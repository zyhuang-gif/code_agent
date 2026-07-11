import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  SKILL_SELECTION_AUDIT_SCHEMA_VERSION,
  type SkillSelectionMetadata,
} from "../src/extensions/contracts.js";
import { loadExtensions, parseSkillMarkdown } from "../src/extensions/filesystem-loader.js";
import { ExtensionRegistry } from "../src/extensions/registry.js";

test("loadExtensions records a stable POSIX-relative skill source", async () => {
  const loaded = await loadExtensions(path.resolve("extensions"));
  assert.deepEqual(loaded.map((extension) => extension.name), ["cmake"]);
  const skill = loaded[0]?.skills?.[0];
  assert.equal(skill?.name, "cmake-build-fix");
  assert.equal(skill.source, "cmake/skills/build-fix/SKILL.md");
  assert.equal(path.isAbsolute(skill.source ?? ""), false);
  assert.equal(skill.source?.includes("\\"), false);
});

test("parseSkillMarkdown accepts only stable relative definition sources", () => {
  const skill = parseSkillMarkdown(
    "---\nname: custom\ndescription: Custom workflow\n---\nUse the workflow.",
    "custom/SKILL.md",
  );
  assert.equal(skill.source, "custom/SKILL.md");
  for (const source of ["C:\\extensions\\custom\\SKILL.md", "../custom/SKILL.md"]) {
    assert.throws(() => parseSkillMarkdown(
      "---\nname: custom\ndescription: Custom workflow\n---\nUse the workflow.",
      source,
    ), /stable relative path/);
  }
});

test("loadExtensions rejects linked skills that resolve outside the extension", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-extension-link-"));
  try {
    const extensionsRoot = path.join(root, "extensions");
    const extension = path.join(extensionsRoot, "linked");
    const external = path.join(root, "external");
    await mkdir(extension, { recursive: true });
    await mkdir(external);
    await writeFile(path.join(extension, "plugin.json"), JSON.stringify({
      name: "linked",
      skills: ["skills/SKILL.md"],
    }), "utf8");
    await writeFile(
      path.join(external, "SKILL.md"),
      "---\nname: linked\ndescription: Linked\n---\nOutside.",
      "utf8",
    );
    await symlink(external, path.join(extension, "skills"), "junction");
    await assert.rejects(loadExtensions(extensionsRoot), /escapes extension through a link/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("loadExtensions ignores a missing root but surfaces invalid roots", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-extension-root-"));
  try {
    assert.deepEqual(await loadExtensions(path.join(root, "missing")), []);
    const file = path.join(root, "extensions.json");
    await writeFile(file, "{}", "utf8");
    await assert.rejects(loadExtensions(file), /failed to read extensions root/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("invoke_skill preserves policy and content while auditing a selected skill", async () => {
  assert.equal(SKILL_SELECTION_AUDIT_SCHEMA_VERSION, 1);
  const loaded = await loadExtensions(path.resolve("extensions"));
  const registry = new ExtensionRegistry();
  for (const extension of loaded) registry.register(extension);
  assert.equal(registry.listSkills()[0]?.name, "cmake-build-fix");
  const tool = registry.createSkillTool();
  assert.match(tool.description, /cmake-build-fix/);
  assert.match(tool.description, /Do not skip a direct match/);
  assert.deepEqual(tool.policy, {
    access: "read_only",
    impact: "non_destructive",
    concurrency: "serial",
    idempotent: true,
    openWorld: false,
  });
  const result = await tool.execute(
    { name: "cmake-build-fix" },
    { workspace: process.cwd(), sessionId: "skill-test", metadata: {} },
  );
  assert.equal(result.status, "success");
  assert.match(result.content, /target_link_libraries/);
  assert.match(result.content, /Allowed tools: list_dir, read_file/);
  assert.equal(result.data, registry.listSkills()[0]);
  const expectedMetadata: SkillSelectionMetadata = {
    skillSelection: {
      schemaVersion: 1,
      outcome: "selected",
      requestedSkill: "cmake-build-fix",
      selectedSkill: "cmake-build-fix",
      extensionName: "cmake",
      definitionSource: "cmake/skills/build-fix/SKILL.md",
    },
  };
  assert.deepEqual(result.metadata, expectedMetadata);
});

test("invoke_skill audits an unknown skill without inventing provenance", async () => {
  const registry = new ExtensionRegistry();
  const tool = registry.createSkillTool();
  const result = await tool.execute(
    { name: "missing-skill" },
    { workspace: process.cwd(), sessionId: "skill-test", metadata: {} },
  );
  assert.equal(result.status, "error");
  assert.equal(result.content, "unknown skill: missing-skill");
  assert.equal(result.error, "unknown skill: missing-skill");
  const expectedMetadata: SkillSelectionMetadata = {
    skillSelection: {
      schemaVersion: 1,
      outcome: "not_found",
      requestedSkill: "missing-skill",
    },
  };
  assert.deepEqual(result.metadata, expectedMetadata);
});

test("registry synthesizes stable provenance for programmatic skills", async () => {
  const registry = new ExtensionRegistry();
  registry.register({
    name: "programmatic extension",
    skills: [{ name: "programmatic skill", description: "test", instructions: "test" }],
  });
  const result = await registry.createSkillTool().execute(
    { name: "programmatic skill" },
    { workspace: process.cwd(), sessionId: "skill-test", metadata: {} },
  );
  const metadata = result.metadata as unknown as SkillSelectionMetadata;
  assert.equal(
    metadata.skillSelection.outcome === "selected" ? metadata.skillSelection.definitionSource : "",
    "extension:programmatic%20extension/programmatic%20skill",
  );
});
