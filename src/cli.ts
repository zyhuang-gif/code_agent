import path from "node:path";
import { pathToFileURL } from "node:url";
import process from "node:process";
import { createInterface } from "node:readline/promises";
import { AgentRuntime } from "./engine/runtime.js";
import type { AgentEvent, RunResult } from "./engine/contracts.js";
import { loadExtensions } from "./extensions/filesystem-loader.js";
import { ExtensionRegistry } from "./extensions/registry.js";
import { GovernedToolExecutor } from "./governance/executor.js";
import { HookBus } from "./governance/hooks.js";
import type { ApprovalProvider, PermissionDecision, PermissionMode, PermissionRequest } from "./governance/permissions.js";
import { PermissionEngine } from "./governance/permissions.js";
import { CompactingContextService } from "./services/context.js";
import { DefaultMcpService } from "./services/mcp.js";
import type { ModelService } from "./services/model.js";
import { EMPTY_USAGE, OpenAICompatibleModelService, ScriptedModelService } from "./services/model.js";
import { createBuiltInTools } from "./tools/builtins.js";
import { ToolRegistry } from "./tools/registry.js";

interface CliOptions {
  readonly task: string;
  readonly workspace: string;
  readonly extensions: string;
  readonly fake: boolean;
  readonly json: boolean;
  readonly permissionMode: PermissionMode;
  readonly maxSteps: number;
}

function parseArgs(argv: readonly string[]): CliOptions {
  let task = "";
  let workspace = ".";
  let extensions = "extensions";
  let fake = false;
  let json = false;
  let permissionMode: PermissionMode = "default";
  let maxSteps = 40;

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = (): string => {
      const value = argv[index + 1];
      if (!value) throw new Error("missing value for " + arg);
      index += 1;
      return value;
    };
    switch (arg) {
      case "--task": task = next(); break;
      case "--workspace": workspace = next(); break;
      case "--extensions": extensions = next(); break;
      case "--fake": fake = true; break;
      case "--json": json = true; break;
      case "--permission-mode": permissionMode = next() as PermissionMode; break;
      case "--max-steps": maxSteps = Number.parseInt(next(), 10); break;
      default:
        if (arg?.startsWith("-")) throw new Error("unknown argument: " + arg);
        task = task ? task + " " + arg : arg ?? "";
    }
  }

  if (!task) throw new Error("task is required; use --task <text>");
  if (!Number.isInteger(maxSteps) || maxSteps < 1) throw new Error("--max-steps must be a positive integer");
  if (!["default", "plan", "accept_edits", "bypass"].includes(permissionMode)) {
    throw new Error("invalid permission mode: " + permissionMode);
  }

  return {
    task,
    workspace: path.resolve(workspace),
    extensions: path.resolve(extensions),
    fake,
    json,
    permissionMode,
    maxSteps,
  };
}

class ConsoleApprovalProvider implements ApprovalProvider {
  async requestApproval(request: PermissionRequest, decision: PermissionDecision): Promise<boolean> {
    if (!process.stdin.isTTY || !process.stdout.isTTY) return false;
    const readline = createInterface({ input: process.stdin, output: process.stdout });
    try {
      const answer = await readline.question(
        "Allow tool " + request.invocation.name + "? " + decision.reason + " [y/N] ",
      );
      return /^(?:y|yes)$/i.test(answer.trim());
    } finally {
      readline.close();
    }
  }
}

function createModel(fake: boolean): ModelService {
  if (fake) {
    return new ScriptedModelService([
      {
        content: null,
        toolCalls: [{ id: "fake-finish", name: "finish", input: { summary: "fake TypeScript runtime completed" } }],
        usage: EMPTY_USAGE,
      },
    ]);
  }

  const apiKey = process.env.CODE_AGENT_API_KEY ?? process.env.DEEPSEEK_API_KEY;
  if (!apiKey) throw new Error("CODE_AGENT_API_KEY or DEEPSEEK_API_KEY is required");
  return new OpenAICompatibleModelService({
    apiKey,
    baseUrl: process.env.CODE_AGENT_BASE_URL ?? "https://api.deepseek.com",
    model: process.env.CODE_AGENT_MODEL ?? "deepseek-v4-flash",
    ...(process.env.CODE_AGENT_REASONING_EFFORT
      ? { reasoningEffort: process.env.CODE_AGENT_REASONING_EFFORT }
      : {}),
  });
}

function printEvent(event: AgentEvent, json: boolean): void {
  if (json) {
    process.stdout.write(JSON.stringify(event) + "\n");
    return;
  }
  switch (event.type) {
    case "session_start":
      console.log("session=" + event.sessionId + " workspace=" + event.workspace);
      break;
    case "context_compacted":
      console.log("context compacted; removed=" + String(event.removedMessages));
      break;
    case "model_start":
      console.log("model step " + String(event.step));
      break;
    case "model_end":
      console.log("model returned tools=" + event.toolCalls.map((call) => call.name).join(","));
      break;
    case "tool_start":
      console.log("tool start " + event.invocation.name);
      break;
    case "tool_end":
      console.log("tool end " + event.record.invocation.name + " status=" + event.record.result.status);
      break;
    case "session_end":
      console.log("result=" + event.result.reason + " summary=" + event.result.summary);
      break;
  }
}

async function execute(options: CliOptions): Promise<RunResult> {
  const extensionRegistry = new ExtensionRegistry();
  for (const extension of await loadExtensions(options.extensions)) {
    extensionRegistry.register(extension);
  }

  const mcp = new DefaultMcpService();
  const registry = new ToolRegistry([
    ...createBuiltInTools(),
    ...extensionRegistry.listTools(),
    ...(extensionRegistry.listSkills().length ? [extensionRegistry.createSkillTool()] : []),
    ...(await mcp.discoverTools()),
  ]);
  const hooks = new HookBus();
  const executor = new GovernedToolExecutor(
    registry,
    new PermissionEngine(options.permissionMode),
    new ConsoleApprovalProvider(),
    hooks,
  );
  const runtime = new AgentRuntime(
    createModel(options.fake),
    new CompactingContextService(),
    executor,
    hooks,
  );

  const stream = runtime.run({
    task: options.task,
    workspace: options.workspace,
    maxSteps: options.maxSteps,
  });
  try {
    while (true) {
      const item = await stream.next();
      if (item.done) return item.value;
      printEvent(item.value, options.json);
    }
  } finally {
    await mcp.close();
  }
}

export async function main(argv: readonly string[] = process.argv.slice(2)): Promise<number> {
  try {
    const result = await execute(parseArgs(argv));
    return result.reason === "completed" ? 0 : 1;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
