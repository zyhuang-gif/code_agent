export type AccessMode = "read_only" | "write";
export type ImpactLevel = "non_destructive" | "destructive";
export type ConcurrencyMode = "parallel_safe" | "serial" | "exclusive";

export interface ToolPolicy {
  readonly access: AccessMode;
  readonly impact: ImpactLevel;
  readonly concurrency: ConcurrencyMode;
  readonly idempotent: boolean;
  readonly openWorld: boolean;
}

export interface JsonSchema {
  readonly type?: "object" | "array" | "string" | "number" | "integer" | "boolean" | "null";
  readonly description?: string;
  readonly properties?: Readonly<Record<string, JsonSchema>>;
  readonly required?: readonly string[];
  readonly additionalProperties?: boolean;
  readonly items?: JsonSchema;
  readonly enum?: readonly unknown[];
  readonly default?: unknown;
}

export interface ToolContext {
  readonly workspace: string;
  readonly sessionId: string;
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly signal?: AbortSignal;
}

export interface TerminalSignal {
  readonly reason: string;
  readonly summary: string;
}

export type ToolStatus = "success" | "error" | "denied";

export interface ToolResult<T = unknown> {
  readonly status: ToolStatus;
  readonly content: string;
  readonly data?: T;
  readonly error?: string;
  readonly terminal?: TerminalSignal;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface ToolDefinition<TInput = unknown, TOutput = unknown> {
  readonly name: string;
  readonly description: string;
  readonly inputSchema: JsonSchema;
  readonly outputSchema?: JsonSchema;
  readonly policy: ToolPolicy;
  execute(input: TInput, context: ToolContext): Promise<ToolResult<TOutput>>;
}

export interface ModelToolDefinition {
  readonly name: string;
  readonly description: string;
  readonly inputSchema: JsonSchema;
}

export interface ToolInvocation {
  readonly id: string;
  readonly name: string;
  readonly input: unknown;
}

export interface ToolExecutionRecord {
  readonly invocation: ToolInvocation;
  readonly result: ToolResult;
  readonly policy: ToolPolicy;
}

export interface ToolExecutionService {
  listTools(): readonly ModelToolDefinition[];
  executeBatch(
    invocations: readonly ToolInvocation[],
    context: ToolContext,
  ): Promise<readonly ToolExecutionRecord[]>;
}

export const READ_ONLY_POLICY: ToolPolicy = Object.freeze({
  access: "read_only",
  impact: "non_destructive",
  concurrency: "parallel_safe",
  idempotent: true,
  openWorld: false,
});
