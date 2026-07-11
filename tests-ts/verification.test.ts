import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import type { CommandRunner, CommandRunOptions, CommandResult } from "../src/governance/checkpoint.js";
import {
  compareVerification,
  VerificationError,
  VerificationRunner,
} from "../src/governance/verification.js";
import type { VerificationAttempt, VerificationConfig } from "../src/governance/verification.js";

class QueueCommandRunner implements CommandRunner {
  readonly calls: Array<{ readonly command: string; readonly args: readonly string[]; readonly options: CommandRunOptions }> = [];

  constructor(private readonly results: CommandResult[]) {}

  async run(command: string, args: readonly string[], options: CommandRunOptions): Promise<CommandResult> {
    this.calls.push({ command, args, options });
    const result = this.results.shift();
    if (!result) throw new Error("missing command result");
    return result;
  }
}

const config: VerificationConfig = {
  command: "node -e \"process.exit(0)\"",
  timeoutSeconds: 12,
  passWhen: "exit_zero",
};

test("verification runner uses a fixed platform shell and exit_zero semantics", async () => {
  const previousApiKey = process.env.CODE_AGENT_API_KEY;
  process.env.CODE_AGENT_API_KEY = "must-not-reach-verification";
  const commandRunner = new QueueCommandRunner([{ exitCode: 0, stdout: "ok\n", stderr: "" }]);
  const timestamps = [new Date("2026-07-11T00:00:00.000Z"), new Date("2026-07-11T00:00:00.025Z")];
  const runner = new VerificationRunner({ commandRunner, clock: () => timestamps.shift()! });
  const workspace = path.resolve("verification-workspace");
  let attempt: VerificationAttempt | null;
  try {
    attempt = await runner.run(workspace, config, "baseline");
  } finally {
    if (previousApiKey === undefined) delete process.env.CODE_AGENT_API_KEY;
    else process.env.CODE_AGENT_API_KEY = previousApiKey;
  }

  assert.equal(attempt?.passed, true);
  assert.equal(attempt?.exitCode, 0);
  assert.equal(attempt?.durationMs, 25);
  assert.equal(commandRunner.calls[0]?.options.cwd, workspace);
  assert.equal(commandRunner.calls[0]?.options.timeoutMs, 12_000);
  assert.equal(commandRunner.calls[0]?.options.maxOutputBytes, 2 * 1024 * 1024);
  assert.equal(commandRunner.calls[0]?.options.env?.CI, process.env.CI ?? "1");
  assert.equal(commandRunner.calls[0]?.options.env?.CODE_AGENT_API_KEY, undefined);
  if (process.platform === "win32") {
    assert.match(commandRunner.calls[0]?.command ?? "", /cmd\.exe$/i);
    assert.deepEqual(commandRunner.calls[0]?.args.slice(0, 3), ["/d", "/s", "/c"]);
  } else {
    assert.equal(commandRunner.calls[0]?.command, "/bin/sh");
    assert.deepEqual(commandRunner.calls[0]?.args.slice(0, 1), ["-c"]);
  }
});

test("verification runner rejects destructive, network, and unsupported pass policies before spawn", async () => {
  const commandRunner = new QueueCommandRunner([]);
  const runner = new VerificationRunner({ commandRunner });
  const workspace = path.resolve("verification-workspace");

  await assert.rejects(
    runner.run(workspace, { ...config, command: "git reset --hard HEAD" }, "baseline"),
    (error: unknown) => error instanceof VerificationError && error.code === "verification_command_destructive",
  );
  await assert.rejects(
    runner.run(workspace, { ...config, command: "npm install" }, "baseline"),
    (error: unknown) => error instanceof VerificationError && error.code === "verification_network_denied",
  );
  await assert.rejects(
    runner.run(workspace, { ...config, command: "python -m pip install package" }, "baseline"),
    (error: unknown) => error instanceof VerificationError && error.code === "verification_network_denied",
  );
  await assert.rejects(
    runner.run(workspace, { ...config, passWhen: "custom" }, "baseline"),
    (error: unknown) => error instanceof VerificationError && error.code === "verification_pass_rule_unsupported",
  );
  assert.equal(commandRunner.calls.length, 0);
});

test("verification runner treats an unresolved command as an infrastructure error", async () => {
  const commandRunner = new QueueCommandRunner([{
    exitCode: process.platform === "win32" ? 1 : 127,
    stdout: "",
    stderr: process.platform === "win32"
      ? "'missing-tool' is not recognized as an internal or external command"
      : "/bin/sh: missing-tool: command not found",
  }]);
  const runner = new VerificationRunner({ commandRunner });
  await assert.rejects(
    runner.run(path.resolve("verification-workspace"), { ...config, command: "missing-tool" }, "baseline"),
    (error: unknown) => error instanceof VerificationError && error.code === "verification_command_not_found",
  );
});

test("failure comparison uses full captured output even when persisted summaries are truncated", async () => {
  const commandRunner = new QueueCommandRunner([
    { exitCode: 1, stdout: "FAILED test_a\n" + "x".repeat(200), stderr: "" },
    { exitCode: 1, stdout: "FAILED test_a\nFAILED test_b\n" + "x".repeat(200), stderr: "" },
  ]);
  const runner = new VerificationRunner({ commandRunner, persistedOutputChars: 20 });
  const workspace = path.resolve("verification-workspace");
  const baseline = await runner.run(workspace, config, "baseline");
  const current = await runner.run(workspace, config, "finish");
  assert.ok(baseline);
  assert.ok(current);
  assert.match(current.stdout, /truncated/);
  assert.deepEqual(compareVerification(baseline, current).newFailures, ["FAILED test_b"]);
});

function attempt(
  phase: VerificationAttempt["phase"],
  passed: boolean,
  failureKeys: readonly string[],
): VerificationAttempt {
  return {
    phase,
    command: "test",
    timeoutMs: 1_000,
    startedAt: "2026-07-11T00:00:00.000Z",
    durationMs: 1,
    exitCode: passed ? 0 : 1,
    passed,
    timedOut: false,
    outputLimitExceeded: false,
    stdout: "",
    stderr: "",
    failureKeys,
    failureKeysReliable: true,
    fingerprint: failureKeys.join("|"),
  };
}

test("verification comparison distinguishes passed, pre-existing, and newly introduced failures", () => {
  assert.deepEqual(compareVerification(attempt("baseline", true, []), attempt("finish", true, [])), {
    status: "passed",
    allowed: true,
    newFailures: [],
  });
  assert.deepEqual(compareVerification(attempt("baseline", false, ["FAILED test_a"]), attempt("finish", false, ["FAILED test_a"])), {
    status: "pre_existing_failure",
    allowed: true,
    newFailures: [],
  });
  assert.deepEqual(compareVerification(attempt("baseline", false, ["FAILED test_a"]), attempt("finish", false, ["FAILED test_a", "FAILED test_b"])), {
    status: "regression",
    allowed: false,
    newFailures: ["FAILED test_b"],
  });
  assert.equal(compareVerification(attempt("baseline", true, []), attempt("finish", false, ["ERROR build"])).allowed, false);
});

test("timeouts and unstructured failures fail closed instead of becoming pre-existing", () => {
  const timeout = { ...attempt("baseline", false, ["<timeout>"]), timedOut: true, exitCode: null, failureKeysReliable: false };
  const finalTimeout = { ...timeout, phase: "finish" as const };
  assert.equal(compareVerification(timeout, finalTimeout).allowed, false);

  const generic = { ...attempt("baseline", false, ["1 failed"]), failureKeysReliable: false };
  const finalGeneric = { ...generic, phase: "finish" as const };
  assert.equal(compareVerification(generic, finalGeneric).allowed, false);
});
