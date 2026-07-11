import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { finalizeManagedRun, prepareManagedRun } from "../src/host/managed-run.js";
import { EMPTY_USAGE } from "../src/services/model.js";

test("managed run prepares an isolated checkpoint and persists final artifacts", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-managed-run-"));
  try {
    const source = path.join(root, "source");
    const runRoot = path.join(root, "runs");
    await mkdir(source, { recursive: true });
    await writeFile(path.join(source, "file.txt"), "before\n", "utf8");
    const prepared = await prepareManagedRun({
      sessionId: "session-1",
      sourceRepository: source,
      runRoot,
    });
    await writeFile(path.join(prepared.session.repository, "file.txt"), "after\n", "utf8");
    const result = await finalizeManagedRun(prepared, {
      sessionId: "session-1",
      reason: "completed",
      summary: "done",
      steps: 1,
      usage: EMPTY_USAGE,
      messages: [],
    });
    assert.equal(result.type, "run_result");
    assert.equal(result.workspace, prepared.session.repository);
    assert.match(await readFile(result.diffPath, "utf8"), /after/);
    assert.equal(JSON.parse(await readFile(result.resultPath, "utf8")).reason, "completed");
    assert.equal(await readFile(path.join(source, "file.txt"), "utf8"), "before\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
