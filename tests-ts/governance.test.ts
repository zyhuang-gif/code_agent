import assert from "node:assert/strict";
import test from "node:test";
import { assessBashCommand } from "../src/governance/bash-safety.js";
import { GovernedToolExecutor } from "../src/governance/executor.js";
import { HookBus } from "../src/governance/hooks.js";
import { PermissionEngine, StaticApprovalProvider } from "../src/governance/permissions.js";
import type { ToolContext, ToolDefinition, ToolPolicy } from "../src/tools/contracts.js";
import { READ_ONLY_POLICY } from "../src/tools/contracts.js";
import { ToolRegistry } from "../src/tools/registry.js";

const context: ToolContext = { workspace: process.cwd(), sessionId: "session", metadata: {} };

function request(policy: ToolPolicy) {
  return {
    sessionId: "session",
    workspace: process.cwd(),
    invocation: { id: "call", name: "tool", input: {} },
    policy,
  };
}

test("permission engine separates read, write, destructive, and plan-mode behavior", () => {
  assert.equal(new PermissionEngine().evaluate(request(READ_ONLY_POLICY)).kind, "allow");
  assert.equal(new PermissionEngine().evaluate(request({ ...READ_ONLY_POLICY, access: "write" })).kind, "ask");
  assert.equal(new PermissionEngine().evaluate(request({ ...READ_ONLY_POLICY, impact: "destructive" })).kind, "ask");
  assert.equal(new PermissionEngine("plan").evaluate(request({ ...READ_ONLY_POLICY, access: "write" })).kind, "deny");
});

test("Bash safety never treats host shell execution as read-only", () => {
  const readCommand = assessBashCommand("git status").policy;
  assert.equal(readCommand.access, "write");
  assert.equal(readCommand.openWorld, true);
  assert.equal(readCommand.concurrency, "serial");
  assert.equal(readCommand.idempotent, false);

  const destructive = assessBashCommand("git reset --hard HEAD").policy;
  assert.equal(destructive.impact, "destructive");
  assert.equal(destructive.concurrency, "exclusive");

  const compound = assessBashCommand("git status & echo modified>../result.json").policy;
  assert.equal(compound.openWorld, true);
  assert.equal(compound.access, "write");
});

test("governed executor asks before a destructive Bash command", async () => {
  const bash: ToolDefinition<{ command: string }> = {
    name: "bash",
    description: "test bash",
    inputSchema: {
      type: "object",
      properties: { command: { type: "string" } },
      required: ["command"],
      additionalProperties: false,
    },
    policy: { ...READ_ONLY_POLICY, access: "write", concurrency: "serial", idempotent: false },
    async execute() { return { status: "success", content: "should not execute" }; },
  };
  const approvals = new StaticApprovalProvider(false);
  const executor = new GovernedToolExecutor(
    new ToolRegistry([bash]),
    new PermissionEngine(),
    approvals,
    new HookBus(),
  );
  const [record] = await executor.executeBatch(
    [{ id: "danger", name: "bash", input: { command: "git reset --hard HEAD" } }],
    context,
  );
  assert.equal(record?.result.status, "denied");
  assert.equal(approvals.requests.length, 1);
});

test("executor runs only parallel-safe batches concurrently", async () => {
  let active = 0;
  let maxActive = 0;
  const makeTool = (name: string, concurrency: ToolPolicy["concurrency"]): ToolDefinition => ({
    name,
    description: name,
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    policy: { ...READ_ONLY_POLICY, concurrency },
    async execute() {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 25));
      active -= 1;
      return { status: "success", content: name };
    },
  });

  const parallelExecutor = new GovernedToolExecutor(
    new ToolRegistry([makeTool("a", "parallel_safe"), makeTool("b", "parallel_safe")]),
    new PermissionEngine(),
    new StaticApprovalProvider(true),
    new HookBus(),
  );
  await parallelExecutor.executeBatch([
    { id: "a", name: "a", input: {} },
    { id: "b", name: "b", input: {} },
  ], context);
  assert.equal(maxActive, 2);

  active = 0;
  maxActive = 0;
  const serialExecutor = new GovernedToolExecutor(
    new ToolRegistry([makeTool("a", "serial"), makeTool("b", "parallel_safe")]),
    new PermissionEngine(),
    new StaticApprovalProvider(true),
    new HookBus(),
  );
  await serialExecutor.executeBatch([
    { id: "a", name: "a", input: {} },
    { id: "b", name: "b", input: {} },
  ], context);
  assert.equal(maxActive, 1);
});

test("pre-tool governance blocks execution and emits a failure lifecycle event", async () => {
  let executed = false;
  let laterExecuted = false;
  let failures = 0;
  const hooks = new HookBus();
  hooks.on("pre_tool_use", (event) => {
    const payload = event.payload as { readonly invocation?: { readonly name?: string } };
    return payload.invocation?.name === "finish"
      ? { action: "block", reason: "verification regression" }
      : undefined;
  });
  hooks.on("post_tool_use_failure", () => { failures += 1; });
  const terminal: ToolDefinition = {
    name: "finish",
    description: "finish",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    policy: { ...READ_ONLY_POLICY, concurrency: "serial" },
    async execute() {
      executed = true;
      return { status: "success", content: "done", terminal: { reason: "completed", summary: "done" } };
    },
  };
  const executor = new GovernedToolExecutor(
    new ToolRegistry([terminal, {
      name: "later_write",
      description: "later write",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      policy: { ...READ_ONLY_POLICY, access: "write", concurrency: "serial" },
      async execute() {
        laterExecuted = true;
        return { status: "success", content: "wrote" };
      },
    }]),
    new PermissionEngine(),
    new StaticApprovalProvider(true),
    hooks,
  );
  const [record] = await executor.executeBatch(
    [
      { id: "finish", name: "finish", input: {} },
      { id: "later", name: "later_write", input: {} },
    ],
    context,
  );
  assert.equal(executed, false);
  assert.equal(record?.result.status, "denied");
  assert.equal(record?.result.terminal, undefined);
  assert.equal(failures, 1);
  assert.equal(laterExecuted, false);
});
