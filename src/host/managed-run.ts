import type { RunResult } from "../engine/contracts.js";
import { FileSystemArtifactStore } from "../governance/artifacts.js";
import type { ArtifactStore } from "../governance/artifacts.js";
import { GitCheckpoint } from "../governance/checkpoint.js";
import type { Checkpoint } from "../governance/checkpoint.js";
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
  readonly reason: string;
  readonly summary: string;
  readonly steps: number;
  readonly usage: RunResult["usage"];
}

export interface ManagedRunDependencies {
  readonly workspaceProvider?: WorkspaceProvider;
  readonly checkpointFactory?: (session: WorkspaceSession) => Checkpoint;
  readonly artifactStoreFactory?: (session: WorkspaceSession) => ArtifactStore;
}

export async function prepareManagedRun(
  request: ManagedRunRequest,
  dependencies: ManagedRunDependencies = {},
): Promise<PreparedManagedRun> {
  const workspaceProvider = dependencies.workspaceProvider ?? new FileSystemWorkspaceProvider();
  const session = await workspaceProvider.create(request);
  const checkpoint = dependencies.checkpointFactory?.(session) ?? new GitCheckpoint({
    repository: session.repository,
    runDirectory: session.runDirectory,
    runRoot: session.runRoot,
    markerPath: session.markerPath,
  });
  const artifacts = dependencies.artifactStoreFactory?.(session) ?? new FileSystemArtifactStore(session);
  await artifacts.initialize();
  await checkpoint.initialize();
  return { session, checkpoint, artifacts };
}

export async function finalizeManagedRun(
  prepared: PreparedManagedRun,
  runtimeResult: RunResult,
): Promise<ManagedRunResult> {
  const diff = await prepared.checkpoint.diff();
  const diffPath = await prepared.artifacts.writeFinalDiff(diff);
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
    reason: runtimeResult.reason,
    summary: runtimeResult.summary,
    steps: runtimeResult.steps,
    usage: runtimeResult.usage,
  };
  await prepared.artifacts.writeResult(result);
  return result;
}
