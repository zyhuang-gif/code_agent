import assert from "node:assert/strict";
import test from "node:test";
import { DefaultMcpService, InMemoryMcpToolProvider } from "../src/services/mcp.js";
import { OpenAICompatibleModelService } from "../src/services/model.js";
import type { ToolDefinition } from "../src/tools/contracts.js";
import { READ_ONLY_POLICY } from "../src/tools/contracts.js";

const noopTool: ToolDefinition = {
  name: "noop",
  description: "noop",
  inputSchema: { type: "object", properties: {}, additionalProperties: false },
  policy: READ_ONLY_POLICY,
  async execute() { return { status: "success", content: "ok" }; },
};

test("MCP service connects providers once and exposes normalized tools", async () => {
  const provider = new InMemoryMcpToolProvider("memory", [noopTool]);
  const service = new DefaultMcpService();
  service.register(provider);
  assert.deepEqual((await service.discoverTools()).map((tool) => tool.name), ["noop"]);
  await service.discoverTools();
  assert.equal(provider.connectCount, 1);
  await service.close();
  assert.equal(provider.closeCount, 1);
});

test("OpenAI-compatible model service translates tool calls and usage", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: Record<string, unknown> | undefined;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(JSON.stringify({
      choices: [{
        message: {
          content: null,
          tool_calls: [{ id: "call-1", function: { name: "noop", arguments: "{}" } }],
        },
      }],
      usage: {
        prompt_tokens: 12,
        completion_tokens: 4,
        prompt_tokens_details: { cached_tokens: 5 },
      },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const service = new OpenAICompatibleModelService({
      apiKey: "test",
      baseUrl: "https://example.invalid/v1/",
      model: "test-model",
    });
    const response = await service.complete({
      messages: [{ role: "user", content: "hello" }],
      tools: [{ name: "noop", description: "noop", inputSchema: noopTool.inputSchema }],
    });
    assert.equal(requestBody?.model, "test-model");
    assert.equal(response.toolCalls[0]?.name, "noop");
    assert.deepEqual(response.toolCalls[0]?.input, {});
    assert.equal(response.usage.promptTokens, 12);
    assert.equal(response.usage.cacheReadTokens, 5);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
