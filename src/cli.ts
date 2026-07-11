import { randomUUID } from "node:crypto";
import path from "node:path";
import process from "node:process";
import { createInterface } from "node:readline/promises";
import { pathToFileURL } from "node:url";
import { AgentRuntime } from "./engine/runtime.js";
import type { AgentEvent, RunResult } from "./engine/contracts.js";
import { loadExtensions } from "./extensions/filesystem-loader.js";
import { ExtensionRegistry } from "./extensions/registry.js";
import { GovernedToolExecutor } from "./governance/executor.js";
import { HookBus } from "./governance/hooks.js";
import type { ApprovalProvider, PermissionDecision, PermissionMode, PermissionRequest } from "./governance/permissions.js";
import { PermissionEngine } from "./governance/permissions.js";
import { finalizeManagedRun, prepareManagedRun } from "./host/managed-run.js";
import type { ManagedRunResult } from "./host/managed-run.js";
import { createDefaultProjectProfile, loadProjectProfile } from "./host/project-profile.js";
import type { ProjectProfile } from "./host/project-profile.js";
import { CompactingContextService } from "./services/context.js";
import { DefaultMcpService } from "./services/mcp.js";
import type { ModelService } from "./services/model.js";
import { EMPTY_USAGE, OpenAICompatibleModelService, ScriptedModelService } from "./services/model.js";
import { createBuiltInTools } from "./tools/builtins.js";
import type { ToolDefinition } from "./tools/contracts.js";
import { ToolRegistry } from "./tools/registry.js";

type WorkspaceMode =
  | {
      readonly kind: "managed";
      readonly sourceRepository: string;
      readonly runRoot: string;
    }
  | {
      readonly kind: "preisolated";
      readonly workspace: string;
      readonly assertion: "already-isolated";
    };

interface CliOptions {
  readonly task: string;
  readonly workspaceMode: WorkspaceMode;
  readonly extensions: string;
  readonly fake: boolean;
  readonly json: boolean;
  readonly permissionMode: PermissionMode;
  readonly maxSteps: number;
  readonly allowHostShell: boolean;
  readonly profilePath: string | null;
}

function parseArgs(argv: readonly string[]): CliOptions {
  let task = "";
  let sourceRepository: string | undefined;
  let runRoot: string | undefined;
  let workspace: string | undefined;
  let workspaceIsIsolated = false;
  let extensions = "extensions";
  let fake = false;
  let json = false;
  let permissionMode: PermissionMode = "default";
  let maxSteps = 40;
  let allowHostShell = false;
  let profilePath: string | null = null;

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
      case "--repo": sourceRepository = next(); break;
      case "--run-root": runRoot = next(); break;
      case "--workspace": workspace = next(); break;
      case "--workspace-is-isolated": workspaceIsIsolated = true; break;
      case "--extensions": extensions = next(); break;
      case "--fake": fake = true; break;
      case "--json": json = true; break;
      case "--permission-mode": permissionMode = next() as PermissionMode; break;
      case "--max-steps": maxSteps = Number.parseInt(next(), 10); break;
      case "--allow-host-shell": allowHostShell = true; break;
      case "--profile": profilePath = path.resolve(next()); break;
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
  if (sourceRepository && workspace) throw new Error("--repo and --workspace are mutually exclusive");
  if (sourceRepository) {
    if (!runRoot) throw new Error("--run-root is required with --repo");
    if (workspaceIsIsolated) throw new Error("--workspace-is-isolated cannot be used with --repo");
  } else if (workspace) {
    if (!workspaceIsIsolated) {
      throw new Error("--workspace requires --workspace-is-isolated because it bypasses managed copying");
    }
    if (runRoot) throw new Error("--run-root is only valid with --repo in this migration phase");
  } else {
    throw new Error("choose managed mode with --repo/--run-root or explicit --workspace/--workspace-is-isolated");
  }
  if (workspaceIsIsolated && !workspace) throw new Error("--workspace-is-isolated requires --workspace");

  const workspaceMode: WorkspaceMode = sourceRepository
    ? { kind: "managed", sourceRepository: path.resolve(sourceRepository), runRoot: path.resolve(runRoot!) }
    : { kind: "preisolated", workspace: path.resolve(workspace!), assertion: "already-isolated" };
  return {
    task,
    workspaceMode,
    extensions: path.resolve(extensions),
    fake,
    json,
    permissionMode,
    maxSteps,
    allowHostShell,
    profilePath,
  };
}

class ConsoleApprovalProvider implements ApprovalProvider {
  async requestApproval(request: PermissionRequest, decision: PermissionDecision): Promise<boolean> {
    if (!process.stdin.isTTY || !process.stderr.isTTY) return false;
    const readline = createInterface({ input: process.stdin, output: process.stderr });
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

export function selectBuiltInTools(
  allowHostShell: boolean,
  profile: ProjectProfile = createDefaultProjectProfile(),
): readonly ToolDefinition[] {
  return createBuiltInTools({
    ignore: profile.ignore,
    maxFileBytes: profile.maxFileBytes,
    commandTimeout: profile.commandTimeout,
  }).filter((tool) => allowHostShell || tool.name !== "bash");
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
    case "session_start": console.log("session=" + event.sessionId + " workspace=" + event.workspace); break;
    case "context_compacted": console.log("context compacted; removed=" + String(event.removedMessages)); break;
    case "model_start": console.log("model step " + String(event.step)); break;
    case "model_end": console.log("model returned tools=" + event.toolCalls.map((call) => call.name).join(",")); break;
    case "tool_start": console.log("tool start " + event.invocation.name); break;
    case "tool_end": console.log("tool end " + event.record.invocation.name + " status=" + event.record.result.status); break;
    case "session_end": console.log("result=" + event.result.reason + " summary=" + event.result.summary); break;
  }
}

function printManagedResult(result: ManagedRunResult, json: boolean): void {
  if (json) {
    process.stdout.write(JSON.stringify(result) + "\n");
    return;
  }
  console.log("source_repository=" + result.sourceRepository);
  console.log("workspace=" + result.workspace);
  console.log("run_directory=" + result.runDirectory);
  console.log("diff_path=" + result.diffPath);
  console.log("result_path=" + result.resultPath);
  console.log("reason=" + result.reason);
}

async function executeRuntime(
  workspace: string,
  sessionId: string,
  options: CliOptions,
  tools: readonly ToolDefinition[],
  hooks: HookBus,
): Promise<RunResult> {
  const executor = new GovernedToolExecutor(
    new ToolRegistry(tools),
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
    workspace,
    sessionId,
    maxSteps: options.maxSteps,
  });
  while (true) {
    const item = await stream.next();
    if (item.done) return item.value;
    printEvent(item.value, options.json);
  }
}

async function execute(options: CliOptions): Promise<RunResult> {
  const profile = options.profilePath
    ? await loadProjectProfile(options.profilePath)
    : createDefaultProjectProfile();
  const extensionRegistry = new ExtensionRegistry();
  for (const extension of await loadExtensions(options.extensions)) extensionRegistry.register(extension);
  const mcp = new DefaultMcpService();
  const builtIns = selectBuiltInTools(options.allowHostShell, profile);
  const tools = [
    ...builtIns,
    ...extensionRegistry.listTools(),
    ...(extensionRegistry.listSkills().length ? [extensionRegistry.createSkillTool()] : []),
    ...(await mcp.discoverTools()),
  ];
  const hooks = new HookBus();
  try {
    if (options.workspaceMode.kind === "preisolated") {
      return await executeRuntime(
        options.workspaceMode.workspace,
        randomUUID(),
        options,
        tools,
        hooks,
      );
    }

    const prepared = await prepareManagedRun({
      sessionId: randomUUID(),
      sourceRepository: options.workspaceMode.sourceRepository,
      runRoot: options.workspaceMode.runRoot,
    });
    const runtimeResult = await executeRuntime(
      prepared.session.repository,
      prepared.session.sessionId,
      options,
      tools,
      hooks,
    );
    const managedResult = await finalizeManagedRun(prepared, runtimeResult);
    printManagedResult(managedResult, options.json);
    return runtimeResult;
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
