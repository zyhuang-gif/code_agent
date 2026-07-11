import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
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
