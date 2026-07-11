import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import type { ArtifactStore } from "../src/governance/artifacts.js";
import type { Checkpoint } from "../src/governance/checkpoint.js";
import {
  HOST_RUN_RESULT_SCHEMA_VERSION,
  finalizeManagedRun,
  prepareManagedRun,
} from "../src/host/managed-run.js";
import type { ManagedRunResult } from "../src/host/managed-run.js";
import { HOST_RUN_EVENT_SCHEMA_VERSION } from "../src/host/run-events.js";
import type { RunEvent, RunEventSink } from "../src/host/run-events.js";
import type { WorkspaceProvider, WorkspaceSession } from "../src/host/workspace.js";
import { EMPTY_USAGE } from "../src/services/model.js";

class RecordingRunEventSink implements RunEventSink {
  readonly events: RunEvent[] = [];

  async record(event: RunEvent): Promise<void> {
    this.events.push(event);
  }
}

test("managed run persists the stable result schema and emits one final run_result", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-managed-run-"));
  try {
    const source = path.join(root, "source");
    const runRoot = path.join(root, "runs");
    await mkdir(source, { recursive: true });
    await writeFile(path.join(source, "file.txt"), "before\n", "utf8");
    const sink = new RecordingRunEventSink();
    const prepared = await prepareManagedRun(
      {
        sessionId: "session-1",
        sourceRepository: source,
        runRoot,
      },
      { runEventSink: sink },
    );
    await writeFile(path.join(prepared.session.repository, "file.txt"), "after\n", "utf8");
    const result = await finalizeManagedRun(prepared, {
      sessionId: "session-1",
      reason: "completed",
      summary: "done",
      steps: 1,
      usage: EMPTY_USAGE,
      messages: [{ role: "user", content: "must not be persisted" }],
    });

    assert.equal(result.type, "run_result");
    assert.equal(result.schemaVersion, HOST_RUN_RESULT_SCHEMA_VERSION);
    assert.equal(result.workspace, prepared.session.repository);
    assert.equal(result.tracePath, prepared.artifacts.paths.tracePath);
    assert.equal(result.verificationPath, prepared.artifacts.paths.verificationPath);
    assert.match(await readFile(result.diffPath, "utf8"), /after/);

    const persisted = JSON.parse(await readFile(result.resultPath, "utf8")) as Record<string, unknown>;
    assert.deepEqual(persisted, result);
    assert.equal("messages" in persisted, false);
    assert.deepEqual(Object.keys(persisted).sort(), [
      "artifactsDirectory",
      "diffPath",
      "mode",
      "reason",
      "resultPath",
      "runDirectory",
      "schemaVersion",
      "sessionId",
      "sourceRepository",
      "steps",
      "summary",
      "tracePath",
      "type",
      "usage",
      "verificationPath",
      "workspace",
    ].sort());

    assert.deepEqual(sink.events.map((event) => event.type), [
      "workspace_create_start",
      "workspace_create_end",
      "checkpoint_start",
      "checkpoint_ready",
      "diff_generated",
      "run_result",
    ]);
    assert.equal(
      sink.events.every((event) => event.schemaVersion === HOST_RUN_EVENT_SCHEMA_VERSION),
      true,
    );
    assert.equal(sink.events.filter((event) => event.type === "run_result").length, 1);
    const finalEvent = sink.events.at(-1);
    assert.equal(finalEvent?.type, "run_result");
    if (finalEvent?.type === "run_result") assert.deepEqual(finalEvent.payload, result);

    const diffEvent = sink.events.find((event) => event.type === "diff_generated");
    assert.equal(diffEvent?.type, "diff_generated");
    if (diffEvent?.type === "diff_generated") {
      assert.equal(diffEvent.payload.diffPath, result.diffPath);
      assert.ok(diffEvent.payload.byteLength > 0);
    }
    assert.equal(await readFile(path.join(source, "file.txt"), "utf8"), "before\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("managed run lifecycle orders workspace, checkpoint, diff, result, and final event", async () => {
  const root = path.resolve("managed-order-fixture");
  const session: WorkspaceSession = {
    sessionId: "ordered-session",
    sourceRepository: path.join(root, "source"),
    runRoot: path.join(root, "runs"),
    runDirectory: path.join(root, "runs", "ordered-session"),
    repository: path.join(root, "runs", "ordered-session", "repository"),
    artifactsDirectory: path.join(root, "runs", "ordered-session", "artifacts"),
    markerPath: path.join(root, "runs", "ordered-session", "run.json"),
  };
  const order: string[] = [];
  let persistedResult: unknown;
  const workspaceProvider: WorkspaceProvider = {
    async create() {
      order.push("workspace:create");
      return session;
    },
  };
  const checkpoint: Checkpoint = {
    async initialize() {
      order.push("checkpoint:initialize");
    },
    async diff() {
      order.push("checkpoint:diff");
      return "diff contents\n";
    },
    async rollback() {},
  };
  const artifactPaths = {
    directory: session.artifactsDirectory,
    diffPath: path.join(session.artifactsDirectory, "final.diff"),
    resultPath: path.join(session.artifactsDirectory, "result.json"),
    tracePath: path.join(session.artifactsDirectory, "trace.jsonl"),
    verificationPath: path.join(session.artifactsDirectory, "verification.json"),
  };
  const artifacts: ArtifactStore = {
    paths: artifactPaths,
    async initialize() {
      order.push("artifacts:initialize");
    },
    async writeFinalDiff() {
      order.push("artifacts:final.diff");
      return artifactPaths.diffPath;
    },
    async writeResult(result) {
      order.push("artifacts:result.json");
      persistedResult = result;
      return artifactPaths.resultPath;
    },
    async writeVerification() {
      return artifactPaths.verificationPath;
    },
  };
  const sink: RunEventSink = {
    async record(event) {
      order.push("event:" + event.type);
    },
  };

  const prepared = await prepareManagedRun(
    {
      sessionId: session.sessionId,
      sourceRepository: session.sourceRepository,
      runRoot: session.runRoot,
    },
    {
      workspaceProvider,
      checkpointFactory: () => checkpoint,
      artifactStoreFactory: () => artifacts,
      runEventSink: sink,
    },
  );
  const result: ManagedRunResult = await finalizeManagedRun(prepared, {
    sessionId: session.sessionId,
    reason: "completed",
    summary: "ordered",
    steps: 3,
    usage: EMPTY_USAGE,
    messages: [],
  });

  assert.deepEqual(order, [
    "event:workspace_create_start",
    "workspace:create",
    "event:workspace_create_end",
    "artifacts:initialize",
    "event:checkpoint_start",
    "checkpoint:initialize",
    "event:checkpoint_ready",
    "checkpoint:diff",
    "artifacts:final.diff",
    "event:diff_generated",
    "artifacts:result.json",
    "event:run_result",
  ]);
  assert.deepEqual(persistedResult, result);
  assert.equal(order.filter((entry) => entry === "event:run_result").length, 1);
  assert.equal(order.at(-1), "event:run_result");
});
