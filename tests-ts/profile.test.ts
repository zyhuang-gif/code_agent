import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  createDefaultProjectProfile,
  loadProjectProfile,
  parseProjectProfile,
  ProfileError,
  ProjectProfile,
  type ProfileErrorCode,
} from "../src/host/project-profile.js";

function assertProfileError(
  error: unknown,
  code: ProfileErrorCode,
  field?: string,
): asserts error is ProfileError {
  assert.ok(error instanceof ProfileError);
  assert.equal(error.name, "ProfileError");
  assert.equal(error.code, code);
  if (field !== undefined) assert.equal(error.field, field);
  assert.equal(error.toJSON().code, code);
}

test("default ProjectProfile matches Python defaults", () => {
  const profile = createDefaultProjectProfile();

  assert.deepEqual(profile.ignore, []);
  assert.deepEqual(profile.syntaxCheck, {});
  assert.equal(profile.setupCmd, null);
  assert.equal(profile.setupNeedsNetwork, true);
  assert.equal(profile.setupTimeout, 300);
  assert.equal(profile.testCmd, null);
  assert.equal(profile.testTimeout, 300);
  assert.equal(profile.commandTimeout, 300);
  assert.equal(profile.passWhen, "exit_zero");
  assert.equal(profile.parseTestOutput, null);
  assert.equal(profile.language, null);
  assert.equal(profile.maxFileBytes, 200_000);

  const second = createDefaultProjectProfile();
  assert.notEqual(profile.ignore, second.ignore);
  assert.notEqual(profile.syntaxCheck, second.syntaxCheck);
});

test("repository Python, Node, CMake, and empty YAML profiles load with snake_case compatibility", async () => {
  const python = await loadProjectProfile(path.resolve("profiles", "python.yaml"));
  const node = await loadProjectProfile(path.resolve("profiles", "node.yaml"));
  const cmake = await loadProjectProfile(path.resolve("profiles", "cmake.yaml"));
  const empty = await loadProjectProfile(path.resolve("profiles", "empty.yaml"));

  assert.deepEqual(python.ignore, [".git", "__pycache__"]);
  assert.equal(python.syntaxCheck[".py"], "python -m py_compile {file}");
  assert.equal(python.language, "python");
  assert.equal(python.testCmd, "pytest -q");
  assert.equal(python.testTimeout, 300);

  assert.deepEqual(node.ignore, ["node_modules"]);
  assert.equal(node.language, "node");
  assert.equal(node.commandTimeout, 300);

  assert.equal(cmake.language, "cmake");
  assert.match(cmake.testCmd ?? "", /cmake -S \. -B build/);
  assert.match(cmake.testCmd ?? "", /ctest --test-dir build/);
  assert.equal(cmake.testTimeout, 120);
  assert.equal(cmake.commandTimeout, 120);

  assert.deepEqual(empty.ignore, []);
  assert.equal(empty.setupNeedsNetwork, true);
  assert.equal(empty.passWhen, "exit_zero");
  assert.equal(empty.maxFileBytes, 200_000);
});

test("all YAML fields map to camelCase properties without executing commands", () => {
  const profile = parseProjectProfile({
    ignore: ["vendor"],
    syntax_check: { ".ts": "tsc --noEmit {file}" },
    setup_cmd: "npm ci",
    setup_needs_network: false,
    setup_timeout: 45,
    test_cmd: "npm test",
    test_timeout: 60,
    command_timeout: 15,
    pass_when: "custom-policy",
    parse_test_output: "tap",
    language: "typescript",
    max_file_bytes: 4_096,
  }, "inline.yaml");

  assert.deepEqual(profile.ignore, ["vendor"]);
  assert.deepEqual(profile.syntaxCheck, { ".ts": "tsc --noEmit {file}" });
  assert.equal(profile.setupCmd, "npm ci");
  assert.equal(profile.setupNeedsNetwork, false);
  assert.equal(profile.setupTimeout, 45);
  assert.equal(profile.testCmd, "npm test");
  assert.equal(profile.testTimeout, 60);
  assert.equal(profile.commandTimeout, 15);
  assert.equal(profile.passWhen, "custom-policy");
  assert.equal(profile.parseTestOutput, "tap");
  assert.equal(profile.language, "typescript");
  assert.equal(profile.maxFileBytes, 4_096);
});

test("empty YAML value uses defaults and unknown fields produce structured ProfileError", () => {
  assert.deepEqual(parseProjectProfile(null), createDefaultProjectProfile());

  assert.throws(
    () => parseProjectProfile({ ignore: [], command_timout: 30 }, "typo.yaml"),
    (error: unknown) => {
      assertProfileError(error, "unknown_field", "command_timout");
      assert.equal(error.source, "typo.yaml");
      assert.deepEqual(error.actual, ["command_timout"]);
      assert.match(error.message, /known snake_case ProjectProfile field/);
      return true;
    },
  );
});

test("ProjectProfile validation reports explicit type, range, and value errors", async (t) => {
  const cases: readonly {
    readonly name: string;
    readonly value: unknown;
    readonly code: ProfileErrorCode;
    readonly field?: string;
  }[] = [
    { name: "root", value: [], code: "invalid_root" },
    { name: "ignore container", value: { ignore: "vendor" }, code: "invalid_type", field: "ignore" },
    { name: "ignore item", value: { ignore: ["vendor", 2] }, code: "invalid_type", field: "ignore[1]" },
    {
      name: "syntax command",
      value: { syntax_check: { ".ts": false } },
      code: "invalid_type",
      field: "syntax_check..ts",
    },
    {
      name: "network flag",
      value: { setup_needs_network: "false" },
      code: "invalid_type",
      field: "setup_needs_network",
    },
    { name: "fractional timeout", value: { test_timeout: 1.5 }, code: "invalid_type", field: "test_timeout" },
    { name: "zero timeout", value: { command_timeout: 0 }, code: "out_of_range", field: "command_timeout" },
    { name: "negative bytes", value: { max_file_bytes: -1 }, code: "out_of_range", field: "max_file_bytes" },
    { name: "empty pass rule", value: { pass_when: "" }, code: "invalid_value", field: "pass_when" },
  ];

  for (const item of cases) {
    await t.test(item.name, () => {
      assert.throws(
        () => parseProjectProfile(item.value, `${item.name}.yaml`),
        (error: unknown) => {
          assertProfileError(error, item.code, item.field);
          return true;
        },
      );
    });
  }
});

test("loadProjectProfile wraps read and YAML parser failures", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-profile-errors-"));
  try {
    await assert.rejects(
      loadProjectProfile(path.join(root, "missing.yaml")),
      (error: unknown) => {
        assertProfileError(error, "read_error");
        return true;
      },
    );

    const malformed = path.join(root, "malformed.yaml");
    await writeFile(malformed, "ignore: [unterminated\n", "utf8");
    await assert.rejects(
      loadProjectProfile(malformed),
      (error: unknown) => {
        assertProfileError(error, "yaml_parse_error");
        return true;
      },
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("shouldIgnore preserves Python hard ignores and supports names and globs", () => {
  const profile = new ProjectProfile({ ignore: ["node_modules", "*.log", "build/*", "cmake-build-*"] });

  assert.equal(profile.shouldIgnore(".git/objects/ab/cdef"), true);
  assert.equal(profile.shouldIgnore("src/__pycache__/module.pyc"), true);
  assert.equal(profile.shouldIgnore("src/module.pyc"), true);
  assert.equal(profile.shouldIgnore("src/pkg.egg-info/PKG-INFO"), true);
  assert.equal(profile.shouldIgnore("pkg/node_modules/index.js"), true);
  assert.equal(profile.shouldIgnore("logs/debug.log"), true);
  assert.equal(profile.shouldIgnore("build/output/bin/app"), true);
  assert.equal(profile.shouldIgnore("cmake-build-debug/CMakeCache.txt"), true);
  assert.equal(profile.shouldIgnore("src/app.ts"), false);
});
