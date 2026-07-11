import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, readFile, rm, unlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  CheckpointError,
  type CommandRunner,
  type CommandRunOptions,
  type CommandResult,
  GitCheckpoint,
  SpawnCommandRunner,
} from "../src/governance/checkpoint.js";

interface CheckpointFixture {
  readonly root: string;
  readonly sourceRepository: string;
  readonly runRoot: string;
  readonly runDirectory: string;
  readonly repository: string;
  readonly markerPath: string;
}

type MarkerRecord = Record<string, unknown>;

function markerFor(fixture: CheckpointFixture): MarkerRecord {
  return {
    schemaVersion: 1,
    sessionId: path.basename(fixture.runDirectory),
    sourceRepository: fixture.sourceRepository,
    repository: fixture.repository,
    runDirectory: fixture.runDirectory,
    runRoot: fixture.runRoot,
  };
}

async function writeMarker(fixture: CheckpointFixture, marker: MarkerRecord = markerFor(fixture)): Promise<void> {
  await writeFile(fixture.markerPath, `${JSON.stringify(marker)}\n`, "utf8");
}

async function createFixture(options: { readonly empty?: boolean; readonly spaces?: boolean } = {}): Promise<CheckpointFixture> {
  const prefix = options.spaces ? "code agent checkpoint " : "code-agent-checkpoint-";
  const root = await mkdtemp(path.join(os.tmpdir(), prefix));
  const sourceRepository = path.join(root, options.spaces ? "source repository" : "source");
  const runRoot = path.join(root, options.spaces ? "run root" : "runs");
  const runDirectory = path.join(runRoot, options.spaces ? "session one" : "session-1");
  const repository = path.join(runDirectory, "repository");
  const markerPath = path.join(runDirectory, "run.json");

  await mkdir(sourceRepository, { recursive: true });
  await mkdir(repository, { recursive: true });
  if (!options.empty) {
    await writeFile(path.join(sourceRepository, "tracked.txt"), "baseline\n", "utf8");
    await writeFile(path.join(repository, "tracked.txt"), "baseline\n", "utf8");
  }

  const fixture = { root, sourceRepository, runRoot, runDirectory, repository, markerPath };
  await writeMarker(fixture);
  return fixture;
}

function checkpoint(
  fixture: CheckpointFixture,
  extras: Partial<ConstructorParameters<typeof GitCheckpoint>[0]> = {},
): GitCheckpoint {
  return new GitCheckpoint({
    repository: fixture.repository,
    runDirectory: fixture.runDirectory,
    runRoot: fixture.runRoot,
    ...extras,
  });
}

async function expectCheckpointError(
  promise: Promise<unknown>,
  code: CheckpointError["code"],
): Promise<CheckpointError> {
  let received: CheckpointError | undefined;
  await assert.rejects(promise, (error: unknown) => {
    assert.ok(error instanceof CheckpointError);
    assert.equal(error.code, code);
    received = error;
    return true;
  });
  assert.ok(received);
  return received;
}

async function pathExists(candidate: string): Promise<boolean> {
  try {
    await access(candidate);
    return true;
  } catch {
    return false;
  }
}

async function runGit(repository: string, args: readonly string[]): Promise<CommandResult> {
  const result = await new SpawnCommandRunner().run("git", args, {
    cwd: repository,
    timeoutMs: 15_000,
  });
  assert.equal(
    result.exitCode,
    0,
    `git ${args.join(" ")} failed:\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );
  return result;
}

test("GitCheckpoint records modified, new, deleted, and binary files in a binary-safe diff", async () => {
  const fixture = await createFixture();
  try {
    const deleted = path.join(fixture.repository, "deleted.txt");
    const binary = path.join(fixture.repository, "data.bin");
    await writeFile(deleted, "remove me\n", "utf8");
    await writeFile(binary, Buffer.from([0, 1, 2, 3, 4, 5, 6, 7]));

    const subject = checkpoint(fixture);
    await subject.initialize();

    await writeFile(path.join(fixture.repository, "tracked.txt"), "changed\n", "utf8");
    await writeFile(path.join(fixture.repository, "added.txt"), "new file\n", "utf8");
    await unlink(deleted);
    await writeFile(binary, Buffer.from([0, 255, 3, 254, 5, 253, 7, 252]));

    const diff = await subject.diff();
    assert.match(diff, /diff --git a\/tracked\.txt b\/tracked\.txt/);
    assert.match(diff, /diff --git a\/added\.txt b\/added\.txt/);
    assert.match(diff, /new file mode/);
    assert.match(diff, /diff --git a\/deleted\.txt b\/deleted\.txt/);
    assert.match(diff, /deleted file mode/);
    assert.match(diff, /diff --git a\/data\.bin b\/data\.bin/);
    assert.match(diff, /GIT binary patch|Binary files/);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("GitCheckpoint creates an empty baseline commit and reports an empty diff", async () => {
  const fixture = await createFixture({ empty: true });
  try {
    const subject = checkpoint(fixture);
    await subject.initialize();
    assert.equal(await subject.diff(), "");
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("diff and rollback stay anchored to the immutable baseline after the Agent commits", async () => {
  const fixture = await createFixture();
  try {
    const subject = checkpoint(fixture);
    await subject.initialize();
    const baselineOid = (await runGit(fixture.repository, ["rev-parse", "HEAD"])).stdout.trim();

    await writeFile(path.join(fixture.repository, "tracked.txt"), "committed agent change\n", "utf8");
    await writeFile(path.join(fixture.repository, "committed.txt"), "committed addition\n", "utf8");
    await runGit(fixture.repository, ["add", "-A"]);
    await runGit(fixture.repository, ["commit", "--no-verify", "--no-gpg-sign", "-m", "agent commit"]);
    const agentOid = (await runGit(fixture.repository, ["rev-parse", "HEAD"])).stdout.trim();
    assert.notEqual(agentOid, baselineOid);

    const diff = await subject.diff();
    assert.match(diff, /committed agent change/);
    assert.match(diff, /diff --git a\/committed\.txt b\/committed\.txt/);

    await subject.rollback();
    assert.equal((await runGit(fixture.repository, ["rev-parse", "HEAD"])).stdout.trim(), baselineOid);
    assert.equal(await readFile(path.join(fixture.repository, "tracked.txt"), "utf8"), "baseline\n");
    assert.equal(await pathExists(path.join(fixture.repository, "committed.txt")), false);
    assert.equal(await subject.diff(), "");
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("ignored baseline files are tracked, ignored additions enter diff, and rollback restores the baseline", async () => {
  const fixture = await createFixture();
  try {
    await writeFile(
      path.join(fixture.repository, ".gitignore"),
      "ignored-existing.txt\nignored-new.txt\nignored-output/\n",
      "utf8",
    );
    await writeFile(path.join(fixture.repository, "ignored-existing.txt"), "ignored baseline\n", "utf8");

    const subject = checkpoint(fixture);
    await subject.initialize();
    assert.match((await runGit(fixture.repository, ["ls-files", "ignored-existing.txt"])).stdout, /ignored-existing\.txt/);

    await writeFile(path.join(fixture.repository, "ignored-existing.txt"), "changed ignored baseline\n", "utf8");
    await writeFile(path.join(fixture.repository, "ignored-new.txt"), "new ignored file\n", "utf8");
    await mkdir(path.join(fixture.repository, "ignored-output"), { recursive: true });
    await writeFile(path.join(fixture.repository, "ignored-output", "cache.bin"), "ignored generated\n", "utf8");

    const diff = await subject.diff();
    assert.match(diff, /diff --git a\/ignored-existing\.txt b\/ignored-existing\.txt/);
    assert.match(diff, /diff --git a\/ignored-new\.txt b\/ignored-new\.txt/);
    assert.match(diff, /diff --git a\/ignored-output\/cache\.bin b\/ignored-output\/cache\.bin/);

    await subject.rollback();
    assert.equal(
      await readFile(path.join(fixture.repository, "ignored-existing.txt"), "utf8"),
      "ignored baseline\n",
    );
    assert.equal(await pathExists(path.join(fixture.repository, "ignored-new.txt")), false);
    assert.equal(await pathExists(path.join(fixture.repository, "ignored-output", "cache.bin")), false);
    assert.equal(await subject.diff(), "");
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("rollback restores tracked files, restores deletions, and removes additions", async () => {
  const fixture = await createFixture();
  try {
    const deleted = path.join(fixture.repository, "deleted.txt");
    await writeFile(deleted, "restore me\n", "utf8");

    const subject = checkpoint(fixture);
    await subject.initialize();

    await writeFile(path.join(fixture.repository, "tracked.txt"), "agent change\n", "utf8");
    await unlink(deleted);
    await writeFile(path.join(fixture.repository, "added.txt"), "agent addition\n", "utf8");

    await subject.rollback();

    assert.equal(await readFile(path.join(fixture.repository, "tracked.txt"), "utf8"), "baseline\n");
    assert.equal(await readFile(deleted, "utf8"), "restore me\n");
    assert.equal(await pathExists(path.join(fixture.repository, "added.txt")), false);
    assert.equal(await subject.diff(), "");
    assert.equal(await readFile(path.join(fixture.sourceRepository, "tracked.txt"), "utf8"), "baseline\n");
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("run marker requires schemaVersion, sessionId, and exact workspace paths", async (t) => {
  const cases: ReadonlyArray<{
    readonly name: string;
    readonly mutate: (marker: MarkerRecord, fixture: CheckpointFixture) => void;
  }> = [
    { name: "schemaVersion", mutate: (marker) => { marker.schemaVersion = 2; } },
    { name: "empty sessionId", mutate: (marker) => { marker.sessionId = "   "; } },
    { name: "mismatched sessionId", mutate: (marker) => { marker.sessionId = "another-session"; } },
    { name: "missing sourceRepository", mutate: (marker) => { delete marker.sourceRepository; } },
    { name: "missing repository", mutate: (marker) => { delete marker.repository; } },
    { name: "missing runDirectory", mutate: (marker) => { delete marker.runDirectory; } },
    { name: "missing runRoot", mutate: (marker) => { delete marker.runRoot; } },
    {
      name: "mismatched repository",
      mutate: (marker, fixture) => { marker.repository = fixture.sourceRepository; },
    },
    {
      name: "mismatched runDirectory",
      mutate: (marker, fixture) => { marker.runDirectory = fixture.runRoot; },
    },
    {
      name: "mismatched runRoot",
      mutate: (marker, fixture) => { marker.runRoot = fixture.root; },
    },
  ];

  for (const markerCase of cases) {
    await t.test(markerCase.name, async () => {
      const fixture = await createFixture();
      try {
        const marker = markerFor(fixture);
        markerCase.mutate(marker, fixture);
        await writeMarker(fixture, marker);
        await expectCheckpointError(checkpoint(fixture).initialize(), "marker_invalid");
      } finally {
        await rm(fixture.root, { recursive: true, force: true });
      }
    });
  }
});

test("rollback refuses to run without the trusted run marker", async () => {
  const fixture = await createFixture();
  try {
    const subject = checkpoint(fixture);
    await subject.initialize();
    const added = path.join(fixture.repository, "added.txt");
    await writeFile(added, "do not clean without marker\n", "utf8");
    await unlink(fixture.markerPath);

    await expectCheckpointError(subject.rollback(), "marker_missing");
    assert.equal(await pathExists(added), true);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("checkpoint rejects run directories outside the configured run root", async () => {
  const fixture = await createFixture();
  try {
    const outsideRunDirectory = path.join(fixture.root, "outside-run");
    const outsideRepository = path.join(outsideRunDirectory, "repository");
    const outsideMarker = path.join(outsideRunDirectory, "run.json");
    await mkdir(outsideRepository, { recursive: true });
    await writeFile(
      outsideMarker,
      `${JSON.stringify({
        schemaVersion: 1,
        sessionId: path.basename(outsideRunDirectory),
        sourceRepository: fixture.sourceRepository,
        repository: outsideRepository,
        runDirectory: outsideRunDirectory,
        runRoot: fixture.runRoot,
      })}\n`,
      "utf8",
    );

    const subject = new GitCheckpoint({
      repository: outsideRepository,
      runDirectory: outsideRunDirectory,
      runRoot: fixture.runRoot,
    });
    await expectCheckpointError(subject.initialize(), "path_escape");
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("checkpoint works when every workspace path contains spaces", async () => {
  const fixture = await createFixture({ spaces: true });
  try {
    const subject = checkpoint(fixture);
    await subject.initialize();
    await writeFile(path.join(fixture.repository, "file with spaces.txt"), "works\n", "utf8");

    const diff = await subject.diff();
    assert.match(diff, /file with spaces\.txt/);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("Git commands use hardened argument arrays, immutable baseline OID, timeout, and controlled config environment", async () => {
  const fixture = await createFixture();
  try {
    const baselineOid = "a".repeat(40);
    const calls: Array<{
      readonly command: string;
      readonly args: readonly string[];
      readonly options: CommandRunOptions;
    }> = [];
    const runner: CommandRunner = {
      async run(command: string, args: readonly string[], options: CommandRunOptions): Promise<CommandResult> {
        calls.push({ command, args, options });
        if (args[0] === "rev-parse") return { exitCode: 0, stdout: `${baselineOid}\n`, stderr: "" };
        return { exitCode: 0, stdout: "", stderr: "" };
      },
    };
    const subject = checkpoint(fixture, { commandRunner: runner });

    await subject.initialize();
    await subject.diff();

    assert.deepEqual(calls[0]?.args, ["init", "--template="]);
    assert.ok(calls.some((call) => JSON.stringify(call.args) === JSON.stringify(["add", "-A", "-f"])));
    assert.ok(calls.some((call) => call.args.includes("--no-verify")));
    assert.ok(calls.some((call) => call.args.includes("--no-textconv")));
    assert.ok(calls.some((call) => call.args.at(-1) === baselineOid));
    for (const call of calls) {
      assert.equal(call.command, "git");
      assert.equal(call.options.cwd, fixture.repository);
      assert.equal(call.options.timeoutMs, 120_000);
      assert.equal(call.options.env?.GIT_CONFIG_NOSYSTEM, "1");
      assert.equal(call.options.env?.GIT_CONFIG_COUNT, "0");
      assert.equal(call.options.env?.GIT_CONFIG_GLOBAL, process.platform === "win32" ? "NUL" : "/dev/null");
    }
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("command failures remain structured", async () => {
  const fixture = await createFixture();
  try {
    const runner: CommandRunner = {
      async run(): Promise<CommandResult> {
        return { exitCode: 9, stdout: "", stderr: "simulated failure" };
      },
    };
    const subject = checkpoint(fixture, { commandRunner: runner });

    const error = await expectCheckpointError(subject.initialize(), "checkpoint_init_failed");
    assert.equal(error.command, "git");
    assert.deepEqual(error.args, ["init", "--template="]);
    assert.equal(error.exitCode, 9);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("missing Git executable is reported distinctly", async () => {
  const fixture = await createFixture();
  try {
    const runner: CommandRunner = {
      async run(): Promise<CommandResult> {
        const error = Object.assign(new Error("git is unavailable"), { code: "ENOENT" });
        throw error;
      },
    };
    const subject = checkpoint(fixture, { commandRunner: runner });

    const error = await expectCheckpointError(subject.initialize(), "git_not_available");
    assert.equal(error.command, "git");
    assert.deepEqual(error.args, ["init", "--template="]);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("SpawnCommandRunner terminates commands that exceed their timeout", async () => {
  const runner = new SpawnCommandRunner();
  const startedAt = Date.now();

  await assert.rejects(
    runner.run(process.execPath, ["-e", "setTimeout(() => {}, 10_000)"], {
      cwd: process.cwd(),
      timeoutMs: 100,
    }),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /timed out after 100ms/);
      return true;
    },
  );
  assert.ok(Date.now() - startedAt < 5_000);
});