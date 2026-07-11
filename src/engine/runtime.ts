import { randomUUID } from "node:crypto";
import type { ContextService } from "../services/context.js";
import type { ModelMessage, ModelRequest, ModelResponse, ModelService, ModelUsage } from "../services/model.js";
import { EMPTY_USAGE } from "../services/model.js";
import type { ToolContext, ToolExecutionService } from "../tools/contracts.js";
import { HookBus } from "../governance/hooks.js";
import type { AgentEvent, AgentRequest, RunResult, StopReason } from "./contracts.js";

const DEFAULT_SYSTEM_PROMPT = [
  "You are a code agent.",
  "Use the available tools to inspect and modify the workspace.",
  "Use workspace-relative paths.",
  "Call finish when the task is complete.",
].join(" ");

function addUsage(left: ModelUsage, right: ModelUsage): ModelUsage {
  return {
    promptTokens: left.promptTokens + right.promptTokens,
    completionTokens: left.completionTokens + right.completionTokens,
    cacheReadTokens: left.cacheReadTokens + right.cacheReadTokens,
    cacheWriteTokens: left.cacheWriteTokens + right.cacheWriteTokens,
  };
}

export class AgentRuntime {
  constructor(
    private readonly model: ModelService,
    private readonly context: ContextService,
    private readonly tools: ToolExecutionService,
    private readonly hooks: HookBus = new HookBus(),
  ) {}

  async *run(request: AgentRequest): AsyncGenerator<AgentEvent, RunResult, void> {
    const sessionId = request.sessionId ?? randomUUID();
    const maxSteps = request.maxSteps ?? 40;
    let usage: ModelUsage = { ...EMPTY_USAGE };
    let messages: ModelMessage[] = [
      { role: "system" as const, content: request.systemPrompt ?? DEFAULT_SYSTEM_PROMPT },
      { role: "user" as const, content: request.task },
    ];

    await this.hooks.emit({
      type: "session_start",
      sessionId,
      payload: { workspace: request.workspace, task: request.task },
    });
    await this.hooks.emit({ type: "user_prompt_submit", sessionId, payload: { task: request.task } });
    yield { type: "session_start", sessionId, workspace: request.workspace, task: request.task };

    const finish = async (reason: StopReason, summary: string, steps: number): Promise<RunResult> => {
      const result: RunResult = { sessionId, reason, summary, steps, usage, messages };
      await this.hooks.emit({ type: "stop", sessionId, payload: result });
      await this.hooks.emit({ type: "session_end", sessionId, payload: result });
      return result;
    };

    for (let step = 1; step <= maxSteps; step += 1) {
      if (request.signal?.aborted) {
        const result = await finish("cancelled", "request cancelled", step - 1);
        yield { type: "session_end", sessionId, result };
        return result;
      }

      const prepared = await this.context.prepare(messages);
      if (prepared.compacted) {
        const compactHook = await this.hooks.emit({
          type: "pre_compact",
          sessionId,
          payload: { originalMessages: messages, preparation: prepared },
        });
        if (!compactHook.blocked) {
          messages = [...prepared.messages];
          await this.hooks.emit({ type: "post_compact", sessionId, payload: prepared });
          yield {
            type: "context_compacted",
            sessionId,
            removedMessages: prepared.removedMessages,
            summary: prepared.summary ?? "",
          };
        }
      }

      let modelRequest: ModelRequest = {
        messages,
        tools: this.tools.listTools(),
        ...(request.signal ? { signal: request.signal } : {}),
      };
      const preModel = await this.hooks.emit<ModelRequest>({
        type: "pre_model_call",
        sessionId,
        payload: modelRequest,
      });
      if (preModel.blocked) {
        const result = await finish("policy_denied", preModel.reason ?? "model call blocked", step - 1);
        yield { type: "session_end", sessionId, result };
        return result;
      }
      modelRequest = preModel.payload;

      yield { type: "model_start", sessionId, step };
      let response: ModelResponse;
      try {
        response = await this.model.complete(modelRequest);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const result = await finish("model_error", message, step - 1);
        yield { type: "session_end", sessionId, result };
        return result;
      }
      usage = addUsage(usage, response.usage);
      await this.hooks.emit({ type: "post_model_call", sessionId, payload: response });
      yield {
        type: "model_end",
        sessionId,
        step,
        toolCalls: response.toolCalls,
        content: response.content,
        usage: response.usage,
      };

      messages = [
        ...messages,
        {
          role: "assistant" as const,
          content: response.content,
          ...(response.toolCalls.length ? { toolCalls: response.toolCalls } : {}),
        },
      ];

      if (response.toolCalls.length === 0) {
        messages.push({
          role: "user",
          content: "Continue with tools, or call finish when the task is complete.",
        });
        continue;
      }

      for (const invocation of response.toolCalls) {
        yield { type: "tool_start", sessionId, step, invocation };
      }
      const toolContext: ToolContext = {
        workspace: request.workspace,
        sessionId,
        metadata: request.metadata ?? {},
        ...(request.signal ? { signal: request.signal } : {}),
      };
      const records = await this.tools.executeBatch(response.toolCalls, toolContext);
      for (const record of records) {
        messages.push({
          role: "tool",
          toolCallId: record.invocation.id,
          content: record.result.content,
        });
        yield { type: "tool_end", sessionId, step, record };
      }

      const terminal = records.find((record) => record.result.terminal)?.result.terminal;
      if (terminal) {
        const reason: StopReason = terminal.reason === "completed" ? "completed" : "internal_error";
        const result = await finish(reason, terminal.summary, step);
        yield { type: "session_end", sessionId, result };
        return result;
      }
    }

    const result = await finish("budget_exceeded", "maximum agent steps reached", maxSteps);
    yield { type: "session_end", sessionId, result };
    return result;
  }
}

export async function collectRun(
  stream: AsyncGenerator<AgentEvent, RunResult, void>,
): Promise<{ readonly events: readonly AgentEvent[]; readonly result: RunResult }> {
  const events: AgentEvent[] = [];
  while (true) {
    const item = await stream.next();
    if (item.done) return { events, result: item.value };
    events.push(item.value);
  }
}
