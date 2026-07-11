import type { ModelMessage } from "./model.js";

export interface ContextPreparation {
  readonly messages: readonly ModelMessage[];
  readonly compacted: boolean;
  readonly removedMessages: number;
  readonly summary?: string;
}

export interface ContextCompactor {
  compact(messages: readonly ModelMessage[]): Promise<string>;
}

export interface ContextService {
  prepare(messages: readonly ModelMessage[]): Promise<ContextPreparation>;
}

export interface CompactingContextOptions {
  readonly maxCharacters?: number;
  readonly preserveRecentMessages?: number;
}

function messageSize(message: ModelMessage): number {
  return (message.content?.length ?? 0) + JSON.stringify(message.toolCalls ?? []).length + 32;
}

export class DeterministicContextCompactor implements ContextCompactor {
  async compact(messages: readonly ModelMessage[]): Promise<string> {
    return messages.map((message) => {
      const content = (message.content ?? "").replace(/\s+/g, " ").trim();
      const preview = content.length > 240 ? content.slice(0, 237) + "..." : content;
      const calls = message.toolCalls?.length
        ? " tools=[" + message.toolCalls.map((call) => call.name).join(",") + "]"
        : "";
      return message.role + ": " + preview + calls;
    }).join("\n");
  }
}

export class CompactingContextService implements ContextService {
  readonly #maxCharacters: number;
  readonly #preserveRecentMessages: number;

  constructor(
    private readonly compactor: ContextCompactor = new DeterministicContextCompactor(),
    options: CompactingContextOptions = {},
  ) {
    this.#maxCharacters = options.maxCharacters ?? 80_000;
    this.#preserveRecentMessages = options.preserveRecentMessages ?? 8;
  }

  async prepare(messages: readonly ModelMessage[]): Promise<ContextPreparation> {
    const total = messages.reduce((sum, message) => sum + messageSize(message), 0);
    if (total <= this.#maxCharacters) return { messages, compacted: false, removedMessages: 0 };

    const leadingSystem = messages[0]?.role === "system" ? [messages[0]] : [];
    const remainder = leadingSystem.length ? messages.slice(1) : messages;
    const keepCount = Math.min(this.#preserveRecentMessages, remainder.length);
    const compactable = remainder.slice(0, remainder.length - keepCount);
    const recent = remainder.slice(remainder.length - keepCount);
    if (compactable.length === 0) return { messages, compacted: false, removedMessages: 0 };

    const summary = await this.compactor.compact(compactable);
    const summaryMessage: ModelMessage = {
      role: "user",
      content: "<conversation-summary>\n" + summary + "\n</conversation-summary>",
    };
    return {
      messages: [...leadingSystem, summaryMessage, ...recent],
      compacted: true,
      removedMessages: compactable.length,
      summary,
    };
  }
}
