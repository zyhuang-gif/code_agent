import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { selectBuiltInTools } from "../src/cli.js";
import { ProjectProfile } from "../src/host/project-profile.js";

const tsxCli = path.resolve("node_modules", "tsx", "dist", "cli.mjs");

interface RunResultEvent {
  readonly type: "run_result";
  readonly sessionId: string;
  readonly sourceRepository: string;
  readonly workspace: string;
  readonly runDirectory: string;
  readonly artifactsDirectory: string;
  readonly diffPath: string;
  readonly resultPath: string;
  readonly tracePath: string;
  readonly verificationPath: string;
  readonly reason: string;
}

interface TraceEnvelope {
  readonly type: string;
  readonly sessionId: string;
  readonly payload: unknown;
}

interface VerificationArtifact {
  readonly decision: string;
  readonly security: { readonly osSandbox: boolean; readonly sensitiveEnvironmentFiltered: boolean };
  readonly baseline: { readonly passed: boolean } | null;
  readonly finishAttempts: ReadonlyArray<{ readonly passed: boolean }>;
}

test("TypeScript CLI creates an isolated workspace and emits artifacts", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-cli-isolated-"));
  try {
    const source = path.join(root, "源 repo");
    const runRoot = path.join(root, "runs");
    await mkdir(source, { recursive: true });
    await writeFile(path.join(source, "hello.txt"), "original\n", "utf8");

    const result = spawnSync(process.execPath, [
      tsxCli,
      "src/cli.ts",
      "--fake",
      "--json",
      "--task",
      "CLI isolated smoke test",
      "--repo",
      source,
      "--run-root",
      runRoot,
      "--extensions",
      "extensions",
    ], {
      cwd: process.cwd(),
      encoding: "utf8",
    });

    assert.equal(result.status, 0, result.stderr);
    const events = result.stdout.trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line) as { type: string });
    assert.equal(events[0]?.type, "session_start");
    const runResult = events.at(-1) as RunResultEvent | undefined;
    assert.equal(runResult?.type, "run_result");
    assert.equal(runResult?.reason, "completed");
    assert.equal(path.relative(runRoot, runResult?.workspace ?? "").startsWith(".."), false);
    assert.equal(await readFile(path.join(source, "hello.txt"), "utf8"), "original\n");
    assert.equal(await readFile(runResult?.diffPath ?? "", "utf8"), "");
    const persisted = JSON.parse(await readFile(runResult?.resultPath ?? "", "utf8")) as RunResultEvent;
    assert.equal(persisted.workspace, runResult?.workspace);
    assert.equal(persisted.tracePath, runResult?.tracePath);
    assert.equal(persisted.verificationPath, runResult?.verificationPath);
    const verification = JSON.parse(await readFile(runResult?.verificationPath ?? "", "utf8")) as VerificationArtifact;
    assert.equal(verification.decision, "not_configured");
    assert.equal(verification.security.osSandbox, false);
    assert.equal(verification.security.sensitiveEnvironmentFiltered, true);

    const trace = (await readFile(runResult?.tracePath ?? "", "utf8"))
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line) as TraceEnvelope);
    assert.deepEqual(trace.slice(0, 4).map((event) => event.type), [
      "workspace_create_start",
      "workspace_create_end",
      "checkpoint_start",
      "checkpoint_ready",
    ]);
    assert.equal(trace.some((event) => event.type === "model_start"), true);
    assert.equal(trace.some((event) => event.type === "permission_request"), true);
    assert.equal(trace.filter((event) => event.type === "run_result").length, 1);
    assert.equal(trace.at(-1)?.type, "run_result");
    assert.equal(trace.every((event) => event.sessionId === runResult?.sessionId), true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("managed CLI runs baseline and finish verification and persists the gate artifact", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-cli-verification-"));
  try {
    const source = path.join(root, "source");
    const runRoot = path.join(root, "runs");
    const profile = path.join(root, "profile.yaml");
    await mkdir(source, { recursive: true });
    await writeFile(path.join(source, "hello.txt"), "original\n", "utf8");
    await writeFile(profile, [
      "test_cmd: node -e \"process.exit(0)\"",
      "test_timeout: 10",
      "pass_when: exit_zero",
      "",
    ].join("\n"), "utf8");

    const result = spawnSync(process.execPath, [
      tsxCli,
      "src/cli.ts",
      "--fake",
      "--json",
      "--task",
      "CLI verification smoke test",
      "--repo",
      source,
      "--run-root",
      runRoot,
      "--profile",
      profile,
      "--extensions",
      "extensions",
    ], { cwd: process.cwd(), encoding: "utf8" });

    assert.equal(result.status, 0, result.stderr);
    const output = result.stdout.trim().split(/\r?\n/).map((line) => JSON.parse(line) as { readonly type: string });
    const runResult = output.at(-1) as RunResultEvent;
    const verification = JSON.parse(await readFile(runResult.verificationPath, "utf8")) as VerificationArtifact;
    assert.equal(verification.decision, "passed");
    assert.equal(verification.baseline?.passed, true);
    assert.equal(verification.finishAttempts.length, 1);
    assert.equal(verification.finishAttempts[0]?.passed, true);
    const trace = (await readFile(runResult.tracePath, "utf8"))
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line) as TraceEnvelope);
    assert.equal(trace.filter((event) => event.type === "verification_start").length, 2);
    assert.equal(trace.filter((event) => event.type === "finish_gate_decision").length, 1);
    assert.equal(trace.at(-1)?.type, "run_result");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("CLI rejects an existing workspace unless it is explicitly declared isolated", () => {
  const result = spawnSync(process.execPath, [
    tsxCli,
    "src/cli.ts",
    "--fake",
    "--task",
    "unsafe workspace",
    "--workspace",
    ".",
  ], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /workspace-is-isolated/);
});

test("CLI accepts --profile with a repository YAML profile", () => {
  const result = spawnSync(process.execPath, [
    tsxCli,
    "src/cli.ts",
    "--fake",
    "--json",
    "--task",
    "CLI profile smoke test",
    "--workspace",
    ".",
    "--workspace-is-isolated",
    "--profile",
    path.resolve("profiles", "node.yaml"),
    "--extensions",
    "extensions",
  ], {
    cwd: process.cwd(),
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr);
  const events = result.stdout.trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line) as {
    readonly type: string;
    readonly result?: { readonly reason?: string };
  });
  assert.equal(events[0]?.type, "session_start");
  assert.equal(events.at(-1)?.type, "session_end");
  assert.equal(events.at(-1)?.result?.reason, "completed");
});
test("CLI maps ProjectProfile values into built-in tool configuration", () => {
  const tools = selectBuiltInTools(true, new ProjectProfile({
    ignore: ["generated"],
    maxFileBytes: 123,
    commandTimeout: 9,
  }));
  const bash = tools.find((tool) => tool.name === "bash");
  assert.equal(bash?.inputSchema.properties?.timeoutMs?.default, 9_000);
});
