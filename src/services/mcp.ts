import type { ToolDefinition } from "../tools/contracts.js";

export interface McpToolProvider {
  readonly name: string;
  connect(): Promise<void>;
  listTools(): Promise<readonly ToolDefinition[]>;
  close(): Promise<void>;
}

export interface McpService {
  register(provider: McpToolProvider): void;
  discoverTools(): Promise<readonly ToolDefinition[]>;
  close(): Promise<void>;
}

export class DefaultMcpService implements McpService {
  readonly #providers = new Map<string, McpToolProvider>();
  readonly #connected = new Set<string>();

  register(provider: McpToolProvider): void {
    if (this.#providers.has(provider.name)) {
      throw new Error(`MCP provider already registered: ${provider.name}`);
    }
    this.#providers.set(provider.name, provider);
  }

  async discoverTools(): Promise<readonly ToolDefinition[]> {
    const tools: ToolDefinition[] = [];
    for (const provider of this.#providers.values()) {
      if (!this.#connected.has(provider.name)) {
        await provider.connect();
        this.#connected.add(provider.name);
      }
      tools.push(...(await provider.listTools()));
    }
    return tools;
  }

  async close(): Promise<void> {
    for (const name of this.#connected) {
      await this.#providers.get(name)?.close();
    }
    this.#connected.clear();
  }
}

export class InMemoryMcpToolProvider implements McpToolProvider {
  connectCount = 0;
  closeCount = 0;

  constructor(
    readonly name: string,
    private readonly tools: readonly ToolDefinition[],
  ) {}

  async connect(): Promise<void> {
    this.connectCount += 1;
  }

  async listTools(): Promise<readonly ToolDefinition[]> {
    return this.tools;
  }

  async close(): Promise<void> {
    this.closeCount += 1;
  }
}
