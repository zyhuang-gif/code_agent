import assert from "node:assert/strict";
import test from "node:test";
import { collectRun, AgentRuntime } from "../src/engine/runtime.js";
import { GovernedToolExecutor } from "../src/governance/executor.js";
import { HookBus } from "../src/governance/hooks.js";
import { PermissionEngine, StaticApprovalProvider } from "../src/governance/permissions.js";
import { CompactingContextService } from "../src/services/context.js";
import { EMPTY_USAGE, ScriptedModelService } from "../src/services/model.js";
import type { ToolDefinition } from "../src/tools/contracts.js";
import { READ_ONLY_POLICY } from "../src/tools/contracts.js";
import { ToolRegistry } from "../src/tools/registry.js";

const inspect: ToolDefinition = {
  name: "inspect",
  description: "inspect",
  inputSchema: { type: "object", properties: {}, additionalProperties: false },
  policy: READ_ONLY_POLICY,
  async execute() { return { status: "success", content: "inspection" }; },
};

const finish: ToolDefinition<{ summary: string }> = {
  name: "finish",
  description: "finish",
  inputSchema: {
    type: "object",
    properties: { summary: { type: "string" } },
    required: ["summary"],
    additionalProperties: false,
  },
  policy: { ...READ_ONLY_POLICY, concurrency: "serial" },
  async execute(input) {
    return {
      status: "success",
      content: input.summary,
      terminal: { reason: "completed", summary: input.summary },
    };
  },
};

test("engine coordinates model and tools without domain-specific logic", async () => {
  const model = new ScriptedModelService([
    {
      content: null,
      toolCalls: [{ id: "inspect-1", name: "inspect", input: {} }],
      usage: { ...EMPTY_USAGE, promptTokens: 10 },
    },
    {
      content: null,
      toolCalls: [{ id: "finish-1", name: "finish", input: { summary: "done" } }],
      usage: { ...EMPTY_USAGE, completionTokens: 3 },
    },
  ]);
  const hooks = new HookBus();
  const executor = new GovernedToolExecutor(
    new ToolRegistry([inspect, finish]),
    new PermissionEngine(),
    new StaticApprovalProvider(true),
    hooks,
  );
  const runtime = new AgentRuntime(model, new CompactingContextService(), executor, hooks);
  const { events, result } = await collectRun(runtime.run({
    task: "inspect and finish",
    workspace: process.cwd(),
    sessionId: "runtime-test",
  }));
  assert.equal(result.reason, "completed");
  assert.equal(result.summary, "done");
  assert.equal(result.steps, 2);
  assert.equal(result.usage.promptTokens, 10);
  assert.equal(result.usage.completionTokens, 3);
  assert.deepEqual(events.filter((event) => event.type === "tool_start").map((event) => event.invocation.name), ["inspect", "finish"]);
  assert.equal(model.requests[1]?.messages.at(-1)?.role, "tool");
});

test("pre-model hook can stop the runtime through governance", async () => {
  const hooks = new HookBus();
  hooks.on("pre_model_call", () => ({ action: "block", reason: "organization policy" }));
  const runtime = new AgentRuntime(
    new ScriptedModelService([]),
    new CompactingContextService(),
    new GovernedToolExecutor(
      new ToolRegistry([finish]),
      new PermissionEngine(),
      new StaticApprovalProvider(true),
      hooks,
    ),
    hooks,
  );
  const { result } = await collectRun(runtime.run({ task: "blocked", workspace: process.cwd() }));
  assert.equal(result.reason, "policy_denied");
  assert.equal(result.summary, "organization policy");
});
