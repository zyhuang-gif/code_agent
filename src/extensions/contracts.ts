import type { ToolDefinition } from "../tools/contracts.js";

export const SKILL_SELECTION_AUDIT_SCHEMA_VERSION = 1 as const;

interface SkillSelectionAuditBase {
  readonly schemaVersion: typeof SKILL_SELECTION_AUDIT_SCHEMA_VERSION;
  readonly requestedSkill: string;
}

export type SkillSelectionAudit =
  | SkillSelectionAuditBase & {
      readonly outcome: "selected";
      readonly selectedSkill: string;
      readonly extensionName: string;
      readonly definitionSource: string;
    }
  | SkillSelectionAuditBase & {
      readonly outcome: "not_found";
    };

export interface SkillSelectionMetadata {
  readonly skillSelection: SkillSelectionAudit;
}

export function isStableSkillDefinitionSource(source: string): boolean {
  if (!source.trim() || source.includes("\\") || source.startsWith("/") || /^[A-Za-z]:/u.test(source)) {
    return false;
  }
  return source.split("/").every((segment) => segment.length > 0 && segment !== "." && segment !== "..");
}

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
