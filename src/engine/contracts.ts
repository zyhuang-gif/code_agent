import type { ModelMessage, ModelUsage } from "../services/model.js";
import type { ToolExecutionRecord, ToolInvocation } from "../tools/contracts.js";

export type StopReason =
  | "completed"
  | "budget_exceeded"
  | "policy_denied"
  | "model_error"
  | "cancelled"
  | "internal_error";

export interface AgentRequest {
  readonly task: string;
  readonly workspace: string;
  readonly systemPrompt?: string;
  readonly sessionId?: string;
  readonly maxSteps?: number;
  readonly metadata?: Readonly<Record<string, unknown>>;
  readonly signal?: AbortSignal;
}

export interface AgentSession {
  readonly id: string;
  readonly workspace: string;
  readonly task: string;
  readonly messages: readonly ModelMessage[];
  readonly step: number;
  readonly usage: ModelUsage;
}

export type AgentEvent =
  | { readonly type: "session_start"; readonly sessionId: string; readonly workspace: string; readonly task: string }
  | { readonly type: "context_compacted"; readonly sessionId: string; readonly removedMessages: number; readonly summary: string }
  | { readonly type: "model_start"; readonly sessionId: string; readonly step: number }
  | { readonly type: "model_end"; readonly sessionId: string; readonly step: number; readonly toolCalls: readonly ToolInvocation[]; readonly content: string | null; readonly usage: ModelUsage }
  | { readonly type: "tool_start"; readonly sessionId: string; readonly step: number; readonly invocation: ToolInvocation }
  | { readonly type: "tool_end"; readonly sessionId: string; readonly step: number; readonly record: ToolExecutionRecord }
  | { readonly type: "session_end"; readonly sessionId: string; readonly result: RunResult };

export interface RunResult {
  readonly sessionId: string;
  readonly reason: StopReason;
  readonly summary: string;
  readonly steps: number;
  readonly usage: ModelUsage;
  readonly messages: readonly ModelMessage[];
}
