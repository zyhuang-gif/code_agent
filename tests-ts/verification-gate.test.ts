import assert from "node:assert/strict";
import { access, mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import type { ArtifactStore } from "../src/governance/artifacts.js";
import { HookBus } from "../src/governance/hooks.js";
import type {
  VerificationAttempt,
  VerificationConfig,
  VerificationExecutor,
  VerificationPhase,
} from "../src/governance/verification.js";
import { VerificationError } from "../src/governance/verification.js";
import { ProjectProfile } from "../src/host/project-profile.js";
import type { RunEvent, RunEventSink } from "../src/host/run-events.js";
import { FileSystemVerificationWorkspaceFactory, VerificationGate } from "../src/host/verification-gate.js";
import type { VerificationReport } from "../src/host/verification-gate.js";
import { READ_ONLY_POLICY } from "../src/tools/contracts.js";

function attempt(
  phase: VerificationPhase,
  passed: boolean,
  failureKeys: readonly string[],
): VerificationAttempt {
  return {
    phase,
    command: "test command",
    timeoutMs: 1_000,
    startedAt: "2026-07-11T00:00:00.000Z",
    durationMs: 5,
    exitCode: passed ? 0 : 1,
    passed,
    timedOut: false,
    outputLimitExceeded: false,
    stdout: passed ? "ok" : failureKeys.join("\n"),
    stderr: "",
    failureKeys,
    failureKeysReliable: true,
    fingerprint: failureKeys.join("|"),
  };
}

class QueueVerificationExecutor implements VerificationExecutor {
  readonly calls: Array<{ readonly workspace: string; readonly config: VerificationConfig; readonly phase: VerificationPhase }> = [];
  constructor(private readonly attempts: VerificationAttempt[]) {}
  async run(workspace: string, config: VerificationConfig, phase: VerificationPhase): Promise<VerificationAttempt | null> {
    this.calls.push({ workspace, config, phase });
    return this.attempts.shift() ?? null;
  }
}

function fixture(executor: VerificationExecutor) {
  const hooks = new HookBus();
  const events: RunEvent[] = [];
  const reports: VerificationReport[] = [];
  let cleanups = 0;
  const directory = path.resolve("verification-artifacts");
  const artifacts: ArtifactStore = {
    paths: {
      directory,
      diffPath: path.join(directory, "final.diff"),
      resultPath: path.join(directory, "result.json"),
      tracePath: path.join(directory, "trace.jsonl"),
      verificationPath: path.join(directory, "verification.json"),
    },
    async initialize() {},
    async writeFinalDiff() { return this.paths.diffPath; },
    async writeResult() { return this.paths.resultPath; },
    async writeVerification(report) {
      reports.push(report as VerificationReport);
      return this.paths.verificationPath;
    },
  };
  const sink: RunEventSink = { async record(event) { events.push(event); } };
  const gate = new VerificationGate({
    sessionId: "gate-session",
    workspace: path.resolve("verification-workspace"),
    profile: new ProjectProfile({ testCmd: "test command", testTimeout: 10 }),
    artifacts,
    hooks,
    runEventSink: sink,
    runner: executor,
    workspaceFactory: {
      async create(sourceWorkspace) {
        return {
          workspace: sourceWorkspace + "-verification-copy",
          async cleanup() { cleanups += 1; },
        };
      },
    },
  });
  return { gate, hooks, events, reports, get cleanups() { return cleanups; } };
}

const finishPayload = {
  invocation: { id: "finish-call", name: "finish", input: { summary: "done" } },
  policy: { ...READ_ONLY_POLICY, concurrency: "serial" as const },
};

test("finish gate allows only pre-existing failures and persists the comparison", async () => {
  const executor = new QueueVerificationExecutor([
    attempt("baseline", false, ["FAILED test_a"]),
    attempt("finish", false, ["FAILED test_a"]),
  ]);
  const state = fixture(executor);
  await state.gate.initialize();
  state.gate.register();
  const emission = await state.hooks.emit({ type: "pre_tool_use", sessionId: "gate-session", payload: finishPayload });

  assert.equal(emission.blocked, false);
  assert.equal(state.gate.report.decision, "pre_existing_failure");
  assert.equal(state.cleanups, 2);
  assert.deepEqual(state.events.map((event) => event.type), [
    "verification_start",
    "verification_end",
    "verification_start",
    "verification_end",
    "finish_gate_decision",
  ]);
  assert.equal(state.reports.at(-1)?.decision, "pre_existing_failure");
});

test("finish gate blocks every regression attempt without changing engine stop semantics", async () => {
  const executor = new QueueVerificationExecutor([
    attempt("baseline", true, []),
    attempt("finish", false, ["FAILED test_b"]),
    attempt("finish", false, ["FAILED test_b"]),
  ]);
  const state = fixture(executor);
  await state.gate.initialize();
  state.gate.register();

  const first = await state.hooks.emit({ type: "pre_tool_use", sessionId: "gate-session", payload: finishPayload });
  assert.equal(first.blocked, true);
  assert.match(first.reason ?? "", /Finish blocked/);
  assert.equal(state.gate.report.blockedAttempts, 1);

  const second = await state.hooks.emit({ type: "pre_tool_use", sessionId: "gate-session", payload: finishPayload });
  assert.equal(second.blocked, true);
  assert.equal(state.gate.report.decision, "blocked");
  assert.equal(state.gate.report.blockedAttempts, 2);
  assert.equal(state.events.filter((event) => event.type === "finish_gate_decision").length, 2);
});

test("verification gate writes not_configured without executing or rolling back", async () => {
  const executor = new QueueVerificationExecutor([]);
  const hooks = new HookBus();
  let persisted: VerificationReport | undefined;
  const directory = path.resolve("verification-artifacts");
  const gate = new VerificationGate({
    sessionId: "no-verification",
    workspace: process.cwd(),
    profile: new ProjectProfile(),
    artifacts: {
      paths: {
        directory,
        diffPath: path.join(directory, "final.diff"),
        resultPath: path.join(directory, "result.json"),
        tracePath: path.join(directory, "trace.jsonl"),
        verificationPath: path.join(directory, "verification.json"),
      },
      async initialize() {},
      async writeFinalDiff() { return this.paths.diffPath; },
      async writeResult() { return this.paths.resultPath; },
      async writeVerification(report) { persisted = report as VerificationReport; return this.paths.verificationPath; },
    },
    hooks,
    runner: executor,
    workspaceFactory: {
      async create() { throw new Error("unexpected verification workspace"); },
    },
  });
  await gate.initialize();
  gate.register();
  assert.equal(persisted?.decision, "not_configured");
  assert.equal(executor.calls.length, 0);
});

test("finish verification infrastructure errors close events, persist error, and block", async () => {
  const baseline = attempt("baseline", true, []);
  let calls = 0;
  const executor: VerificationExecutor = {
    async run() {
      calls += 1;
      if (calls === 1) return baseline;
      throw new VerificationError("verification_spawn_failed", "runner unavailable");
    },
  };
  const state = fixture(executor);
  await state.gate.initialize();
  state.gate.register();

  const emission = await state.hooks.emit({
    type: "pre_tool_use",
    sessionId: "gate-session",
    payload: finishPayload,
  });

  assert.equal(emission.blocked, true);
  assert.match(emission.reason ?? "", /verification failed to run/);
  assert.equal(state.gate.report.decision, "error");
  assert.equal(state.gate.report.error?.code, "verification_spawn_failed");
  const verificationEnd = state.events.filter((event) => event.type === "verification_end").at(-1);
  assert.equal(verificationEnd?.type, "verification_end");
  if (verificationEnd?.type === "verification_end") {
    assert.equal(verificationEnd.payload.status, "error");
    assert.equal(verificationEnd.payload.errorCode, "verification_spawn_failed");
  }
  const decision = state.events.at(-1);
  assert.equal(decision?.type, "finish_gate_decision");
  if (decision?.type === "finish_gate_decision") assert.equal(decision.payload.status, "error");
});

test("baseline infrastructure errors persist evidence and prevent runtime setup", async () => {
  const state = fixture({
    async run() {
      throw new VerificationError("verification_workspace_unsafe", "unsafe baseline workspace");
    },
  });

  await assert.rejects(state.gate.initialize(), /unsafe baseline workspace/);
  assert.equal(state.gate.report.decision, "error");
  assert.equal(state.gate.report.error?.code, "verification_workspace_unsafe");
  assert.equal(state.cleanups, 1);
  const end = state.events.at(-1);
  assert.equal(end?.type, "verification_end");
  if (end?.type === "verification_end") assert.equal(end.payload.status, "error");
});

test("filesystem verification workspace isolates test side effects from the agent workspace", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-verification-copy-"));
  try {
    const source = path.join(root, "repository");
    const scratchRoot = path.join(root, "verification-workspaces");
    await mkdir(source, { recursive: true });
    await writeFile(path.join(source, "source.txt"), "original\n", "utf8");
    const factory = new FileSystemVerificationWorkspaceFactory(scratchRoot);
    const verificationWorkspace = await factory.create(source, "finish", 1);
    await writeFile(path.join(verificationWorkspace.workspace, "generated.txt"), "test side effect\n", "utf8");
    await verificationWorkspace.cleanup();

    assert.equal(await access(path.join(source, "source.txt")).then(() => true), true);
    await assert.rejects(access(path.join(source, "generated.txt")));
    await assert.rejects(access(verificationWorkspace.workspace));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
