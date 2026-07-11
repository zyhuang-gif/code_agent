import { createHash } from "node:crypto";
import path from "node:path";
import { assessBashCommand } from "./bash-safety.js";
import { SpawnCommandRunner } from "./checkpoint.js";
import type { CommandRunner } from "./checkpoint.js";

export type VerificationPhase = "baseline" | "finish";

export interface VerificationConfig {
  readonly command: string | null;
  readonly timeoutSeconds: number;
  readonly passWhen: string;
}

export interface VerificationAttempt {
  readonly phase: VerificationPhase;
  readonly command: string;
  readonly timeoutMs: number;
  readonly startedAt: string;
  readonly durationMs: number;
  readonly exitCode: number | null;
  readonly passed: boolean;
  readonly timedOut: boolean;
  readonly outputLimitExceeded: boolean;
  readonly stdout: string;
  readonly stderr: string;
  readonly failureKeys: readonly string[];
  readonly failureKeysReliable: boolean;
  readonly fingerprint: string;
}

export type VerificationComparisonStatus = "passed" | "pre_existing_failure" | "regression";

export interface VerificationComparison {
  readonly status: VerificationComparisonStatus;
  readonly allowed: boolean;
  readonly newFailures: readonly string[];
}

export type VerificationErrorCode =
  | "verification_command_invalid"
  | "verification_command_destructive"
  | "verification_command_not_found"
  | "verification_network_denied"
  | "verification_pass_rule_unsupported"
  | "verification_spawn_failed"
  | "verification_workspace_copy_failed"
  | "verification_workspace_unsafe";

export class VerificationError extends Error {
  constructor(
    readonly code: VerificationErrorCode,
    message: string,
    readonly originalCause?: unknown,
  ) {
    super(message, originalCause === undefined ? undefined : { cause: originalCause });
    this.name = "VerificationError";
  }
}

export interface VerificationRunnerOptions {
  readonly commandRunner?: CommandRunner;
  readonly clock?: () => Date;
  readonly maxOutputBytes?: number;
  readonly persistedOutputChars?: number;
}

export interface VerificationExecutor {
  run(
    workspace: string,
    config: VerificationConfig,
    phase: VerificationPhase,
  ): Promise<VerificationAttempt | null>;
}

const DEFAULT_MAX_OUTPUT_BYTES = 2 * 1024 * 1024;
const DEFAULT_PERSISTED_OUTPUT_CHARS = 16_000;
const MAX_FAILURE_KEY_CHARS = 1_000;
const MAX_FAILURE_KEYS = 200;
const ANSI_ESCAPE_PATTERN = /\u001b\[[0-?]*[ -/]*[@-~]/gu;
const FAILURE_MARKER_PATTERN = /\b(?:assert(?:ion)?|error|exception|fail(?:ed|ure)?|fatal|not found|undefined reference|unresolved external)\b/iu;
const SENSITIVE_ENVIRONMENT_PATTERN = /(?:^|_)(?:api_?key|token|secret|password|passwd|credentials?|private_?key)(?:$|_)/iu;

function errorCode(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("code" in error)) return undefined;
  return typeof error.code === "string" ? error.code : undefined;
}

function truncateOutput(value: string, limit: number): string {
  if (value.length <= limit) return value;
  const half = Math.floor(limit / 2);
  return value.slice(0, half) + "\n...<truncated>...\n" + value.slice(-half);
}

function normalizeFailureLine(line: string, workspace: string): string {
  const normalizedWorkspace = workspace.replaceAll("\\", "/");
  const normalized = line
    .replace(ANSI_ESCAPE_PATTERN, "")
    .replaceAll("\\", "/")
    .replaceAll(normalizedWorkspace, "<workspace>")
    .replace(/\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds)\b/giu, "<duration>")
    .replace(/\s+/gu, " ")
    .trim();
  return truncateOutput(normalized, MAX_FAILURE_KEY_CHARS);
}

function isReliableFailureLine(line: string): boolean {
  if (!FAILURE_MARKER_PATTERN.test(line)) return false;
  return !/^(?:\d+\s+)?(?:errors?|fail(?:ed|ures?)?|fatal|exception|assertion)[:.!]?$/iu.test(line);
}

function failureKeys(
  output: string,
  workspace: string,
  fallback: string,
): { readonly keys: readonly string[]; readonly reliable: boolean } {
  const lines = output
    .split(/\r?\n/gu)
    .map((line) => normalizeFailureLine(line, workspace))
    .filter(Boolean);
  const marked = lines.filter((line) => FAILURE_MARKER_PATTERN.test(line));
  const reliableMarked = marked.filter(isReliableFailureLine);
  const selected = reliableMarked.length > 0 ? reliableMarked : marked.length > 0 ? marked : lines.slice(-20);
  const unique = [...new Set(selected)].sort();
  if (unique.length > MAX_FAILURE_KEYS) {
    const retained = unique.slice(0, MAX_FAILURE_KEYS - 1);
    const overflowHash = createHash("sha256").update(JSON.stringify(unique.slice(MAX_FAILURE_KEYS - 1))).digest("hex");
    return { keys: Object.freeze([...retained, `<overflow:${overflowHash}>`]), reliable: reliableMarked.length > 0 };
  }
  if (unique.length > 0) return { keys: Object.freeze(unique), reliable: reliableMarked.length > 0 };
  return { keys: Object.freeze([fallback]), reliable: false };
}

function fingerprint(attempt: Pick<VerificationAttempt, "exitCode" | "timedOut" | "outputLimitExceeded" | "failureKeys" | "failureKeysReliable">): string {
  return createHash("sha256").update(JSON.stringify({
    exitCode: attempt.exitCode,
    timedOut: attempt.timedOut,
    outputLimitExceeded: attempt.outputLimitExceeded,
    failureKeys: attempt.failureKeys,
    failureKeysReliable: attempt.failureKeysReliable,
  })).digest("hex");
}

function shellInvocation(command: string): { readonly executable: string; readonly args: readonly string[] } {
  if (process.platform === "win32") {
    return {
      executable: path.join(process.env.SystemRoot ?? "C:\\Windows", "System32", "cmd.exe"),
      args: ["/d", "/s", "/c", command],
    };
  }
  return { executable: "/bin/sh", args: ["-c", command] };
}

function verificationEnvironment(): Readonly<NodeJS.ProcessEnv> {
  const environment: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (SENSITIVE_ENVIRONMENT_PATTERN.test(key)) continue;
    environment[key] = value;
  }
  environment.CI = process.env.CI ?? "1";
  return environment;
}

export function verificationCommandHash(command: string): string {
  return createHash("sha256").update(command).digest("hex");
}

function commandWasNotFound(exitCode: number, stdout: string, stderr: string): boolean {
  if (exitCode === 127 || exitCode === 9009) return true;
  const output = stdout + "\n" + stderr;
  return /not recognized as an internal or external command|command not found/iu.test(output);
}

export class VerificationRunner implements VerificationExecutor {
  readonly #runner: CommandRunner;
  readonly #clock: () => Date;
  readonly #maxOutputBytes: number;
  readonly #persistedOutputChars: number;

  constructor(options: VerificationRunnerOptions = {}) {
    this.#runner = options.commandRunner ?? new SpawnCommandRunner();
    this.#clock = options.clock ?? (() => new Date());
    this.#maxOutputBytes = options.maxOutputBytes ?? DEFAULT_MAX_OUTPUT_BYTES;
    this.#persistedOutputChars = options.persistedOutputChars ?? DEFAULT_PERSISTED_OUTPUT_CHARS;
  }

  async run(
    workspace: string,
    config: VerificationConfig,
    phase: VerificationPhase,
  ): Promise<VerificationAttempt | null> {
    const command = config.command?.trim() ?? "";
    if (!command) return null;
    if (config.passWhen !== "exit_zero") {
      throw new VerificationError(
        "verification_pass_rule_unsupported",
        `unsupported verification pass_when rule: ${config.passWhen}`,
      );
    }
    if (!Number.isSafeInteger(config.timeoutSeconds) || config.timeoutSeconds < 1) {
      throw new VerificationError("verification_command_invalid", "verification timeout must be a positive integer");
    }

    const assessment = assessBashCommand(command);
    if (assessment.destructive) {
      throw new VerificationError(
        "verification_command_destructive",
        "verification command matches a destructive shell pattern",
      );
    }
    if (assessment.network) {
      throw new VerificationError(
        "verification_network_denied",
        "verification commands cannot access external systems or install dependencies",
      );
    }

    const timeoutMs = config.timeoutSeconds * 1_000;
    const started = this.#clock();
    const invocation = shellInvocation(command);
    let exitCode: number | null = null;
    let stdout = "";
    let stderr = "";
    let comparisonOutput = "";
    let timedOut = false;
    let outputLimitExceeded = false;
    try {
      const result = await this.#runner.run(invocation.executable, invocation.args, {
        cwd: workspace,
        timeoutMs,
        maxOutputBytes: this.#maxOutputBytes,
        env: verificationEnvironment(),
      });
      exitCode = result.exitCode;
      if (commandWasNotFound(result.exitCode, result.stdout, result.stderr)) {
        throw new VerificationError(
          "verification_command_not_found",
          "verification command could not be resolved by the platform shell",
        );
      }
      comparisonOutput = result.stdout + (result.stdout && result.stderr ? "\n" : "") + result.stderr;
      stdout = truncateOutput(result.stdout, this.#persistedOutputChars);
      stderr = truncateOutput(result.stderr, this.#persistedOutputChars);
    } catch (error) {
      const code = errorCode(error);
      if (code === "COMMAND_TIMEOUT") {
        timedOut = true;
        stderr = `verification command timed out after ${String(timeoutMs)}ms`;
        comparisonOutput = stderr;
      } else if (code === "OUTPUT_LIMIT") {
        outputLimitExceeded = true;
        stderr = `verification command output exceeded ${String(this.#maxOutputBytes)} bytes`;
        comparisonOutput = stderr;
      } else if (error instanceof VerificationError) {
        throw error;
      } else {
        throw new VerificationError("verification_spawn_failed", "failed to execute verification command", error);
      }
    }
    const finished = this.#clock();
    const durationMs = Math.max(0, finished.getTime() - started.getTime());
    const passed = exitCode === 0 && !timedOut && !outputLimitExceeded;
    const failure = passed
      ? { keys: Object.freeze([] as string[]), reliable: true }
      : failureKeys(
          comparisonOutput,
          workspace,
          timedOut ? "<timeout>" : outputLimitExceeded ? "<output-limit>" : `<exit:${String(exitCode ?? 1)}>`,
        );
    const partial = {
      exitCode,
      timedOut,
      outputLimitExceeded,
      failureKeys: failure.keys,
      failureKeysReliable: failure.reliable,
    };
    return Object.freeze({
      phase,
      command,
      timeoutMs,
      startedAt: started.toISOString(),
      durationMs,
      exitCode,
      passed,
      timedOut,
      outputLimitExceeded,
      stdout,
      stderr,
      failureKeys: failure.keys,
      failureKeysReliable: failure.reliable,
      fingerprint: fingerprint(partial),
    });
  }
}

export function compareVerification(
  baseline: VerificationAttempt,
  current: VerificationAttempt,
): VerificationComparison {
  if (current.passed) return { status: "passed", allowed: true, newFailures: [] };
  if (baseline.passed) {
    return { status: "regression", allowed: false, newFailures: current.failureKeys };
  }
  if (
    !baseline.failureKeysReliable
    || !current.failureKeysReliable
    || baseline.timedOut
    || current.timedOut
    || baseline.outputLimitExceeded
    || current.outputLimitExceeded
    || baseline.exitCode !== current.exitCode
  ) {
    return { status: "regression", allowed: false, newFailures: current.failureKeys };
  }
  const baselineFailures = new Set(baseline.failureKeys);
  const newFailures = current.failureKeys.filter((failure) => !baselineFailures.has(failure));
  if (newFailures.length === 0) {
    return { status: "pre_existing_failure", allowed: true, newFailures: [] };
  }
  return { status: "regression", allowed: false, newFailures };
}
