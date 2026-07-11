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

test("Bash safety derives dynamic policy from the command", () => {
  assert.deepEqual(assessBashCommand("git status").policy, READ_ONLY_POLICY);
  const destructive = assessBashCommand("git reset --hard HEAD").policy;
  assert.equal(destructive.impact, "destructive");
  assert.equal(destructive.concurrency, "exclusive");
  const network = assessBashCommand("git push origin master").policy;
  assert.equal(network.openWorld, true);
  assert.equal(network.access, "write");
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
