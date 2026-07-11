import type { Dirent } from "node:fs";
import { cp, mkdir, mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import type { ArtifactStore } from "../governance/artifacts.js";
import type { HookBus } from "../governance/hooks.js";
import {
  compareVerification,
  VerificationError,
  VerificationRunner,
  verificationCommandHash,
} from "../governance/verification.js";
import type {
  VerificationAttempt,
  VerificationComparison,
  VerificationConfig,
  VerificationExecutor,
} from "../governance/verification.js";
import type { ProjectProfile } from "./project-profile.js";
import { HOST_RUN_EVENT_SCHEMA_VERSION } from "./run-events.js";
import type { RunEvent, RunEventSink } from "./run-events.js";

export const VERIFICATION_REPORT_SCHEMA_VERSION = 1 as const;

export type VerificationReportDecision =
  | "pending"
  | "not_configured"
  | "passed"
  | "pre_existing_failure"
  | "blocked"
  | "error";

export interface VerificationReport {
  readonly schemaVersion: typeof VERIFICATION_REPORT_SCHEMA_VERSION;
  readonly sessionId: string;
  readonly command: string | null;
  readonly timeoutMs: number;
  readonly passWhen: string;
  readonly security: {
    readonly shell: "fixed_argv";
    readonly lexicalCommandPolicy: true;
    readonly sensitiveEnvironmentFiltered: true;
    readonly osSandbox: false;
    readonly workspaceIsolation: "copy";
  };
  readonly baseline: VerificationAttempt | null;
  readonly finishAttempts: readonly VerificationAttempt[];
  readonly decision: VerificationReportDecision;
  readonly blockedAttempts: number;
  readonly newFailures: readonly string[];
  readonly error?: { readonly code: string; readonly message: string };
}

export interface VerificationGateOptions {
  readonly sessionId: string;
  readonly workspace: string;
  readonly profile: ProjectProfile;
  readonly artifacts: ArtifactStore;
  readonly hooks: HookBus;
  readonly runEventSink?: RunEventSink;
  readonly runner?: VerificationExecutor;
  readonly scratchRoot?: string;
  readonly workspaceFactory?: VerificationWorkspaceFactory;
}

export interface VerificationWorkspace {
  readonly workspace: string;
  cleanup(): Promise<void>;
}

export interface VerificationWorkspaceFactory {
  create(sourceWorkspace: string, phase: "baseline" | "finish", attempt: number): Promise<VerificationWorkspace>;
}

function isSameOrInside(parent: string, candidate: string): boolean {
  const relative = path.relative(parent, candidate);
  return relative === "" || (relative !== ".." && !relative.startsWith(".." + path.sep) && !path.isAbsolute(relative));
}

async function rejectLinks(directory: string): Promise<void> {
  let entries: Dirent[];
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    throw new VerificationError("verification_workspace_copy_failed", "failed to read verification source workspace", error);
  }
  for (const entry of entries) {
    if (entry.isSymbolicLink()) {
      throw new VerificationError(
        "verification_workspace_unsafe",
        `verification workspace contains a symbolic link or junction: ${entry.name}`,
      );
    }
    if (entry.isDirectory()) await rejectLinks(path.join(directory, entry.name));
  }
}

export class FileSystemVerificationWorkspaceFactory implements VerificationWorkspaceFactory {
  readonly #scratchRoot: string;

  constructor(scratchRoot: string) {
    this.#scratchRoot = path.resolve(scratchRoot);
  }

  async create(
    sourceWorkspace: string,
    phase: "baseline" | "finish",
    attempt: number,
  ): Promise<VerificationWorkspace> {
    const source = path.resolve(sourceWorkspace);
    if (isSameOrInside(source, this.#scratchRoot) || isSameOrInside(this.#scratchRoot, source)) {
      throw new VerificationError(
        "verification_workspace_unsafe",
        "verification scratch root and source workspace must be disjoint",
      );
    }
    await rejectLinks(source);
    await mkdir(this.#scratchRoot, { recursive: true });
    const attemptDirectory = await mkdtemp(path.join(this.#scratchRoot, `${phase}-${String(attempt)}-`));
    const workspace = path.join(attemptDirectory, "repository");
    try {
      await cp(source, workspace, { recursive: true, errorOnExist: true, force: false, preserveTimestamps: true });
    } catch (error) {
      await rm(attemptDirectory, { recursive: true, force: true }).catch(() => undefined);
      throw new VerificationError("verification_workspace_copy_failed", "failed to create verification workspace", error);
    }
    return {
      workspace,
      async cleanup() {
        await rm(attemptDirectory, { recursive: true, force: true });
      },
    };
  }
}

function recordEvent(sink: RunEventSink | undefined, event: RunEvent): Promise<void> {
  return sink?.record(event) ?? Promise.resolve();
}

function gateReason(comparison: VerificationComparison): string {
  const details = comparison.newFailures.slice(0, 8).join(" | ");
  const reason = details
    ? `Finish blocked because verification introduced new failures: ${details}`
    : "Finish blocked because verification regressed from the baseline";
  return reason.length <= 4_000 ? reason : reason.slice(0, 4_000) + "...<truncated>";
}

export class VerificationGate {
  readonly #sessionId: string;
  readonly #workspace: string;
  readonly #artifacts: ArtifactStore;
  readonly #hooks: HookBus;
  readonly #runEventSink: RunEventSink | undefined;
  readonly #runner: VerificationExecutor;
  readonly #config: VerificationConfig;
  readonly #workspaceFactory: VerificationWorkspaceFactory;
  #baseline: VerificationAttempt | null = null;
  #finishAttempts: VerificationAttempt[] = [];
  #decision: VerificationReportDecision = "pending";
  #blockedAttempts = 0;
  #newFailures: readonly string[] = [];
  #error: { readonly code: string; readonly message: string } | undefined;

  constructor(options: VerificationGateOptions) {
    this.#sessionId = options.sessionId;
    this.#workspace = options.workspace;
    this.#artifacts = options.artifacts;
    this.#hooks = options.hooks;
    this.#runEventSink = options.runEventSink;
    this.#runner = options.runner ?? new VerificationRunner();
    if (!options.workspaceFactory && !options.scratchRoot) {
      throw new TypeError("verification gate requires scratchRoot or workspaceFactory");
    }
    this.#workspaceFactory = options.workspaceFactory
      ?? new FileSystemVerificationWorkspaceFactory(options.scratchRoot!);
    this.#config = {
      command: options.profile.testCmd,
      timeoutSeconds: options.profile.testTimeout,
      passWhen: options.profile.passWhen,
    };
  }

  get report(): VerificationReport {
    return {
      schemaVersion: VERIFICATION_REPORT_SCHEMA_VERSION,
      sessionId: this.#sessionId,
      command: this.#config.command,
      timeoutMs: this.#config.timeoutSeconds * 1_000,
      passWhen: this.#config.passWhen,
      security: {
        shell: "fixed_argv",
        lexicalCommandPolicy: true,
        sensitiveEnvironmentFiltered: true,
        osSandbox: false,
        workspaceIsolation: "copy",
      },
      baseline: this.#baseline,
      finishAttempts: Object.freeze([...this.#finishAttempts]),
      decision: this.#decision,
      blockedAttempts: this.#blockedAttempts,
      newFailures: this.#newFailures,
      ...(this.#error ? { error: this.#error } : {}),
    };
  }

  async initialize(): Promise<void> {
    if (!this.#config.command?.trim()) {
      this.#decision = "not_configured";
      await this.#persist();
      return;
    }
    try {
      this.#baseline = await this.#runAttempt("baseline", 0);
      if (!this.#baseline) throw new VerificationError("verification_command_invalid", "missing baseline command");
      this.#decision = "pending";
      await this.#persist();
    } catch (error) {
      const code = error instanceof VerificationError ? error.code : "verification_initialize_failed";
      this.#error = { code, message: error instanceof Error ? error.message : String(error) };
      this.#decision = "error";
      await this.#persist();
      throw error;
    }
  }

  register(): void {
    if (!this.#baseline) return;
    this.#hooks.on("pre_tool_use", async (event) => {
      const payload = event.payload as { readonly invocation?: { readonly name?: string } };
      if (payload.invocation?.name !== "finish") return;
      let current: VerificationAttempt | null;
      try {
        current = await this.#runAttempt("finish", this.#finishAttempts.length + 1);
      } catch (error) {
        const code = error instanceof VerificationError ? error.code : "verification_finish_failed";
        this.#error = { code, message: error instanceof Error ? error.message : String(error) };
        this.#blockedAttempts += 1;
        this.#decision = "error";
        this.#newFailures = [];
        await this.#persist();
        await this.#recordDecision("block", "error", []);
        return { action: "block", reason: `Finish blocked because verification failed to run: ${code}` };
      }
      if (!current) return;
      this.#finishAttempts.push(current);
      const comparison = compareVerification(this.#baseline!, current);
      this.#newFailures = comparison.newFailures;
      if (comparison.allowed) {
        this.#decision = comparison.status === "passed" ? "passed" : "pre_existing_failure";
        await this.#persist();
        await this.#recordDecision("allow", comparison.status, comparison.newFailures);
        return;
      }
      this.#blockedAttempts += 1;
      this.#decision = "blocked";
      await this.#persist();
      await this.#recordDecision("block", comparison.status, comparison.newFailures);
      return { action: "block", reason: gateReason(comparison) };
    });
  }

  async #runAttempt(phase: "baseline" | "finish", attempt: number): Promise<VerificationAttempt | null> {
    const startedAt = Date.now();
    await recordEvent(this.#runEventSink, {
      schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
      sessionId: this.#sessionId,
      type: "verification_start",
      payload: { phase, commandHash: verificationCommandHash(this.#config.command ?? ""), attempt },
    });
    let verificationWorkspace: VerificationWorkspace | undefined;
    let result: VerificationAttempt | null = null;
    let failure: unknown;
    try {
      verificationWorkspace = await this.#workspaceFactory.create(this.#workspace, phase, attempt);
      result = await this.#runner.run(verificationWorkspace.workspace, this.#config, phase);
      if (!result) {
        failure = new VerificationError("verification_command_invalid", "verification runner returned no attempt");
      }
    } catch (error) {
      failure = error;
    }
    if (verificationWorkspace) {
      try {
        await verificationWorkspace.cleanup();
      } catch (error) {
        failure ??= new VerificationError(
          "verification_workspace_copy_failed",
          "failed to clean verification workspace",
          error,
        );
      }
    }
    if (failure) {
      const code = failure instanceof VerificationError ? failure.code : "verification_attempt_failed";
      await recordEvent(this.#runEventSink, {
        schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
        sessionId: this.#sessionId,
        type: "verification_end",
        payload: {
          phase,
          attempt,
          status: "error",
          passed: false,
          exitCode: null,
          timedOut: false,
          durationMs: Math.max(0, Date.now() - startedAt),
          errorCode: code,
        },
      });
      throw failure;
    }
    await recordEvent(this.#runEventSink, {
      schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
      sessionId: this.#sessionId,
      type: "verification_end",
      payload: {
        phase,
        attempt,
        status: result!.passed ? "passed" : "failed",
        passed: result!.passed,
        exitCode: result!.exitCode,
        timedOut: result!.timedOut,
        durationMs: result!.durationMs,
      },
    });
    return result;
  }

  async #recordDecision(
    decision: "allow" | "block",
    status: VerificationComparison["status"] | "error",
    newFailures: readonly string[],
  ): Promise<void> {
    await recordEvent(this.#runEventSink, {
      schemaVersion: HOST_RUN_EVENT_SCHEMA_VERSION,
      sessionId: this.#sessionId,
      type: "finish_gate_decision",
      payload: {
        decision,
        status,
        blockedAttempts: this.#blockedAttempts,
        newFailures,
      },
    });
  }

  async #persist(): Promise<void> {
    await this.#artifacts.writeVerification(this.report);
  }
}
