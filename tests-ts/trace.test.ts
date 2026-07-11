import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import type { AgentEvent } from "../src/engine/contracts.js";
import type { HookEvent } from "../src/governance/hooks.js";
import {
  FileSystemTraceSink,
  TRACE_SCHEMA_VERSION,
  TraceError,
} from "../src/governance/trace.js";
import type {
  Redactor,
  TraceEnvelope,
  TraceFileSystem,
} from "../src/governance/trace.js";
import { DeferredRunEventSink, HOST_RUN_EVENT_SCHEMA_VERSION } from "../src/host/run-events.js";
import type { RunEvent, RunEventSink } from "../src/host/run-events.js";

function parseJsonLines(source: string): TraceEnvelope[] {
  assert.equal(source.endsWith("\n"), true);
  return source.slice(0, -1).split("\n").map((line) => JSON.parse(line) as TraceEnvelope);
}

test("trace sink normalizes Agent, Host, Hook, Permission, and Tool events into one schema", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-trace-schema-"));
  try {
    const timestamps = [
      "2026-07-11T00:00:00.000Z",
      "2026-07-11T00:00:01.000Z",
      "2026-07-11T00:00:02.000Z",
      "2026-07-11T00:00:03.000Z",
      "2026-07-11T00:00:04.000Z",
    ];
    let clockIndex = 0;
    const tracePath = path.join(root, "artifacts", "trace.jsonl");
    const sink = new FileSystemTraceSink(tracePath, {
      clock() {
        const timestamp = timestamps[clockIndex];
        assert.ok(timestamp);
        clockIndex += 1;
        return new Date(timestamp);
      },
    });

    const agentEvent: AgentEvent = {
      type: "model_start",
      sessionId: "session-1",
      step: 2,
    };
    const runEvent: RunEvent = {
      schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
      type: "checkpoint_ready",
      sessionId: "session-1",
      payload: { runDirectory: "run", workspace: "workspace" },
    };
    const hookEvent: HookEvent<{ readonly blocked: boolean }> = {
      type: "permission_request",
      sessionId: "session-1",
      payload: { blocked: false },
    };
    const permissionEvent = {
      type: "permission_decision",
      sessionId: "session-1",
      payload: { decision: "allow", reason: "test" },
    } as const;
    const toolEvent = {
      type: "tool_execution",
      sessionId: "session-1",
      payload: { invocationId: "call-1", status: "success" },
    } as const;

    await sink.record(agentEvent);
    await sink.record(runEvent);
    await sink.record(hookEvent);
    await sink.record(permissionEvent);
    await sink.record(toolEvent);

    const envelopes = parseJsonLines(await readFile(tracePath, "utf8"));
    assert.deepEqual(envelopes, [
      {
        schemaVersion: TRACE_SCHEMA_VERSION,
        timestamp: timestamps[0],
        sessionId: "session-1",
        type: "model_start",
        payload: { step: 2 },
      },
      {
        schemaVersion: TRACE_SCHEMA_VERSION,
        timestamp: timestamps[1],
        sessionId: "session-1",
        type: "checkpoint_ready",
        payload: { runDirectory: "run", workspace: "workspace" },
      },
      {
        schemaVersion: TRACE_SCHEMA_VERSION,
        timestamp: timestamps[2],
        sessionId: "session-1",
        type: "permission_request",
        payload: { blocked: false },
      },
      {
        schemaVersion: TRACE_SCHEMA_VERSION,
        timestamp: timestamps[3],
        sessionId: "session-1",
        type: "permission_decision",
        payload: { decision: "allow", reason: "test" },
      },
      {
        schemaVersion: TRACE_SCHEMA_VERSION,
        timestamp: timestamps[4],
        sessionId: "session-1",
        type: "tool_execution",
        payload: { invocationId: "call-1", status: "success" },
      },
    ]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("trace sink serializes concurrent record calls without interleaving and preserves call order", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-trace-concurrent-"));
  try {
    const tracePath = path.join(root, "trace.jsonl");
    const sink = new FileSystemTraceSink(tracePath);
    const events = Array.from({ length: 80 }, (_, index) => ({
      type: "tool_event",
      sessionId: "concurrent-session",
      payload: {
        index,
        content: (`line-${index}\n` + "x".repeat(4096)).repeat(2),
      },
    }));

    await Promise.all(events.map((event) => sink.record(event)));

    const envelopes = parseJsonLines(await readFile(tracePath, "utf8"));
    assert.equal(envelopes.length, events.length);
    assert.deepEqual(
      envelopes.map((envelope) => (envelope.payload as { readonly index: number }).index),
      events.map((event) => event.payload.index),
    );
    for (const [index, envelope] of envelopes.entries()) {
      assert.equal(envelope.schemaVersion, TRACE_SCHEMA_VERSION);
      assert.equal(envelope.type, "tool_event");
      assert.equal(envelope.sessionId, "concurrent-session");
      assert.equal(
        (envelope.payload as { readonly content: string }).content,
        events[index]?.payload.content,
      );
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("trace failures reject with TraceError, queue recovery remains explicit, and redaction runs first", async () => {
  let appendAttempts = 0;
  let appended = "";
  const fileSystem: TraceFileSystem = {
    async mkdir() {},
    async appendFile(_target, data) {
      appendAttempts += 1;
      if (appendAttempts === 1) throw new Error("disk full");
      appended += data;
    },
  };
  const redactor: Redactor = {
    redact(value) {
      const payload = value as Readonly<Record<string, unknown>>;
      return { ...payload, secret: "[redacted]" };
    },
  };
  const sink = new FileSystemTraceSink(path.resolve("trace-failure.jsonl"), {
    fileSystem,
    redactor,
    clock: () => new Date("2026-07-11T01:00:00.000Z"),
  });

  const failed = sink.record({
    type: "permission_event",
    sessionId: "failure-session",
    payload: { secret: "raw" },
  });
  const recovered = sink.record({
    type: "tool_event",
    sessionId: "failure-session",
    payload: { secret: "raw", status: "success" },
  });

  await assert.rejects(failed, (error: unknown) => {
    assert.ok(error instanceof TraceError);
    assert.equal(error.code, "trace_write_failed");
    assert.equal(error.sessionId, "failure-session");
    assert.equal(error.eventType, "permission_event");
    assert.match(error.message, /failed to append trace event/);
    assert.ok(error.originalCause instanceof Error);
    return true;
  });
  await recovered;

  const [envelope] = parseJsonLines(appended);
  assert.deepEqual(envelope?.payload, { secret: "[redacted]", status: "success" });
  assert.equal(appendAttempts, 2);

  await assert.rejects(
    sink.record({
      type: "serialization_event",
      sessionId: "failure-session",
      payload: { unsupported: 1n },
    }),
    (error: unknown) => error instanceof TraceError && error.code === "trace_serialize_failed",
  );
  assert.equal(appendAttempts, 2);
});

test("deferred run event sink replays buffered events before forwarding new events", async () => {
  const deferred = new DeferredRunEventSink();
  const recorded: RunEvent[] = [];
  const delegate: RunEventSink = {
    async record(event) {
      recorded.push(event);
    },
  };
  const start: RunEvent = {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "workspace_create_start",
    sessionId: "deferred-session",
    payload: { sourceRepository: "source", runRoot: "runs" },
  };
  const ready: RunEvent = {
    schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
    type: "checkpoint_ready",
    sessionId: "deferred-session",
    payload: { runDirectory: "run", workspace: "workspace" },
  };

  await deferred.record(start);
  await deferred.attach(delegate);
  await deferred.record(ready);

  assert.deepEqual(recorded, [start, ready]);
  await assert.rejects(deferred.attach(delegate), /already has a delegate/);
  await assert.rejects(deferred.attach(deferred), /cannot delegate to itself/);
});
