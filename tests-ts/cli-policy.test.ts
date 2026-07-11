import assert from "node:assert/strict";
import test from "node:test";
import { selectBuiltInTools } from "../src/cli.js";

test("managed CLI does not expose host shell unless explicitly enabled", () => {
  assert.equal(selectBuiltInTools(false).some((tool) => tool.name === "bash"), false);
  assert.equal(selectBuiltInTools(true).some((tool) => tool.name === "bash"), true);
});
