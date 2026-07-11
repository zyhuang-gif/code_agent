import { open } from "node:fs/promises";
import type { ModelResponse, ModelUsage } from "../services/model.js";

const MAX_MODEL_SCRIPT_BYTES = 1024 * 1024;
const MAX_RESPONSES = 100;
const MAX_TOOL_CALLS_PER_RESPONSE = 50;

const ROOT_FIELDS = new Set(["schemaVersion", "responses"]);
const RESPONSE_FIELDS = new Set(["content", "toolCalls", "usage"]);
const TOOL_CALL_FIELDS = new Set(["id", "name", "input"]);
const USAGE_FIELDS = new Set([
  "promptTokens",
  "completionTokens",
  "cacheReadTokens",
  "cacheWriteTokens",
]);

export type ModelScriptErrorCode =
  | "read_error"
  | "file_too_large"
  | "json_parse_error"
  | "invalid_schema_version"
  | "invalid_type"
  | "unknown_field"
  | "out_of_range"
  | "invalid_value"
  | "duplicate_tool_call_id";

export interface ModelScriptErrorOptions {
  readonly code: ModelScriptErrorCode;
  readonly source: string;
  readonly cause?: unknown;
}

export interface SerializedModelScriptError {
  readonly name: "ModelScriptError";
  readonly code: ModelScriptErrorCode;
  readonly source: string;
  readonly message: string;
}

export class ModelScriptError extends Error {
  readonly code: ModelScriptErrorCode;
  readonly source: string;

  constructor(message: string, options: ModelScriptErrorOptions) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "ModelScriptError";
    this.code = options.code;
    this.source = options.source;
  }

  toJSON(): SerializedModelScriptError {
    return {
      name: "ModelScriptError",
      code: this.code,
      source: this.source,
      message: this.message,
    };
  }
}

type JsonObject = Record<string, unknown>;

function fail(
  source: string,
  code: ModelScriptErrorCode,
  message: string,
  cause?: unknown,
): never {
  throw new ModelScriptError(message, {
    code,
    source,
    ...(cause === undefined ? {} : { cause }),
  });
}

function asObject(value: unknown, source: string, field: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(source, "invalid_type", `${field} must be a JSON object`);
  }
  return value as JsonObject;
}

function rejectUnknownFields(
  value: JsonObject,
  allowed: ReadonlySet<string>,
  source: string,
  field: string,
): void {
  const unknown = Object.keys(value).filter((key) => !allowed.has(key));
  if (unknown.length > 0) {
    fail(source, "unknown_field", `${field} contains unknown field: ${unknown.join(", ")}`);
  }
}

function parseUsage(value: unknown, source: string, field: string): ModelUsage {
  const usage = asObject(value, source, field);
  rejectUnknownFields(usage, USAGE_FIELDS, source, field);

  const result: Record<keyof ModelUsage, number> = {
    promptTokens: 0,
    completionTokens: 0,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
  };
  for (const key of USAGE_FIELDS as ReadonlySet<keyof ModelUsage>) {
    const tokenCount = usage[key];
    if (typeof tokenCount !== "number" || !Number.isSafeInteger(tokenCount) || tokenCount < 0) {
      fail(source, "invalid_value", `${field}.${key} must be a non-negative safe integer`);
    }
    result[key] = tokenCount;
  }
  return result;
}

function parseResponse(value: unknown, source: string, index: number): ModelResponse {
  const field = `responses[${index}]`;
  const response = asObject(value, source, field);
  rejectUnknownFields(response, RESPONSE_FIELDS, source, field);

  if (typeof response.content !== "string" && response.content !== null) {
    fail(source, "invalid_type", `${field}.content must be a string or null`);
  }
  if (!Array.isArray(response.toolCalls)) {
    fail(source, "invalid_type", `${field}.toolCalls must be an array`);
  }
  if (response.toolCalls.length > MAX_TOOL_CALLS_PER_RESPONSE) {
    fail(
      source,
      "out_of_range",
      `${field}.toolCalls must contain at most ${String(MAX_TOOL_CALLS_PER_RESPONSE)} calls`,
    );
  }

  const callIds = new Set<string>();
  const toolCalls = response.toolCalls.map((value, callIndex) => {
    const callField = `${field}.toolCalls[${callIndex}]`;
    const call = asObject(value, source, callField);
    rejectUnknownFields(call, TOOL_CALL_FIELDS, source, callField);

    if (typeof call.id !== "string" || call.id.length === 0) {
      fail(source, "invalid_value", `${callField}.id must be a non-empty string`);
    }
    if (callIds.has(call.id)) {
      fail(source, "duplicate_tool_call_id", `${field} contains duplicate tool call id: ${call.id}`);
    }
    callIds.add(call.id);

    if (typeof call.name !== "string" || call.name.length === 0) {
      fail(source, "invalid_value", `${callField}.name must be a non-empty string`);
    }
    asObject(call.input, source, `${callField}.input`);

    return { id: call.id, name: call.name, input: call.input };
  });

  const usage = response.usage === undefined
    ? { promptTokens: 0, completionTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 }
    : parseUsage(response.usage, source, `${field}.usage`);

  return { content: response.content, toolCalls, usage };
}

function parseModelScript(text: string, source: string): readonly ModelResponse[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch (error) {
    fail(source, "json_parse_error", `failed to parse model script JSON: ${source}`, error);
  }

  const root = asObject(parsed, source, "model script");
  rejectUnknownFields(root, ROOT_FIELDS, source, "model script");
  if (root.schemaVersion !== 1) {
    fail(source, "invalid_schema_version", "model script schemaVersion must equal 1");
  }
  if (!Array.isArray(root.responses)) {
    fail(source, "invalid_type", "model script responses must be an array");
  }
  if (root.responses.length < 1 || root.responses.length > MAX_RESPONSES) {
    fail(source, "out_of_range", `model script responses must contain 1..${String(MAX_RESPONSES)} items`);
  }

  return root.responses.map((value, index) => parseResponse(value, source, index));
}

export async function loadModelScript(source: string): Promise<readonly ModelResponse[]> {
  let bytes: Buffer;
  try {
    const file = await open(source, "r");
    try {
      const stats = await file.stat();
      if (!stats.isFile()) {
        fail(source, "read_error", `model script must be a regular file: ${source}`);
      }
      if (stats.size > MAX_MODEL_SCRIPT_BYTES) {
        fail(
          source,
          "file_too_large",
          `model script exceeds the ${String(MAX_MODEL_SCRIPT_BYTES)} byte limit: ${source}`,
        );
      }
      const bounded = Buffer.allocUnsafe(MAX_MODEL_SCRIPT_BYTES + 1);
      let offset = 0;
      while (offset < bounded.length) {
        const { bytesRead } = await file.read(bounded, offset, bounded.length - offset, null);
        if (bytesRead === 0) break;
        offset += bytesRead;
      }
      bytes = bounded.subarray(0, offset);
    } finally {
      await file.close();
    }
  } catch (error) {
    if (error instanceof ModelScriptError) throw error;
    fail(source, "read_error", `failed to read model script: ${source}`, error);
  }

  if (bytes.length > MAX_MODEL_SCRIPT_BYTES) {
    fail(
      source,
      "file_too_large",
      `model script exceeds the ${String(MAX_MODEL_SCRIPT_BYTES)} byte limit: ${source}`,
    );
  }

  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes).replace(/^\uFEFF/, "");
  } catch (error) {
    fail(source, "json_parse_error", `model script is not valid UTF-8: ${source}`, error);
  }
  return parseModelScript(text, source);
}
