import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ArtifactError, FileSystemArtifactStore } from "../src/governance/artifacts.js";

test("artifact store binds all four artifacts to the validated run layout", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-artifacts-"));
  try {
    const runDirectory = path.join(root, "run");
    const repository = path.join(runDirectory, "repository");
    const artifactsDirectory = path.join(runDirectory, "artifacts");
    await mkdir(repository, { recursive: true });
    const store = new FileSystemArtifactStore({ runDirectory, repository, artifactsDirectory });

    assert.deepEqual(
      {
        diff: path.basename(store.paths.diffPath),
        result: path.basename(store.paths.resultPath),
        trace: path.basename(store.paths.tracePath),
        verification: path.basename(store.paths.verificationPath),
      },
      {
        diff: "final.diff",
        result: "result.json",
        trace: "trace.jsonl",
        verification: "verification.json",
      },
    );
    assert.equal(new Set([
      store.paths.diffPath,
      store.paths.resultPath,
      store.paths.tracePath,
      store.paths.verificationPath,
    ]).size, 4);

    assert.equal(await store.writeFinalDiff("diff --git a/a b/a\n"), store.paths.diffPath);
    assert.equal(await readFile(store.paths.diffPath, "utf8"), "diff --git a/a b/a\n");
    assert.equal(await store.writeResult({ reason: "completed", steps: 2 }), store.paths.resultPath);
    assert.deepEqual(JSON.parse(await readFile(store.paths.resultPath, "utf8")), {
      reason: "completed",
      steps: 2,
    });
    assert.equal(
      await store.writeVerification({ schemaVersion: 1, status: "not_run" }),
      store.paths.verificationPath,
    );
    assert.equal(await readFile(store.paths.verificationPath, "utf8"), [
      "{",
      "  \"schemaVersion\": 1,",
      "  \"status\": \"not_run\"",
      "}",
      "",
    ].join("\n"));

    for (const artifactPath of [
      store.paths.diffPath,
      store.paths.resultPath,
      store.paths.tracePath,
      store.paths.verificationPath,
    ]) {
      assert.equal(path.dirname(artifactPath), artifactsDirectory);
      assert.equal(path.relative(repository, artifactPath).startsWith(".."), true);
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("artifact store rejects artifact directories inside the repository", () => {
  const runDirectory = path.resolve("run");
  const repository = path.join(runDirectory, "repository");
  assert.throws(
    () => new FileSystemArtifactStore({
      runDirectory,
      repository,
      artifactsDirectory: path.join(repository, "artifacts"),
    }),
    (error: unknown) => error instanceof ArtifactError && error.code === "artifact_path_invalid",
  );
});
