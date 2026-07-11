import type { RunResult } from "../engine/contracts.js";
import { FileSystemArtifactStore } from "../governance/artifacts.js";
import type { ArtifactStore } from "../governance/artifacts.js";
import { GitCheckpoint } from "../governance/checkpoint.js";
import type { Checkpoint } from "../governance/checkpoint.js";
import {
  HOST_RUN_EVENT_SCHEMA_VERSION,
} from "./run-events.js";
import type { RunEvent, RunEventSink } from "./run-events.js";
import { FileSystemWorkspaceProvider } from "./workspace.js";
import type { WorkspaceProvider, WorkspaceSession } from "./workspace.js";

export const HOST_RUN_RESULT_SCHEMA_VERSION = 1 as const;

export interface ManagedRunRequest {
  readonly sessionId: string;
  readonly sourceRepository: string;
  readonly runRoot: string;
  readonly ignorePatterns?: readonly string[];
}

export interface PreparedManagedRun {
  readonly session: WorkspaceSession;
  readonly checkpoint: Checkpoint;
  readonly artifacts: ArtifactStore;
  readonly runEventSink?: RunEventSink;
}

export interface ManagedRunResult {
  readonly type: "run_result";
  readonly schemaVersion: typeof HOST_RUN_RESULT_SCHEMA_VERSION;
  readonly mode: "managed";
  readonly sessionId: string;
  readonly sourceRepository: string;
  readonly workspace: string;
  readonly runDirectory: string;
  readonly artifactsDirectory: string;
  readonly diffPath: string;
  readonly resultPath: string;
  readonly tracePath: string;
  readonly verificationPath: string;
  readonly reason: RunResult["reason"];
  readonly summary: string;
  readonly steps: number;
  readonly usage: RunResult["usage"];
}

export interface ManagedRunDependencies {
  readonly workspaceProvider?: WorkspaceProvider;
  readonly checkpointFactory?: (session: WorkspaceSession) => Checkpoint;
  readonly artifactStoreFactory?: (session: WorkspaceSession) => ArtifactStore;
  readonly runEventSink?: RunEventSink;
}

async function recordRunEvent(
  sink: RunEventSink | undefined,
  event: RunEvent,
): Promise<void> {
  if (sink) await sink.record(event);
}

export async function prepareManagedRun(
  request: ManagedRunRequest,
  dependencies: ManagedRunDependencies = {},
  runEventSink: RunEventSink | undefined = dependencies.runEventSink,
): Promise<PreparedManagedRun> {
  await recordRunEvent(runEventSink, {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "workspace_create_start",
    sessionId: request.sessionId,
    payload: {
      sourceRepository: request.sourceRepository,
      runRoot: request.runRoot,
    },
  });

  const workspaceProvider = dependencies.workspaceProvider ?? new FileSystemWorkspaceProvider();
  const session = await workspaceProvider.create(request);
  await recordRunEvent(runEventSink, {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "workspace_create_end",
    sessionId: session.sessionId,
    payload: {
      sourceRepository: session.sourceRepository,
      runRoot: session.runRoot,
      runDirectory: session.runDirectory,
      workspace: session.repository,
      artifactsDirectory: session.artifactsDirectory,
    },
  });

  const checkpoint = dependencies.checkpointFactory?.(session) ?? new GitCheckpoint({
    repository: session.repository,
    runDirectory: session.runDirectory,
    runRoot: session.runRoot,
    markerPath: session.markerPath,
  });
  const artifacts = dependencies.artifactStoreFactory?.(session) ?? new FileSystemArtifactStore(session);
  await artifacts.initialize();
  await recordRunEvent(runEventSink, {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "checkpoint_start",
    sessionId: session.sessionId,
    payload: {
      runDirectory: session.runDirectory,
      workspace: session.repository,
    },
  });
  await checkpoint.initialize();
  await recordRunEvent(runEventSink, {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "checkpoint_ready",
    sessionId: session.sessionId,
    payload: {
      runDirectory: session.runDirectory,
      workspace: session.repository,
    },
  });

  return {
    session,
    checkpoint,
    artifacts,
    ...(runEventSink ? { runEventSink } : {}),
  };
}

export async function finalizeManagedRun(
  prepared: PreparedManagedRun,
  runtimeResult: RunResult,
  runEventSink: RunEventSink | undefined = prepared.runEventSink,
): Promise<ManagedRunResult> {
  const diff = await prepared.checkpoint.diff();
  const diffPath = await prepared.artifacts.writeFinalDiff(diff);
  await recordRunEvent(runEventSink, {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "diff_generated",
    sessionId: prepared.session.sessionId,
    payload: {
      diffPath,
      byteLength: Buffer.byteLength(diff, "utf8"),
    },
  });

  const result: ManagedRunResult = {
    type: "run_result",
    schemaVersion: HOST_RUN_RESULT_SCHEMA_VERSION,
    mode: "managed",
    sessionId: prepared.session.sessionId,
    sourceRepository: prepared.session.sourceRepository,
    workspace: prepared.session.repository,
    runDirectory: prepared.session.runDirectory,
    artifactsDirectory: prepared.session.artifactsDirectory,
    diffPath,
    resultPath: prepared.artifacts.paths.resultPath,
    tracePath: prepared.artifacts.paths.tracePath,
    verificationPath: prepared.artifacts.paths.verificationPath,
    reason: runtimeResult.reason,
    summary: runtimeResult.summary,
    steps: runtimeResult.steps,
    usage: runtimeResult.usage,
  };
  await prepared.artifacts.writeResult(result);
  await recordRunEvent(runEventSink, {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "run_result",
    sessionId: prepared.session.sessionId,
    payload: result,
  });
  return result;
}
