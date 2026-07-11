import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createBuiltInTools } from "../src/tools/builtins.js";
import type { ToolContext, ToolDefinition } from "../src/tools/contracts.js";
import { READ_ONLY_POLICY } from "../src/tools/contracts.js";
import { ToolRegistry } from "../src/tools/registry.js";

const context = (workspace: string): ToolContext => ({
  workspace,
  sessionId: "test-session",
  metadata: {},
});

test("tool registry validates model input before execution", async () => {
  let called = false;
  const tool: ToolDefinition<{ value: string }> = {
    name: "echo",
    description: "echo",
    inputSchema: {
      type: "object",
      properties: { value: { type: "string" } },
      required: ["value"],
      additionalProperties: false,
    },
    policy: READ_ONLY_POLICY,
    async execute(input) {
      called = true;
      return { status: "success", content: input.value };
    },
  };
  const registry = new ToolRegistry([tool]);
  const result = await registry.execute("echo", {}, context(process.cwd()));
  assert.equal(result.status, "error");
  assert.match(result.content, /value is required/);
  assert.equal(called, false);
});

test("built-in file tools stay inside the workspace", async () => {
  const workspace = await mkdtemp(path.join(os.tmpdir(), "code-agent-ts-tools-"));
  try {
    await writeFile(path.join(workspace, "hello.txt"), "hello\nworld\n", "utf8");
    const registry = new ToolRegistry(createBuiltInTools());
    const read = await registry.execute("read_file", { path: "hello.txt", startLine: 2 }, context(workspace));
    assert.equal(read.status, "success");
    assert.match(read.content, /2: world/);

    const escaped = await registry.execute("read_file", { path: "../outside.txt" }, context(workspace));
    assert.equal(escaped.status, "error");
    assert.match(escaped.content, /escapes workspace/);

    const gitWrite = await registry.execute("write_file", { path: ".git/config", content: "no" }, context(workspace));
    assert.equal(gitWrite.status, "error");
    assert.match(gitWrite.content, /Git metadata/);

    const write = await registry.execute("write_file", { path: "nested/new.txt", content: "ok" }, context(workspace));
    assert.equal(write.status, "success");
    assert.equal(await readFile(path.join(workspace, "nested/new.txt"), "utf8"), "ok");
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Profile-derived tool config appends ignores and constrains read and grep", async () => {
  const workspace = await mkdtemp(path.join(os.tmpdir(), "code-agent-ts-profile-tools-"));
  try {
    await mkdir(path.join(workspace, ".git"), { recursive: true });
    await mkdir(path.join(workspace, "custom-cache"), { recursive: true });
    await mkdir(path.join(workspace, "generated", "nested"), { recursive: true });
    await writeFile(path.join(workspace, ".git", "config"), "needle\n", "utf8");
    await writeFile(path.join(workspace, "custom-cache", "secret.txt"), "needle\n", "utf8");
    await writeFile(path.join(workspace, "generated", "nested", "secret.txt"), "needle\n", "utf8");
    await writeFile(path.join(workspace, "visible.txt"), "needle\n", "utf8");
    await writeFile(path.join(workspace, "large.txt"), "needle in a file larger than the configured limit\n", "utf8");

    const registry = new ToolRegistry(createBuiltInTools({
      ignore: ["custom-cache", "generated/*"],
      maxFileBytes: 12,
      commandTimeout: 7,
    }));

    const listing = await registry.execute("list_dir", {}, context(workspace));
    assert.equal(listing.status, "success");
    assert.match(listing.content, /visible\.txt/);
    assert.doesNotMatch(listing.content, /\.git/);
    assert.doesNotMatch(listing.content, /custom-cache/);
    assert.doesNotMatch(listing.content, /generated\/nested/);

    const fullRead = await registry.execute("read_file", { path: "large.txt" }, context(workspace));
    assert.equal(fullRead.status, "error");
    assert.match(fullRead.content, /file too large/);

    const rangedRead = await registry.execute(
      "read_file",
      { path: "large.txt", startLine: 1, endLine: 1 },
      context(workspace),
    );
    assert.equal(rangedRead.status, "success");
    assert.match(rangedRead.content, /needle in a file/);

    const grep = await registry.execute("grep", { pattern: "needle" }, context(workspace));
    assert.equal(grep.status, "success");
    assert.match(grep.content, /visible\.txt:1:needle/);
    assert.doesNotMatch(grep.content, /large\.txt/);
    assert.doesNotMatch(grep.content, /secret\.txt/);
    assert.doesNotMatch(grep.content, /\.git/);

    const bash = registry.get("bash");
    assert.equal(bash.inputSchema.properties?.timeoutMs?.default, 7_000);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("default built-in tool config keeps Python-compatible size and timeout defaults", () => {
  const registry = new ToolRegistry(createBuiltInTools());
  assert.equal(registry.get("bash").inputSchema.properties?.timeoutMs?.default, 300_000);
  assert.equal(registry.get("edit_file").name, "edit_file");
});
