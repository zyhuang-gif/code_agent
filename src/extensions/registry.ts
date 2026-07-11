import type { ToolDefinition } from "../tools/contracts.js";
import { READ_ONLY_POLICY } from "../tools/contracts.js";
import {
  isStableSkillDefinitionSource,
  SKILL_SELECTION_AUDIT_SCHEMA_VERSION,
  type AgentExtension,
  type SkillDefinition,
  type SkillSelectionAudit,
  type SkillSelectionMetadata,
} from "./contracts.js";

interface InvokeSkillInput { readonly name: string }
interface RegisteredSkill {
  readonly definition: SkillDefinition;
  readonly extensionName: string;
  readonly definitionSource: string;
}

function syntheticDefinitionSource(extensionName: string, skillName: string): string {
  return `extension:${encodeURIComponent(extensionName)}/${encodeURIComponent(skillName)}`;
}

export class ExtensionRegistry {
  readonly #extensions = new Map<string, AgentExtension>();
  readonly #skills = new Map<string, RegisteredSkill>();

  register(extension: AgentExtension): void {
    if (this.#extensions.has(extension.name)) {
      throw new Error("extension already registered: " + extension.name);
    }
    const registrations = (extension.skills ?? []).map((skill): readonly [string, RegisteredSkill] => {
      const definitionSource = skill.source ?? syntheticDefinitionSource(extension.name, skill.name);
      if (!isStableSkillDefinitionSource(definitionSource)) {
        throw new Error("skill definition source must be a stable relative path: " + definitionSource);
      }
      return [skill.name, { definition: skill, extensionName: extension.name, definitionSource }];
    });
    const names = new Set<string>();
    for (const [name] of registrations) {
      if (names.has(name) || this.#skills.has(name)) {
        throw new Error("skill already registered: " + name);
      }
      names.add(name);
    }
    for (const [name, registration] of registrations) this.#skills.set(name, registration);
    this.#extensions.set(extension.name, extension);
  }

  listSkills(): readonly SkillDefinition[] {
    return [...this.#skills.values()].map(({ definition }) => definition);
  }

  listTools(): readonly ToolDefinition[] {
    return [...this.#extensions.values()].flatMap((extension) => [...(extension.tools ?? [])]);
  }

  createSkillTool(): ToolDefinition<InvokeSkillInput, SkillDefinition> {
    const skills = this.#skills;
    const descriptions = this.listSkills()
      .map((skill) => skill.name + ": " + skill.description)
      .join("\n");
    return {
      name: "invoke_skill",
      description: [
        "Select and load specialized workflow instructions before solving when a listed skill directly matches",
        "the repository or problem. Do not skip a direct match because the task appears simple.",
        "Available skills:\n" + descriptions,
      ].join(" "),
      inputSchema: {
        type: "object",
        properties: { name: { type: "string" } },
        required: ["name"],
        additionalProperties: false,
      },
      policy: { ...READ_ONLY_POLICY, concurrency: "serial" },
      async execute(input) {
        const registered = skills.get(input.name);
        if (!registered) {
          const skillSelection: SkillSelectionAudit = {
            schemaVersion: SKILL_SELECTION_AUDIT_SCHEMA_VERSION,
            outcome: "not_found",
            requestedSkill: input.name,
          };
          return {
            status: "error",
            content: "unknown skill: " + input.name,
            error: "unknown skill: " + input.name,
            metadata: { skillSelection } satisfies SkillSelectionMetadata,
          };
        }
        const { definition: skill, extensionName, definitionSource } = registered;
        const allowed = skill.allowedTools?.length
          ? "\nAllowed tools: " + skill.allowedTools.join(", ")
          : "";
        const skillSelection: SkillSelectionAudit = {
          schemaVersion: SKILL_SELECTION_AUDIT_SCHEMA_VERSION,
          outcome: "selected",
          requestedSkill: input.name,
          selectedSkill: skill.name,
          extensionName,
          definitionSource,
        };
        return {
          status: "success",
          content: "<skill name=\"" + skill.name + "\">\n" + skill.instructions + allowed + "\n</skill>",
          data: skill,
          metadata: { skillSelection } satisfies SkillSelectionMetadata,
        };
      },
    };
  }
}
