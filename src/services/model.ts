import type { ModelToolDefinition, ToolInvocation } from "../tools/contracts.js";

export type ModelRole = "system" | "user" | "assistant" | "tool";

export interface ModelMessage {
  readonly role: ModelRole;
  readonly content: string | null;
  readonly toolCallId?: string;
  readonly toolCalls?: readonly ToolInvocation[];
}

export interface ModelUsage {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly cacheReadTokens: number;
  readonly cacheWriteTokens: number;
}

export interface ModelRequest {
  readonly messages: readonly ModelMessage[];
  readonly tools: readonly ModelToolDefinition[];
  readonly signal?: AbortSignal;
}

export interface ModelResponse {
  readonly content: string | null;
  readonly toolCalls: readonly ToolInvocation[];
  readonly usage: ModelUsage;
  readonly raw?: unknown;
}

export interface ModelService {
  complete(request: ModelRequest): Promise<ModelResponse>;
}

export interface OpenAICompatibleModelConfig {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly model: string;
  readonly reasoningEffort?: string;
  readonly headers?: Readonly<Record<string, string>>;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("model response must be an object");
  }
  return value as Record<string, unknown>;
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function toWireMessage(message: ModelMessage): Record<string, unknown> {
  if (message.role === "tool") {
    return { role: "tool", content: message.content ?? "", tool_call_id: message.toolCallId ?? "" };
  }
  const wire: Record<string, unknown> = { role: message.role, content: message.content };
  if (message.role === "assistant" && message.toolCalls?.length) {
    wire.tool_calls = message.toolCalls.map((call) => ({
      id: call.id,
      type: "function",
      function: { name: call.name, arguments: JSON.stringify(call.input) },
    }));
  }
  return wire;
}

export class OpenAICompatibleModelService implements ModelService {
  constructor(private readonly config: OpenAICompatibleModelConfig) {}

  async complete(request: ModelRequest): Promise<ModelResponse> {
    const endpoint = this.config.baseUrl.replace(/\/$/, "") + "/chat/completions";
    const body: Record<string, unknown> = {
      model: this.config.model,
      messages: request.messages.map(toWireMessage),
      tools: request.tools.map((tool) => ({
        type: "function",
        function: { name: tool.name, description: tool.description, parameters: tool.inputSchema },
      })),
    };
    if (this.config.reasoningEffort) body.reasoning_effort = this.config.reasoningEffort;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        authorization: "Bearer " + this.config.apiKey,
        "content-type": "application/json",
        ...this.config.headers,
      },
      body: JSON.stringify(body),
      ...(request.signal ? { signal: request.signal } : {}),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error("model request failed (" + String(response.status) + "): " + detail);
    }

    const raw: unknown = await response.json();
    const root = asRecord(raw);
    const choices = Array.isArray(root.choices) ? root.choices : [];
    const firstChoice = choices[0] ? asRecord(choices[0]) : {};
    const message = firstChoice.message ? asRecord(firstChoice.message) : {};
    const rawCalls = Array.isArray(message.tool_calls) ? message.tool_calls : [];
    const toolCalls: ToolInvocation[] = rawCalls.map((value, index) => {
      const call = asRecord(value);
      const fn = call.function ? asRecord(call.function) : {};
      const argumentsText = typeof fn.arguments === "string" ? fn.arguments : "{}";
      let input: unknown;
      try { input = JSON.parse(argumentsText); } catch { input = {}; }
      return {
        id: typeof call.id === "string" ? call.id : "call-" + String(index + 1),
        name: typeof fn.name === "string" ? fn.name : "",
        input,
      };
    });

    const usage = root.usage ? asRecord(root.usage) : {};
    const cacheDetails = usage.prompt_tokens_details ? asRecord(usage.prompt_tokens_details) : {};
    return {
      content: typeof message.content === "string" ? message.content : null,
      toolCalls,
      usage: {
        promptTokens: asNumber(usage.prompt_tokens),
        completionTokens: asNumber(usage.completion_tokens),
        cacheReadTokens: asNumber(cacheDetails.cached_tokens),
        cacheWriteTokens: 0,
      },
      raw,
    };
  }
}

export class ScriptedModelService implements ModelService {
  readonly requests: ModelRequest[] = [];
  readonly #responses: ModelResponse[];
  constructor(responses: readonly ModelResponse[]) { this.#responses = [...responses]; }
  async complete(request: ModelRequest): Promise<ModelResponse> {
    this.requests.push(request);
    const response = this.#responses.shift();
    if (!response) throw new Error("scripted model has no response left");
    return response;
  }
}

export const EMPTY_USAGE: ModelUsage = Object.freeze({
  promptTokens: 0,
  completionTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
});
