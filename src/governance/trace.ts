import { appendFile as nodeAppendFile, mkdir as nodeMkdir } from "node:fs/promises";
import path from "node:path";

export const TRACE_SCHEMA_VERSION = 1 as const;

export interface TraceRecordEvent {
  readonly sessionId: string;
  readonly type: string;
}

export interface TraceEnvelope<TPayload = unknown> {
  readonly schemaVersion: typeof TRACE_SCHEMA_VERSION;
  readonly timestamp: string;
  readonly sessionId: string;
  readonly type: string;
  readonly payload: TPayload;
}

export interface Redactor {
  redact(value: unknown): unknown;
}

export interface TraceSink {
  readonly tracePath: string;
  record<TEvent extends TraceRecordEvent>(event: TEvent): Promise<void>;
}

export type TraceErrorCode =
  | "trace_event_invalid"
  | "trace_redaction_failed"
  | "trace_serialize_failed"
  | "trace_write_failed";

export interface TraceErrorDetails {
  readonly code: TraceErrorCode;
  readonly message: string;
  readonly tracePath: string;
  readonly sessionId?: string;
  readonly eventType?: string;
  readonly cause?: unknown;
}

export class TraceError extends Error {
  readonly code: TraceErrorCode;
  readonly tracePath: string;
  readonly sessionId: string | undefined;
  readonly eventType: string | undefined;
  readonly originalCause: unknown;

  constructor(details: TraceErrorDetails) {
    super(details.message, details.cause === undefined ? undefined : { cause: details.cause });
    this.name = "TraceError";
    this.code = details.code;
    this.tracePath = details.tracePath;
    this.sessionId = details.sessionId;
    this.eventType = details.eventType;
    this.originalCause = details.cause;
  }
}

export interface TraceFileSystem {
  mkdir(target: string, options: { readonly recursive: true }): Promise<void>;
  appendFile(
    target: string,
    data: string,
    options: { readonly encoding: "utf8"; readonly flag: "a" },
  ): Promise<void>;
}

export interface FileSystemTraceSinkOptions {
  readonly redactor?: Redactor;
  readonly clock?: () => Date;
  readonly fileSystem?: TraceFileSystem;
}

const nodeTraceFileSystem: TraceFileSystem = {
  async mkdir(target, options) {
    await nodeMkdir(target, options);
  },
  async appendFile(target, data, options) {
    await nodeAppendFile(target, data, options);
  },
};

const identityRedactor: Redactor = Object.freeze({
  redact(value: unknown): unknown {
    return value;
  },
});

function recordContext(event: unknown): { readonly sessionId?: string; readonly eventType?: string } {
  if (typeof event !== "object" || event === null || Array.isArray(event)) return {};
  const record = event as Readonly<Record<string, unknown>>;
  return {
    ...(typeof record.sessionId === "string" ? { sessionId: record.sessionId } : {}),
    ...(typeof record.type === "string" ? { eventType: record.type } : {}),
  };
}

function normalizePayload(record: Readonly<Record<string, unknown>>): unknown {
  if (Object.prototype.hasOwnProperty.call(record, "payload")) return record.payload;
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(record)) {
    if (key !== "sessionId" && key !== "type") payload[key] = value;
  }
  return payload;
}

function jsonRootValue(value: unknown): unknown {
  return value === undefined || typeof value === "function" || typeof value === "symbol"
    ? null
    : value;
}

export class FileSystemTraceSink implements TraceSink {
  readonly tracePath: string;
  readonly #redactor: Redactor;
  readonly #clock: () => Date;
  readonly #fileSystem: TraceFileSystem;
  #initialized = false;
  #tail: Promise<void> = Promise.resolve();

  constructor(tracePath: string, options: FileSystemTraceSinkOptions = {}) {
    this.tracePath = path.resolve(tracePath);
    this.#redactor = options.redactor ?? identityRedactor;
    this.#clock = options.clock ?? (() => new Date());
    this.#fileSystem = options.fileSystem ?? nodeTraceFileSystem;
  }

  record<TEvent extends TraceRecordEvent>(event: TEvent): Promise<void> {
    const operation = this.#tail.then(() => this.#append(event));
    this.#tail = operation.catch(() => undefined);
    return operation;
  }

  #traceError(
    code: TraceErrorCode,
    message: string,
    event: unknown,
    cause?: unknown,
  ): TraceError {
    return new TraceError({
      code,
      message,
      tracePath: this.tracePath,
      ...recordContext(event),
      ...(cause === undefined ? {} : { cause }),
    });
  }

  #validateEvent(event: unknown): Readonly<Record<string, unknown>> {
    if (typeof event !== "object" || event === null || Array.isArray(event)) {
      throw this.#traceError(
        "trace_event_invalid",
        "trace event must be an object",
        event,
      );
    }
    const record = event as Readonly<Record<string, unknown>>;
    if (typeof record.sessionId !== "string" || record.sessionId.trim().length === 0) {
      throw this.#traceError(
        "trace_event_invalid",
        "trace event sessionId must be a non-empty string",
        event,
      );
    }
    if (typeof record.type !== "string" || record.type.trim().length === 0) {
      throw this.#traceError(
        "trace_event_invalid",
        "trace event type must be a non-empty string",
        event,
      );
    }
    return record;
  }

  async #append(event: unknown): Promise<void> {
    const record = this.#validateEvent(event);
    let payload: unknown;
    try {
      payload = jsonRootValue(this.#redactor.redact(normalizePayload(record)));
    } catch (error) {
      throw this.#traceError(
        "trace_redaction_failed",
        "failed to redact trace event payload",
        event,
        error,
      );
    }

    let timestamp: string;
    try {
      timestamp = this.#clock().toISOString();
    } catch (error) {
      throw this.#traceError(
        "trace_serialize_failed",
        "failed to create trace event timestamp",
        event,
        error,
      );
    }

    const envelope: TraceEnvelope = {
      schemaVersion: TRACE_SCHEMA_VERSION,
      timestamp,
      sessionId: record.sessionId as string,
      type: record.type as string,
      payload,
    };

    let line: string;
    try {
      line = JSON.stringify(envelope) + "\n";
    } catch (error) {
      throw this.#traceError(
        "trace_serialize_failed",
        "failed to serialize trace event",
        event,
        error,
      );
    }

    try {
      if (!this.#initialized) {
        await this.#fileSystem.mkdir(path.dirname(this.tracePath), { recursive: true });
        this.#initialized = true;
      }
      await this.#fileSystem.appendFile(this.tracePath, line, { encoding: "utf8", flag: "a" });
    } catch (error) {
      throw this.#traceError(
        "trace_write_failed",
        "failed to append trace event: " + this.tracePath,
        event,
        error,
      );
    }
  }
}

export { FileSystemTraceSink as JsonlTraceSink };
