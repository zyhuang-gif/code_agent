import type {
  ModelToolDefinition,
  ToolContext,
  ToolExecutionRecord,
  ToolExecutionService,
  ToolInvocation,
  ToolPolicy,
  ToolResult,
} from "../tools/contracts.js";
import { ToolRegistry } from "../tools/registry.js";
import { assessBashCommand } from "./bash-safety.js";
import { HookBus } from "./hooks.js";
import type { ApprovalProvider, PermissionDecision, PermissionRequest } from "./permissions.js";
import { PermissionEngine } from "./permissions.js";

interface PreToolPayload {
  readonly invocation: ToolInvocation;
  readonly policy: ToolPolicy;
}

interface PermissionPayload {
  readonly request: PermissionRequest;
  readonly decision: PermissionDecision;
}

const UNKNOWN_TOOL_POLICY: ToolPolicy = Object.freeze({
  access: "write",
  impact: "destructive",
  concurrency: "exclusive",
  idempotent: false,
  openWorld: true,
});

function deniedResult(reason: string): ToolResult {
  return { status: "denied", content: reason, error: reason };
}

function errorResult(reason: string): ToolResult {
  return { status: "error", content: reason, error: reason };
}

export class GovernedToolExecutor implements ToolExecutionService {
  constructor(
    private readonly registry: ToolRegistry,
    private readonly permissions: PermissionEngine,
    private readonly approvals: ApprovalProvider,
    private readonly hooks: HookBus,
  ) {}

  listTools(): readonly ModelToolDefinition[] {
    return this.registry.toModelTools();
  }

  #policyFor(invocation: ToolInvocation): ToolPolicy {
    const definition = this.registry.get(invocation.name);
    if (invocation.name !== "bash") {
      return definition.policy;
    }
    if (typeof invocation.input !== "object" || invocation.input === null || Array.isArray(invocation.input)) {
      return definition.policy;
    }
    const command = (invocation.input as Record<string, unknown>).command;
    return typeof command === "string" ? assessBashCommand(command).policy : definition.policy;
  }

  async #executeOne(invocation: ToolInvocation, context: ToolContext): Promise<ToolExecutionRecord> {
    let policy: ToolPolicy;
    try {
      policy = this.#policyFor(invocation);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { invocation, policy: UNKNOWN_TOOL_POLICY, result: errorResult(message) };
    }

    const preTool = await this.hooks.emit<PreToolPayload>({
      type: "pre_tool_use",
      sessionId: context.sessionId,
      payload: { invocation, policy },
    });
    if (preTool.blocked) {
      const record = {
        invocation,
        policy,
        result: deniedResult(preTool.reason ?? "blocked by pre-tool hook"),
      };
      await this.hooks.emit({
        type: "post_tool_use_failure",
        sessionId: context.sessionId,
        payload: record,
      });
      return record;
    }

    const effectiveInvocation = preTool.payload.invocation;
    try {
      policy = this.#policyFor(effectiveInvocation);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { invocation: effectiveInvocation, policy: UNKNOWN_TOOL_POLICY, result: errorResult(message) };
    }

    const request: PermissionRequest = {
      sessionId: context.sessionId,
      workspace: context.workspace,
      invocation: effectiveInvocation,
      policy,
    };
    let decision = this.permissions.evaluate(request);
    const permissionHook = await this.hooks.emit<PermissionPayload>({
      type: "permission_request",
      sessionId: context.sessionId,
      payload: { request, decision },
    });
    if (permissionHook.blocked) {
      decision = { kind: "deny", reason: permissionHook.reason ?? "blocked by permission hook" };
    } else {
      decision = permissionHook.payload.decision;
    }

    if (decision.kind === "deny") {
      return { invocation: effectiveInvocation, policy, result: deniedResult(decision.reason) };
    }
    if (decision.kind === "ask") {
      const approved = await this.approvals.requestApproval(request, decision);
      if (!approved) {
        return {
          invocation: effectiveInvocation,
          policy,
          result: deniedResult(`approval rejected: ${decision.reason}`),
        };
      }
    }

    const result = await this.registry.execute(effectiveInvocation.name, effectiveInvocation.input, context);
    const hookType = result.status === "success" ? "post_tool_use" : "post_tool_use_failure";
    await this.hooks.emit({
      type: hookType,
      sessionId: context.sessionId,
      payload: { invocation: effectiveInvocation, policy, result },
    });
    return { invocation: effectiveInvocation, policy, result };
  }

  async executeBatch(
    invocations: readonly ToolInvocation[],
    context: ToolContext,
  ): Promise<readonly ToolExecutionRecord[]> {
    const allParallelSafe = invocations.every((invocation) => {
      try {
        return this.#policyFor(invocation).concurrency === "parallel_safe";
      } catch {
        return false;
      }
    });

    if (allParallelSafe) {
      return Promise.all(invocations.map((invocation) => this.#executeOne(invocation, context)));
    }

    const records: ToolExecutionRecord[] = [];
    for (const invocation of invocations) {
      const record = await this.#executeOne(invocation, context);
      records.push(record);
      if (invocation.name === "finish" || record.result.terminal) break;
    }
    return records;
  }
}
