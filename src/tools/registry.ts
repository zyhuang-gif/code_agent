import type {
  JsonSchema,
  ModelToolDefinition,
  ToolContext,
  ToolDefinition,
  ToolResult,
} from "./contracts.js";

export class ToolInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ToolInputError";
  }
}

function matchesType(value: unknown, type: NonNullable<JsonSchema["type"]>): boolean {
  switch (type) {
    case "object":
      return typeof value === "object" && value !== null && !Array.isArray(value);
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
  }
}

export function validateInput(schema: JsonSchema, value: unknown, valuePath = "input"): void {
  if (schema.type && !matchesType(value, schema.type)) {
    throw new ToolInputError(`${valuePath} must be ${schema.type}`);
  }

  if (schema.enum && !schema.enum.some((item) => Object.is(item, value))) {
    throw new ToolInputError(`${valuePath} must be one of: ${schema.enum.join(", ")}`);
  }

  if (schema.type === "object" && typeof value === "object" && value !== null && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    for (const required of schema.required ?? []) {
      if (!(required in record)) {
        throw new ToolInputError(`${valuePath}.${required} is required`);
      }
    }
    if (schema.additionalProperties === false && schema.properties) {
      for (const key of Object.keys(record)) {
        if (!(key in schema.properties)) {
          throw new ToolInputError(`${valuePath}.${key} is not allowed`);
        }
      }
    }
    for (const [key, childSchema] of Object.entries(schema.properties ?? {})) {
      if (key in record) {
        validateInput(childSchema, record[key], `${valuePath}.${key}`);
      }
    }
  }

  if (schema.type === "array" && Array.isArray(value) && schema.items) {
    value.forEach((item, index) => validateInput(schema.items!, item, `${valuePath}[${index}]`));
  }
}

export class ToolRegistry {
  readonly #tools = new Map<string, ToolDefinition>();

  constructor(tools: readonly ToolDefinition[] = []) {
    for (const tool of tools) {
      this.register(tool);
    }
  }

  register(tool: ToolDefinition): void {
    if (this.#tools.has(tool.name)) {
      throw new Error(`tool already registered: ${tool.name}`);
    }
    this.#tools.set(tool.name, tool);
  }

  get(name: string): ToolDefinition {
    const tool = this.#tools.get(name);
    if (!tool) {
      throw new Error(`unknown tool: ${name}`);
    }
    return tool;
  }

  list(): readonly ToolDefinition[] {
    return [...this.#tools.values()];
  }

  toModelTools(): readonly ModelToolDefinition[] {
    return this.list().map((tool) => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.inputSchema,
    }));
  }

  async execute(name: string, input: unknown, context: ToolContext): Promise<ToolResult> {
    const tool = this.get(name);
    try {
      validateInput(tool.inputSchema, input);
      return await tool.execute(input, context);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { status: "error", content: message, error: message };
    }
  }
}
