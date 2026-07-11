import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ArtifactError, FileSystemArtifactStore } from "../src/governance/artifacts.js";

test("artifact store binds artifacts to the validated run layout", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-artifacts-"));
  try {
    const runDirectory = path.join(root, "run");
    const repository = path.join(runDirectory, "repository");
    const artifactsDirectory = path.join(runDirectory, "artifacts");
    await mkdir(repository, { recursive: true });
    const store = new FileSystemArtifactStore({ runDirectory, repository, artifactsDirectory });
    assert.equal(await store.writeFinalDiff("diff --git a/a b/a\n"), store.paths.diffPath);
    assert.equal(await readFile(store.paths.diffPath, "utf8"), "diff --git a/a b/a\n");
    assert.equal(await store.writeResult({ reason: "completed", steps: 2 }), store.paths.resultPath);
    assert.deepEqual(JSON.parse(await readFile(store.paths.resultPath, "utf8")), {
      reason: "completed",
      steps: 2,
    });
    assert.equal(path.dirname(store.paths.diffPath), artifactsDirectory);
    assert.equal(path.relative(repository, store.paths.diffPath).startsWith(".."), true);
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
