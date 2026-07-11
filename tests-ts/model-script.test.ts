import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  loadModelScript,
  ModelScriptError,
  type ModelScriptErrorCode,
} from "../src/host/model-script.js";

const MIB = 1024 * 1024;

function script(response: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schemaVersion: 1,
    responses: [{ content: null, toolCalls: [], ...response }],
  };
}

async function writeJson(root: string, name: string, value: unknown): Promise<string> {
  const source = path.join(root, name);
  await writeFile(source, JSON.stringify(value), "utf8");
  return source;
}

async function expectModelScriptError(
  promise: Promise<unknown>,
  code: ModelScriptErrorCode,
  source: string,
): Promise<ModelScriptError> {
  let caught: unknown;
  try {
    await promise;
  } catch (error) {
    caught = error;
  }
  assert.ok(caught instanceof ModelScriptError);
  assert.equal(caught.name, "ModelScriptError");
  assert.equal(caught.code, code);
  assert.equal(caught.source, source);
  assert.deepEqual(caught.toJSON(), {
    name: "ModelScriptError",
    code,
    source,
    message: caught.message,
  });
  return caught;
}

test("loadModelScript validates schema v1 and defaults omitted usage", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-model-script-"));
  try {
    const source = await writeJson(root, "valid.json", {
      schemaVersion: 1,
      responses: [
        {
          content: null,
          toolCalls: [{ id: "edit-1", name: "unregistered_tool", input: { nested: [1, true] } }],
        },
        {
          content: "done",
          toolCalls: [],
          usage: {
            promptTokens: 3,
            completionTokens: 4,
            cacheReadTokens: 5,
            cacheWriteTokens: 6,
          },
        },
      ],
    });

    const responses = await loadModelScript(source);
    assert.deepEqual(responses, [
      {
        content: null,
        toolCalls: [{ id: "edit-1", name: "unregistered_tool", input: { nested: [1, true] } }],
        usage: { promptTokens: 0, completionTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 },
      },
      {
        content: "done",
        toolCalls: [],
        usage: { promptTokens: 3, completionTokens: 4, cacheReadTokens: 5, cacheWriteTokens: 6 },
      },
    ]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("loadModelScript accepts response and tool-call limits", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-model-script-limits-"));
  try {
    const response = {
      content: null,
      toolCalls: Array.from({ length: 50 }, (_, index) => ({
        id: `call-${String(index)}`,
        name: "tool",
        input: {},
      })),
    };
    const source = await writeJson(root, "limits.json", {
      schemaVersion: 1,
      responses: Array.from({ length: 100 }, () => response),
    });

    const responses = await loadModelScript(source);
    assert.equal(responses.length, 100);
    assert.equal(responses[0]?.toolCalls.length, 50);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("loadModelScript rejects read, size, and JSON errors with their source", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-model-script-errors-"));
  try {
    const missing = path.join(root, "missing.json");
    await expectModelScriptError(loadModelScript(missing), "read_error", missing);

    await expectModelScriptError(loadModelScript(root), "read_error", root);

    const oversized = path.join(root, "oversized.json");
    await writeFile(oversized, Buffer.alloc(MIB + 1, 0x20));
    await expectModelScriptError(loadModelScript(oversized), "file_too_large", oversized);

    const malformed = path.join(root, "malformed.json");
    await writeFile(malformed, "{", "utf8");
    await expectModelScriptError(loadModelScript(malformed), "json_parse_error", malformed);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("loadModelScript accepts a UTF-8 BOM and CRLF", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-model-script-bom-"));
  try {
    const source = path.join(root, "bom.json");
    const content = `\uFEFF${JSON.stringify(script(), null, 2).replace(/\n/g, "\r\n")}\r\n`;
    await writeFile(source, content, "utf8");

    const responses = await loadModelScript(source);
    assert.equal(responses.length, 1);
    assert.deepEqual(responses[0]?.toolCalls, []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("loadModelScript rejects invalid root fields, version, and response counts", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-model-script-root-"));
  try {
    const cases: readonly [string, unknown, ModelScriptErrorCode][] = [
      ["root-array", [], "invalid_type"],
      ["unknown-root", { ...script(), typo: true }, "unknown_field"],
      ["version", { ...script(), schemaVersion: 2 }, "invalid_schema_version"],
      ["responses-type", { schemaVersion: 1, responses: {} }, "invalid_type"],
      ["responses-empty", { schemaVersion: 1, responses: [] }, "out_of_range"],
      ["responses-many", { schemaVersion: 1, responses: Array.from({ length: 101 }, () => null) }, "out_of_range"],
    ];

    for (const [name, value, code] of cases) {
      await t.test(name, async () => {
        const source = await writeJson(root, `${name}.json`, value);
        await expectModelScriptError(loadModelScript(source), code, source);
      });
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("loadModelScript strictly validates responses and tool calls", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-model-script-response-"));
  try {
    const validCall = { id: "call-1", name: "tool", input: {} };
    const cases: readonly [string, unknown, ModelScriptErrorCode][] = [
      ["response-object", { schemaVersion: 1, responses: [null] }, "invalid_type"],
      ["unknown-response", script({ typo: true }), "unknown_field"],
      ["content-missing", { schemaVersion: 1, responses: [{ toolCalls: [] }] }, "invalid_type"],
      ["content", script({ content: 1 }), "invalid_type"],
      ["calls-type", script({ toolCalls: {} }), "invalid_type"],
      ["calls-many", script({ toolCalls: Array.from({ length: 51 }, () => validCall) }), "out_of_range"],
      ["call-object", script({ toolCalls: [null] }), "invalid_type"],
      ["unknown-call", script({ toolCalls: [{ ...validCall, typo: true }] }), "unknown_field"],
      ["empty-id", script({ toolCalls: [{ ...validCall, id: "" }] }), "invalid_value"],
      ["empty-name", script({ toolCalls: [{ ...validCall, name: "" }] }), "invalid_value"],
      ["input-array", script({ toolCalls: [{ ...validCall, input: [] }] }), "invalid_type"],
      ["duplicate-id", script({ toolCalls: [validCall, { ...validCall, name: "other" }] }), "duplicate_tool_call_id"],
    ];

    for (const [name, value, code] of cases) {
      await t.test(name, async () => {
        const source = await writeJson(root, `${name}.json`, value);
        await expectModelScriptError(loadModelScript(source), code, source);
      });
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("loadModelScript requires complete non-negative safe-integer usage", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "code-agent-model-script-usage-"));
  try {
    const validUsage = {
      promptTokens: 0,
      completionTokens: 0,
      cacheReadTokens: 0,
      cacheWriteTokens: 0,
    };
    const cases: readonly [string, unknown, ModelScriptErrorCode][] = [
      ["usage-object", script({ usage: null }), "invalid_type"],
      ["usage-unknown", script({ usage: { ...validUsage, totalTokens: 0 } }), "unknown_field"],
      ["usage-missing", script({ usage: { promptTokens: 0 } }), "invalid_value"],
      ["usage-negative", script({ usage: { ...validUsage, completionTokens: -1 } }), "invalid_value"],
      ["usage-fraction", script({ usage: { ...validUsage, cacheReadTokens: 1.5 } }), "invalid_value"],
      ["usage-unsafe", script({ usage: { ...validUsage, cacheWriteTokens: Number.MAX_SAFE_INTEGER + 1 } }), "invalid_value"],
    ];

    for (const [name, value, code] of cases) {
      await t.test(name, async () => {
        const source = await writeJson(root, `${name}.json`, value);
        await expectModelScriptError(loadModelScript(source), code, source);
      });
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
