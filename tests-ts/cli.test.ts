import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";

test("TypeScript CLI runs a complete fake session and emits JSON events", () => {
  const tsxCli = path.resolve("node_modules", "tsx", "dist", "cli.mjs");
  const result = spawnSync(process.execPath, [
    tsxCli,
    "src/cli.ts",
    "--fake",
    "--json",
    "--task",
    "CLI smoke test",
    "--workspace",
    ".",
    "--extensions",
    "extensions",
  ], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  const events = result.stdout.trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line) as { type: string; result?: { reason?: string } });
  assert.equal(events[0]?.type, "session_start");
  assert.equal(events.at(-1)?.type, "session_end");
  assert.equal(events.at(-1)?.result?.reason, "completed");
});
