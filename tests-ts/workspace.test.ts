import assert from "node:assert/strict";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  FileSystemWorkspaceProvider,
  RUN_MARKER_SCHEMA_VERSION,
  WorkspaceError,
} from "../src/host/workspace.js";

async function pathExists(target: string): Promise<boolean> {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function writeFixture(root: string, relativePath: string, content = relativePath): Promise<void> {
  const target = path.join(root, ...relativePath.split("/"));
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, content, "utf8");
}

async function expectWorkspaceError(
  operation: Promise<unknown>,
  code: WorkspaceError["code"],
  reason?: string,
): Promise<void> {
  await assert.rejects(operation, (error: unknown) => {
    assert.ok(error instanceof WorkspaceError);
    assert.equal(error.code, code);
    if (reason !== undefined) assert.equal(error.details.reason, reason);
    return true;
  });
}

function systemErrorCode(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("code" in error)) return undefined;
  const code = (error as { readonly code?: unknown }).code;
  return typeof code === "string" ? code : undefined;
}

test("workspace provider creates an isolated copy with a fixed run layout and marker", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent 工作区 "));
  try {
    const source = path.join(root, "源 项目");
    const runRoot = path.join(root, "运行 目录");
    await writeFixture(source, "src/问候.txt", "你好，source\n");

    const session = await new FileSystemWorkspaceProvider().create({
      sourceRepository: source,
      runRoot,
      sessionId: "session-一",
    });

    assert.equal(session.sourceRepository, await realpath(source));
    assert.equal(session.runRoot, await realpath(runRoot));
    assert.equal(session.runDirectory, path.join(session.runRoot, "session-一"));
    assert.equal(session.repository, path.join(session.runDirectory, "repository"));
    assert.equal(session.artifactsDirectory, path.join(session.runDirectory, "artifacts"));
    assert.equal(session.markerPath, path.join(session.runDirectory, "run.json"));
    assert.equal(path.dirname(session.repository), session.runDirectory);
    assert.equal(path.dirname(session.artifactsDirectory), session.runDirectory);
    assert.notEqual(session.repository, session.sourceRepository);

    assert.equal(await readFile(path.join(session.repository, "src", "问候.txt"), "utf8"), "你好，source\n");
    await writeFile(path.join(session.repository, "src", "问候.txt"), "isolated change\n", "utf8");
    assert.equal(await readFile(path.join(source, "src", "问候.txt"), "utf8"), "你好，source\n");

    const marker = JSON.parse(await readFile(session.markerPath, "utf8")) as Record<string, unknown>;
    assert.deepEqual(marker, {
      schemaVersion: RUN_MARKER_SCHEMA_VERSION,
      sessionId: "session-一",
      sourceRepository: session.sourceRepository,
      repository: session.repository,
      runDirectory: session.runDirectory,
      runRoot: session.runRoot,
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace copy always applies core ignores and appends user ignore patterns", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-ignore-"));
  try {
    const source = path.join(root, "source");
    const ignoredFiles = [
      ".git/config",
      ".Codex/worktrees/old/metadata",
      "node_modules/pkg/index.js",
      "nested/node_modules/pkg/index.js",
      ".venv/pyvenv.cfg",
      "__pycache__/module.pyc",
      ".pytest_cache/state",
      "dist/output.js",
      "coverage/index.html",
      "workspace/run.txt",
      "trace/events.jsonl",
      ".tmp/cache",
      "custom-cache/value.txt",
      "cmake-build-debug/CMakeCache.txt",
      "logs/ignored.tmp",
    ];
    for (const relativePath of ignoredFiles) await writeFixture(source, relativePath);
    await writeFixture(source, ".Codex/keep.txt", "keep codex metadata outside worktrees");
    await writeFixture(source, "logs/keep.log", "keep log");
    await writeFixture(source, "src/index.ts", "export {};\n");

    const session = await new FileSystemWorkspaceProvider().create({
      sourceRepository: source,
      runRoot: path.join(root, "runs"),
      sessionId: "ignore-test",
      ignorePatterns: ["custom-cache", "cmake-build-*", "logs/*.tmp", "!.git"],
    });

    for (const relativePath of ignoredFiles) {
      assert.equal(
        await pathExists(path.join(session.repository, ...relativePath.split("/"))),
        false,
        `${relativePath} must not be copied`,
      );
    }
    assert.equal(await readFile(path.join(session.repository, ".Codex", "keep.txt"), "utf8"), "keep codex metadata outside worktrees");
    assert.equal(await readFile(path.join(session.repository, "logs", "keep.log"), "utf8"), "keep log");
    assert.equal(await readFile(path.join(session.repository, "src", "index.ts"), "utf8"), "export {};\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace run directories are unique and an existing session directory is never reused", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-unique-"));
  try {
    const source = path.join(root, "source");
    const runRoot = path.join(root, "runs");
    await writeFixture(source, "README.md", "fixture\n");
    const provider = new FileSystemWorkspaceProvider();

    const first = await provider.create({ sourceRepository: source, runRoot, sessionId: "session-a" });
    const second = await provider.create({ sourceRepository: source, runRoot, sessionId: "session-b" });
    assert.notEqual(first.runDirectory, second.runDirectory);
    assert.equal(path.dirname(first.runDirectory), first.runRoot);
    assert.equal(path.dirname(second.runDirectory), second.runRoot);

    await expectWorkspaceError(
      provider.create({ sourceRepository: source, runRoot, sessionId: "session-a" }),
      "run_directory_exists",
    );
    assert.equal(await readFile(path.join(first.repository, "README.md"), "utf8"), "fixture\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("runRoot and sourceRepository directory trees must be completely disjoint", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-run-root-boundary-"));
  try {
    const source = path.join(root, "source");
    await writeFixture(source, "README.md", "source\n");
    const provider = new FileSystemWorkspaceProvider();

    await expectWorkspaceError(
      provider.create({ sourceRepository: source, runRoot: source, sessionId: "equal" }),
      "run_root_invalid",
      "run_root_inside_source",
    );
    assert.equal(await pathExists(path.join(source, "equal")), false);

    const nestedRunRoot = path.join(source, ".runs", "nested");
    await expectWorkspaceError(
      provider.create({ sourceRepository: source, runRoot: nestedRunRoot, sessionId: "nested" }),
      "run_root_invalid",
      "run_root_inside_source",
    );
    assert.equal(await pathExists(path.join(source, ".runs")), false);
    assert.equal(await readFile(path.join(source, "README.md"), "utf8"), "source\n");

    const containingRunRoot = path.join(root, "containing-runs");
    const containedSource = path.join(containingRunRoot, "source-project");
    await writeFixture(containedSource, "README.md", "contained source\n");
    await expectWorkspaceError(
      provider.create({
        sourceRepository: containedSource,
        runRoot: containingRunRoot,
        sessionId: "source-inside-run-root",
      }),
      "run_root_invalid",
      "source_repository_inside_run_root",
    );
    assert.equal(await pathExists(path.join(containingRunRoot, "source-inside-run-root")), false);
    assert.equal(await readFile(path.join(containedSource, "README.md"), "utf8"), "contained source\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("session traversal and a repository path equal to sourceRepository are rejected", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-layout-boundary-"));
  try {
    const provider = new FileSystemWorkspaceProvider();
    const source = path.join(root, "source");
    const externalRunRoot = path.join(root, "runs");
    await writeFixture(source, "README.md", "source\n");

    await expectWorkspaceError(
      provider.create({ sourceRepository: source, runRoot: externalRunRoot, sessionId: "../escape" }),
      "run_root_invalid",
      "invalid_session_id",
    );
    assert.equal(await pathExists(path.join(root, "escape")), false);

    const overlappingRunRoot = path.join(root, "overlap-runs");
    const overlappingSource = path.join(overlappingRunRoot, "same-session", "repository");
    await writeFixture(overlappingSource, "README.md", "overlap\n");
    await expectWorkspaceError(
      provider.create({
        sourceRepository: overlappingSource,
        runRoot: overlappingRunRoot,
        sessionId: "same-session",
      }),
      "run_root_invalid",
      "source_repository_inside_run_root",
    );
    assert.equal(await readFile(path.join(overlappingSource, "README.md"), "utf8"), "overlap\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("sessionId rejects Windows reserved device components on every platform", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-reserved-session-"));
  try {
    const source = path.join(root, "source");
    const runRoot = path.join(root, "runs");
    await writeFixture(source, "README.md", "source\n");
    const provider = new FileSystemWorkspaceProvider();
    const reservedSessionIds = [
      "CON",
      "prn.txt",
      "AUX.log",
      "nul.json",
      ...Array.from({ length: 9 }, (_, index) => `COM${String(index + 1)}.trace`),
      ...Array.from({ length: 9 }, (_, index) => `lpt${String(index + 1)}.txt`),
    ];

    for (const sessionId of reservedSessionIds) {
      await assert.rejects(
        provider.create({ sourceRepository: source, runRoot, sessionId }),
        (error: unknown) => {
          assert.ok(error instanceof WorkspaceError);
          assert.equal(error.code, "run_root_invalid");
          assert.equal(error.details.reason, "invalid_session_id");
          assert.equal(error.details.rule, "windows_reserved_component");
          return true;
        },
      );
      assert.equal(await pathExists(path.join(runRoot, sessionId)), false);
    }

    const allowed = await provider.create({
      sourceRepository: source,
      runRoot,
      sessionId: "COM10.txt",
    });
    assert.equal(path.basename(allowed.runDirectory), "COM10.txt");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
test("invalid source and run root inputs return structured workspace errors", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-invalid-workspace-"));
  try {
    const provider = new FileSystemWorkspaceProvider();
    await expectWorkspaceError(
      provider.create({
        sourceRepository: path.join(root, "missing"),
        runRoot: path.join(root, "runs"),
        sessionId: "missing-source",
      }),
      "source_not_found",
    );

    const sourceFile = path.join(root, "source.txt");
    await writeFile(sourceFile, "not a directory", "utf8");
    await expectWorkspaceError(
      provider.create({
        sourceRepository: sourceFile,
        runRoot: path.join(root, "runs"),
        sessionId: "source-file",
      }),
      "source_not_directory",
    );

    const source = path.join(root, "source");
    await writeFixture(source, "README.md", "source\n");
    const runRootFile = path.join(root, "run-root-file");
    await writeFile(runRootFile, "not a directory", "utf8");
    await expectWorkspaceError(
      provider.create({ sourceRepository: source, runRoot: runRootFile, sessionId: "invalid-run-root" }),
      "run_root_invalid",
      "run_root_not_directory",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace copy refuses symlinks and junctions instead of following them", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-link-safety-"));
  try {
    const source = path.join(root, "source");
    const outside = path.join(root, "outside");
    await writeFixture(source, "README.md", "source\n");
    await writeFixture(outside, "secret.txt", "outside\n");

    const linkPath = path.join(source, "linked-outside");
    try {
      await symlink(outside, linkPath, process.platform === "win32" ? "junction" : "dir");
    } catch (error) {
      if (["EACCES", "EPERM", "ENOSYS", "UNKNOWN"].includes(systemErrorCode(error) ?? "")) {
        t.skip("this platform does not permit creating a test symlink or junction");
        return;
      }
      throw error;
    }

    await expectWorkspaceError(
      new FileSystemWorkspaceProvider().create({
        sourceRepository: source,
        runRoot: path.join(root, "runs"),
        sessionId: "link-test",
      }),
      "unsupported_link",
      "all_links_rejected",
    );
    assert.equal(await readFile(path.join(outside, "secret.txt"), "utf8"), "outside\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
