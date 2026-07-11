import type { ToolDefinition } from "../tools/contracts.js";

export interface SkillDefinition {
  readonly name: string;
  readonly description: string;
  readonly instructions: string;
  readonly allowedTools?: readonly string[];
  readonly source?: string;
}

export interface AgentExtension {
  readonly name: string;
  readonly skills?: readonly SkillDefinition[];
  readonly tools?: readonly ToolDefinition[];
}

export interface ExtensionManifest {
  readonly name: string;
  readonly skills?: readonly string[];
}
