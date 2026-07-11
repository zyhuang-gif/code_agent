import assert from "node:assert/strict";
import test from "node:test";
import { CompactingContextService } from "../src/services/context.js";
import type { ModelMessage } from "../src/services/model.js";

test("context service compacts old messages and preserves the system and recent tail", async () => {
  const messages: ModelMessage[] = [
    { role: "system", content: "system" },
    { role: "user", content: "a".repeat(80) },
    { role: "assistant", content: "b".repeat(80) },
    { role: "user", content: "recent" },
  ];
  const service = new CompactingContextService(undefined, {
    maxCharacters: 100,
    preserveRecentMessages: 1,
  });
  const result = await service.prepare(messages);
  assert.equal(result.compacted, true);
  assert.equal(result.removedMessages, 2);
  assert.equal(result.messages[0]?.role, "system");
  assert.match(result.messages[1]?.content ?? "", /conversation-summary/);
  assert.equal(result.messages.at(-1)?.content, "recent");
});
