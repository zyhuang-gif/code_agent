export const HOST_RUN_EVENT_SCHEMA_VERSION = 1 as const;
export const RUN_EVENT_SCHEMA_VERSION = HOST_RUN_EVENT_SCHEMA_VERSION;

export type RunEventType =
  | "workspace_create_start"
  | "workspace_create_end"
  | "checkpoint_start"
  | "checkpoint_ready"
  | "verification_start"
  | "verification_end"
  | "finish_gate_decision"
  | "diff_generated"
  | "run_result";

export interface HostRunEvent<TType extends RunEventType, TPayload> {
  readonly schemaVersion: typeof HOST_RUN_EVENT_SCHEMA_VERSION;
  readonly sessionId: string;
  readonly type: TType;
  readonly payload: TPayload;
}

export interface WorkspaceCreateStartPayload {
  readonly sourceRepository: string;
  readonly runRoot: string;
}

export interface WorkspaceCreateEndPayload {
  readonly sourceRepository: string;
  readonly runRoot: string;
  readonly runDirectory: string;
  readonly workspace: string;
  readonly artifactsDirectory: string;
}

export interface CheckpointLifecyclePayload {
  readonly runDirectory: string;
  readonly workspace: string;
}

export interface DiffGeneratedPayload {
  readonly diffPath: string;
  readonly byteLength: number;
}

export interface VerificationStartPayload {
  readonly phase: "baseline" | "finish";
  readonly commandHash: string;
  readonly attempt: number;
}

export interface VerificationEndPayload {
  readonly phase: "baseline" | "finish";
  readonly attempt: number;
  readonly status: "passed" | "failed" | "error";
  readonly passed: boolean;
  readonly exitCode: number | null;
  readonly timedOut: boolean;
  readonly durationMs: number;
  readonly errorCode?: string;
}

export interface FinishGateDecisionPayload {
  readonly decision: "allow" | "block";
  readonly status: "passed" | "pre_existing_failure" | "regression" | "error";
  readonly blockedAttempts: number;
  readonly newFailures: readonly string[];
}

export type WorkspaceCreateStartEvent = HostRunEvent<
  "workspace_create_start",
  WorkspaceCreateStartPayload
>;
export type WorkspaceCreateEndEvent = HostRunEvent<
  "workspace_create_end",
  WorkspaceCreateEndPayload
>;
export type CheckpointStartEvent = HostRunEvent<
  "checkpoint_start",
  CheckpointLifecyclePayload
>;
export type CheckpointReadyEvent = HostRunEvent<
  "checkpoint_ready",
  CheckpointLifecyclePayload
>;
export type DiffGeneratedEvent = HostRunEvent<"diff_generated", DiffGeneratedPayload>;
export type VerificationStartEvent = HostRunEvent<"verification_start", VerificationStartPayload>;
export type VerificationEndEvent = HostRunEvent<"verification_end", VerificationEndPayload>;
export type FinishGateDecisionEvent = HostRunEvent<"finish_gate_decision", FinishGateDecisionPayload>;
export type RunResultEvent<TResult = unknown> = HostRunEvent<"run_result", TResult>;

export type RunEvent<TResult = unknown> =
  | WorkspaceCreateStartEvent
  | WorkspaceCreateEndEvent
  | CheckpointStartEvent
  | CheckpointReadyEvent
  | VerificationStartEvent
  | VerificationEndEvent
  | FinishGateDecisionEvent
  | DiffGeneratedEvent
  | RunResultEvent<TResult>;

export interface RunEventSink {
  record(event: RunEvent): Promise<void>;
}

export class DeferredRunEventSink implements RunEventSink {
  readonly #buffer: RunEvent[] = [];
  #delegate: RunEventSink | undefined;
  #tail: Promise<void> = Promise.resolve();

  record(event: RunEvent): Promise<void> {
    return this.#enqueue(async () => {
      if (this.#delegate) {
        await this.#delegate.record(event);
        return;
      }
      this.#buffer.push(event);
    });
  }

  attach(delegate: RunEventSink): Promise<void> {
    if (delegate === this) return Promise.reject(new TypeError("run event sink cannot delegate to itself"));
    return this.#enqueue(async () => {
      if (this.#delegate) throw new Error("run event sink already has a delegate");
      while (this.#buffer.length > 0) {
        const event = this.#buffer[0]!;
        await delegate.record(event);
        this.#buffer.shift();
      }
      this.#delegate = delegate;
    });
  }

  #enqueue(operation: () => Promise<void>): Promise<void> {
    const queued = this.#tail.then(operation);
    this.#tail = queued.catch(() => undefined);
    return queued;
  }
}
