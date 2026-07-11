import { spawn } from "node:child_process";
import type { Dirent } from "node:fs";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import type { JsonSchema, ToolDefinition, ToolPolicy } from "./contracts.js";
import { READ_ONLY_POLICY } from "./contracts.js";
import { resolveWorkspacePath } from "./path-safety.js";

const WRITE_POLICY: ToolPolicy = Object.freeze({
  access: "write",
  impact: "non_destructive",
  concurrency: "serial",
  idempotent: false,
  openWorld: false,
});

const BASH_POLICY: ToolPolicy = Object.freeze({
  access: "write",
  impact: "non_destructive",
  concurrency: "serial",
  idempotent: false,
  openWorld: false,
});

const IGNORED_DIRECTORIES = new Set([".git", "node_modules", ".venv", "__pycache__", "dist"]);

function objectSchema(
  properties: Readonly<Record<string, JsonSchema>>,
  required: readonly string[] = [],
): JsonSchema {
  return { type: "object", properties, required, additionalProperties: false };
}

function truncate(text: string, limit = 8_000): string {
  if (text.length <= limit) return text;
  const half = Math.floor(limit / 2);
  return text.slice(0, half) + "\n...<truncated>...\n" + text.slice(-half);
}

function globPattern(pattern: string): RegExp {
  const escaped = pattern
    .replace(/[.+^$()|[\]\\{}]/g, "\\$&")
    .replaceAll("**", "__DOUBLE_STAR__")
    .replaceAll("*", "[^/]*")
    .replaceAll("__DOUBLE_STAR__", ".*")
    .replaceAll("?", ".");
  return new RegExp("^" + escaped + "$", "i");
}

async function walkFiles(root: string, maxEntries = 1_000): Promise<string[]> {
  const files: string[] = [];
  async function visit(directory: string): Promise<void> {
    if (files.length >= maxEntries) return;
    let entries: Dirent[];
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch {
      return;
    }
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      if (files.length >= maxEntries) return;
      if (entry.isDirectory() && IGNORED_DIRECTORIES.has(entry.name)) continue;
      const absolute = path.join(directory, entry.name);
      files.push(absolute);
      if (entry.isDirectory()) await visit(absolute);
    }
  }
  await visit(root);
  return files;
}

interface ListDirectoryInput { readonly path?: string }
interface ReadFileInput { readonly path: string; readonly startLine?: number; readonly endLine?: number }
interface GrepInput { readonly pattern: string; readonly glob?: string }
interface EditInput { readonly path: string; readonly search: string; readonly replace: string }
interface WriteFileInput { readonly path: string; readonly content: string }
interface BashInput { readonly command: string; readonly timeoutMs?: number }
interface FinishInput { readonly summary: string }

function listDirectoryTool(): ToolDefinition<ListDirectoryInput, { readonly entries: readonly string[] }> {
  return {
    name: "list_dir",
    description: "List files below a workspace-relative directory.",
    inputSchema: objectSchema({ path: { type: "string", default: "." } }),
    policy: READ_ONLY_POLICY,
    async execute(input, context) {
      const root = await resolveWorkspacePath(context.workspace, input.path ?? ".", { mustExist: true });
      const entries = await walkFiles(root);
      const workspace = await resolveWorkspacePath(context.workspace, ".", { mustExist: true });
      const relative = entries.map((entry) => path.relative(workspace, entry).split(path.sep).join("/"));
      return { status: "success", content: truncate(relative.join("\n")), data: { entries: relative } };
    },
  };
}

function readFileTool(): ToolDefinition<ReadFileInput> {
  return {
    name: "read_file",
    description: "Read a UTF-8 file range with line numbers. Paths are workspace-relative.",
    inputSchema: objectSchema(
      {
        path: { type: "string" },
        startLine: { type: "integer" },
        endLine: { type: "integer" },
      },
      ["path"],
    ),
    policy: READ_ONLY_POLICY,
    async execute(input, context) {
      const file = await resolveWorkspacePath(context.workspace, input.path, { mustExist: true });
      const details = await stat(file);
      if (!details.isFile()) return { status: "error", content: "path is not a file", error: "path is not a file" };
      if (details.size > 500_000 && (input.startLine === undefined || input.endLine === undefined)) {
        return { status: "error", content: "file too large; specify startLine and endLine", error: "file too large" };
      }
      const lines = (await readFile(file, "utf8")).split(/\r?\n/);
      const start = Math.max(1, input.startLine ?? 1);
      const end = Math.min(lines.length, input.endLine ?? lines.length);
      const content = lines.slice(start - 1, end).map((line, index) => String(start + index) + ": " + line).join("\n");
      return { status: "success", content: truncate(content) };
    },
  };
}

function grepTool(): ToolDefinition<GrepInput> {
  return {
    name: "grep",
    description: "Search UTF-8 workspace files with a regular expression.",
    inputSchema: objectSchema(
      { pattern: { type: "string" }, glob: { type: "string" } },
      ["pattern"],
    ),
    policy: READ_ONLY_POLICY,
    async execute(input, context) {
      const regex = new RegExp(input.pattern);
      const matchGlob = input.glob ? globPattern(input.glob) : null;
      const workspace = await resolveWorkspacePath(context.workspace, ".", { mustExist: true });
      const candidates = await walkFiles(workspace, 5_000);
      const hits: string[] = [];
      for (const candidate of candidates) {
        const details = await stat(candidate).catch(() => null);
        if (!details?.isFile() || details.size > 500_000) continue;
        const relative = path.relative(workspace, candidate).split(path.sep).join("/");
        if (matchGlob && !matchGlob.test(relative)) continue;
        let text: string;
        try {
          text = await readFile(candidate, "utf8");
        } catch {
          continue;
        }
        for (const [index, line] of text.split(/\r?\n/).entries()) {
          regex.lastIndex = 0;
          if (regex.test(line)) hits.push(relative + ":" + String(index + 1) + ":" + line);
          if (hits.length >= 500) break;
        }
        if (hits.length >= 500) break;
      }
      return { status: "success", content: truncate(hits.join("\n")), data: hits };
    },
  };
}

function editTool(): ToolDefinition<EditInput> {
  return {
    name: "edit_file",
    description: "Replace one unique text occurrence in a workspace file.",
    inputSchema: objectSchema(
      { path: { type: "string" }, search: { type: "string" }, replace: { type: "string" } },
      ["path", "search", "replace"],
    ),
    policy: WRITE_POLICY,
    async execute(input, context) {
      const file = await resolveWorkspacePath(context.workspace, input.path, { mustExist: true, writable: true });
      const original = await readFile(file, "utf8");
      const parts = original.split(input.search);
      if (parts.length === 1) return { status: "error", content: "search text not found", error: "search text not found" };
      if (parts.length > 2) return { status: "error", content: "search text is ambiguous", error: "search text is ambiguous" };
      await writeFile(file, parts[0] + input.replace + parts[1], "utf8");
      return { status: "success", content: "edited " + input.path };
    },
  };
}

function writeFileTool(): ToolDefinition<WriteFileInput> {
  return {
    name: "write_file",
    description: "Create or overwrite a UTF-8 file inside the workspace.",
    inputSchema: objectSchema(
      { path: { type: "string" }, content: { type: "string" } },
      ["path", "content"],
    ),
    policy: WRITE_POLICY,
    async execute(input, context) {
      const file = await resolveWorkspacePath(context.workspace, input.path, { writable: true });
      await mkdir(path.dirname(file), { recursive: true });
      await writeFile(file, input.content, "utf8");
      return { status: "success", content: "wrote " + input.path };
    },
  };
}

async function runShell(
  command: string,
  cwd: string,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<{ readonly exitCode: number; readonly stdout: string; readonly stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, {
      cwd,
      shell: true,
      windowsHide: true,
      signal,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    const append = (current: string, chunk: Buffer): string => truncate(current + chunk.toString("utf8"), 500_000);
    child.stdout.on("data", (chunk: Buffer) => { stdout = append(stdout, chunk); });
    child.stderr.on("data", (chunk: Buffer) => { stderr = append(stderr, chunk); });
    const timer = setTimeout(() => child.kill(), timeoutMs);
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      resolve({ exitCode: code ?? 1, stdout, stderr });
    });
  });
}

function bashTool(): ToolDefinition<BashInput, { readonly exitCode: number }> {
  return {
    name: "bash",
    description: "Run a shell command in the workspace. Dynamic governance classifies each command before execution.",
    inputSchema: objectSchema(
      { command: { type: "string" }, timeoutMs: { type: "integer", default: 300_000 } },
      ["command"],
    ),
    policy: BASH_POLICY,
    async execute(input, context) {
      const timeoutMs = Math.max(1, Math.min(input.timeoutMs ?? 300_000, 900_000));
      const result = await runShell(input.command, context.workspace, timeoutMs, context.signal);
      const content = truncate(
        "exit_code=" + String(result.exitCode) + "\nstdout:\n" + result.stdout + "\nstderr:\n" + result.stderr,
      );
      if (result.exitCode === 0) {
        return { status: "success", content, data: { exitCode: result.exitCode } };
      }
      return {
        status: "error",
        content,
        data: { exitCode: result.exitCode },
        error: "command exited with " + String(result.exitCode),
      };
    },
  };
}

function finishTool(): ToolDefinition<FinishInput> {
  return {
    name: "finish",
    description: "Finish the current agent task with a concise summary.",
    inputSchema: objectSchema({ summary: { type: "string" } }, ["summary"]),
    policy: { ...READ_ONLY_POLICY, concurrency: "serial" },
    async execute(input) {
      return {
        status: "success",
        content: input.summary,
        terminal: { reason: "completed", summary: input.summary },
      };
    },
  };
}

export function createBuiltInTools(): readonly ToolDefinition[] {
  return [
    listDirectoryTool(),
    readFileTool(),
    grepTool(),
    editTool(),
    writeFileTool(),
    bashTool(),
    finishTool(),
  ];
}
