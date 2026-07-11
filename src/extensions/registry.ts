import type { ToolDefinition } from "../tools/contracts.js";
import { READ_ONLY_POLICY } from "../tools/contracts.js";
import type { AgentExtension, SkillDefinition } from "./contracts.js";

interface InvokeSkillInput { readonly name: string }

export class ExtensionRegistry {
  readonly #extensions = new Map<string, AgentExtension>();
  readonly #skills = new Map<string, SkillDefinition>();

  register(extension: AgentExtension): void {
    if (this.#extensions.has(extension.name)) {
      throw new Error("extension already registered: " + extension.name);
    }
    for (const skill of extension.skills ?? []) {
      if (this.#skills.has(skill.name)) {
        throw new Error("skill already registered: " + skill.name);
      }
      this.#skills.set(skill.name, skill);
    }
    this.#extensions.set(extension.name, extension);
  }

  listSkills(): readonly SkillDefinition[] {
    return [...this.#skills.values()];
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
      description: "Load specialized workflow instructions when relevant. Available skills:\n" + descriptions,
      inputSchema: {
        type: "object",
        properties: { name: { type: "string" } },
        required: ["name"],
        additionalProperties: false,
      },
      policy: { ...READ_ONLY_POLICY, concurrency: "serial" },
      async execute(input) {
        const skill = skills.get(input.name);
        if (!skill) {
          return {
            status: "error",
            content: "unknown skill: " + input.name,
            error: "unknown skill: " + input.name,
          };
        }
        const allowed = skill.allowedTools?.length
          ? "\nAllowed tools: " + skill.allowedTools.join(", ")
          : "";
        return {
          status: "success",
          content: "<skill name=\"" + skill.name + "\">\n" + skill.instructions + allowed + "\n</skill>",
          data: skill,
        };
      },
    };
  }
}
