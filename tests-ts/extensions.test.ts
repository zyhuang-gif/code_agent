import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { loadExtensions } from "../src/extensions/filesystem-loader.js";
import { ExtensionRegistry } from "../src/extensions/registry.js";

test("CMake is loaded as a skill extension without changing the engine", async () => {
  const loaded = await loadExtensions(path.resolve("extensions"));
  assert.deepEqual(loaded.map((extension) => extension.name), ["cmake"]);
  const registry = new ExtensionRegistry();
  for (const extension of loaded) registry.register(extension);
  assert.equal(registry.listSkills()[0]?.name, "cmake-build-fix");
  const tool = registry.createSkillTool();
  assert.match(tool.description, /cmake-build-fix/);
  const result = await tool.execute(
    { name: "cmake-build-fix" },
    { workspace: process.cwd(), sessionId: "skill-test", metadata: {} },
  );
  assert.equal(result.status, "success");
  assert.match(result.content, /target_link_libraries/);
});
