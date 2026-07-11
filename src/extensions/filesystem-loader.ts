import { readFile, readdir, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { isStableSkillDefinitionSource } from "./contracts.js";
import type { AgentExtension, ExtensionManifest, SkillDefinition } from "./contracts.js";

function parseStringList(value: string): readonly string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function parseSkillMarkdown(markdown: string, source?: string): SkillDefinition {
  const normalized = markdown.replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---\n")) {
    throw new Error("skill must start with YAML-like frontmatter");
  }
  const end = normalized.indexOf("\n---\n", 4);
  if (end < 0) throw new Error("skill frontmatter is not closed");
  const header = normalized.slice(4, end);
  const body = normalized.slice(end + 5).trim();
  const metadata = new Map<string, string>();
  for (const line of header.split("\n")) {
    const separator = line.indexOf(":");
    if (separator < 0) continue;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, "");
    metadata.set(key, value);
  }
  const name = metadata.get("name");
  const description = metadata.get("description");
  if (!name || !description) throw new Error("skill requires name and description");
  const allowedTools = metadata.has("allowed-tools")
    ? parseStringList(metadata.get("allowed-tools") ?? "")
    : undefined;
  if (source !== undefined && !isStableSkillDefinitionSource(source)) {
    throw new Error("skill definition source must be a stable relative path: " + source);
  }
  return {
    name,
    description,
    instructions: body,
    ...(allowedTools ? { allowedTools } : {}),
    ...(source ? { source } : {}),
  };
}

function toPosixRelative(root: string, target: string): string {
  return path.relative(root, target).split(path.sep).join(path.posix.sep);
}

async function loadExtension(root: string, directory: string): Promise<AgentExtension> {
  const manifestPath = path.join(directory, "plugin.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as ExtensionManifest;
  if (!manifest.name) throw new Error("extension manifest requires name: " + manifestPath);
  const resolvedDirectory = await realpath(directory);
  const skills: SkillDefinition[] = [];
  for (const relative of manifest.skills ?? []) {
    const skillPath = path.resolve(directory, relative);
    const escaped = path.relative(directory, skillPath);
    if (escaped.startsWith("..") || path.isAbsolute(escaped)) {
      throw new Error("skill path escapes extension: " + relative);
    }
    const resolvedSkillPath = await realpath(skillPath);
    const resolvedEscape = path.relative(resolvedDirectory, resolvedSkillPath);
    if (resolvedEscape.startsWith("..") || path.isAbsolute(resolvedEscape)) {
      throw new Error("skill path escapes extension through a link: " + relative);
    }
    if (!(await stat(resolvedSkillPath)).isFile()) {
      throw new Error("skill path is not a regular file: " + relative);
    }
    const source = toPosixRelative(root, skillPath);
    skills.push(parseSkillMarkdown(await readFile(resolvedSkillPath, "utf8"), source));
  }
  return { name: manifest.name, skills };
}

export async function loadExtensions(root: string): Promise<readonly AgentExtension[]> {
  let entries;
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch (error) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT") return [];
    throw new Error("failed to read extensions root: " + path.resolve(root), { cause: error });
  }
  const extensions: AgentExtension[] = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    if (!entry.isDirectory()) continue;
    extensions.push(await loadExtension(root, path.join(root, entry.name)));
  }
  return extensions;
}
