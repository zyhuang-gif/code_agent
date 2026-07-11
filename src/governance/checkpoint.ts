import { spawn } from "node:child_process";
import { lstat, readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";

export interface Checkpoint {
  initialize(): Promise<void>;
  diff(): Promise<string>;
  rollback(): Promise<void>;
}

export interface CommandRunOptions {
  readonly cwd: string;
  readonly maxOutputBytes?: number;
  readonly timeoutMs?: number;
  readonly env?: Readonly<NodeJS.ProcessEnv>;
}

export interface CommandResult {
  readonly exitCode: number;
  readonly stdout: string;
  readonly stderr: string;
}

export interface CommandRunner {
  run(command: string, args: readonly string[], options: CommandRunOptions): Promise<CommandResult>;
}

export type CheckpointOperation = "validation" | "initialize" | "diff" | "rollback";

export type CheckpointErrorCode =
  | "run_root_invalid"
  | "run_directory_invalid"
  | "repository_invalid"
  | "path_escape"
  | "marker_missing"
  | "marker_invalid"
  | "source_not_found"
  | "source_repository_conflict"
  | "git_not_available"
  | "checkpoint_init_failed"
  | "diff_failed"
  | "rollback_failed";

export interface CheckpointErrorDetails {
  readonly code: CheckpointErrorCode;
  readonly operation: CheckpointOperation;
  readonly message: string;
  readonly command?: string;
  readonly args?: readonly string[];
  readonly exitCode?: number;
  readonly stdout?: string;
  readonly stderr?: string;
  readonly cause?: unknown;
}

export class CheckpointError extends Error {
  readonly code: CheckpointErrorCode;
  readonly operation: CheckpointOperation;
  readonly command: string | undefined;
  readonly args: readonly string[] | undefined;
  readonly exitCode: number | undefined;
  readonly stdout: string | undefined;
  readonly stderr: string | undefined;
  readonly originalCause: unknown;

  constructor(details: CheckpointErrorDetails) {
    super(details.message);
    this.name = "CheckpointError";
    this.code = details.code;
    this.operation = details.operation;
    this.command = details.command;
    this.args = details.args;
    this.exitCode = details.exitCode;
    this.stdout = details.stdout;
    this.stderr = details.stderr;
    this.originalCause = details.cause;
  }
}

export interface CheckpointRunMarker {
  readonly schemaVersion: 1;
  readonly sessionId: string;
  readonly sourceRepository: string;
  readonly repository: string;
  readonly runDirectory: string;
  readonly runRoot: string;
  readonly [key: string]: unknown;
}

export interface GitCheckpointOptions {
  readonly repository: string;
  readonly runDirectory: string;
  readonly runRoot: string;
  readonly markerPath?: string;
  readonly commandRunner?: CommandRunner;
  readonly maxDiffBytes?: number;
}

interface ValidatedWorkspace {
  readonly repository: string;
  readonly runDirectory: string;
  readonly runRoot: string;
  readonly markerPath: string;
  readonly sourceRepository: string;
}

const DEFAULT_MAX_COMMAND_OUTPUT_BYTES = 32 * 1024 * 1024;
const DEFAULT_MAX_DIFF_BYTES = 32 * 1024 * 1024;
const DEFAULT_GIT_TIMEOUT_MS = 120_000;
const MAX_ARGUMENT_BYTES = 24 * 1024;
const BASELINE_OID_PATTERN = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/iu;

class CommandOutputLimitError extends Error {
  readonly code = "OUTPUT_LIMIT";

  constructor(readonly maxOutputBytes: number) {
    super(`command output exceeded ${String(maxOutputBytes)} bytes`);
    this.name = "CommandOutputLimitError";
  }
}

class CommandTimeoutError extends Error {
  readonly code = "COMMAND_TIMEOUT";

  constructor(readonly timeoutMs: number) {
    super(`command timed out after ${String(timeoutMs)}ms`);
    this.name = "CommandTimeoutError";
  }
}

function terminateProcessTree(child: ReturnType<typeof spawn>): void {
  if (process.platform === "win32" && child.pid !== undefined) {
    const taskkill = path.join(process.env.SystemRoot ?? "C:\\Windows", "System32", "taskkill.exe");
    const killer = spawn(taskkill, ["/pid", String(child.pid), "/t", "/f"], {
      shell: false,
      windowsHide: true,
      stdio: "ignore",
    });
    killer.once("error", () => { child.kill("SIGKILL"); });
    killer.once("close", (code) => {
      if (code !== 0) child.kill("SIGKILL");
    });
    return;
  }
  if (child.pid !== undefined) {
    try {
      process.kill(-child.pid, "SIGKILL");
      return;
    } catch {
      // Fall through when the detached process group no longer exists.
    }
  }
  child.kill("SIGKILL");
}

export class SpawnCommandRunner implements CommandRunner {
  async run(command: string, args: readonly string[], options: CommandRunOptions): Promise<CommandResult> {
    const maxOutputBytes = options.maxOutputBytes ?? DEFAULT_MAX_COMMAND_OUTPUT_BYTES;
    const timeoutMs = options.timeoutMs ?? DEFAULT_GIT_TIMEOUT_MS;
    if (!Number.isSafeInteger(maxOutputBytes) || maxOutputBytes <= 0) {
      throw new RangeError("maxOutputBytes must be a positive safe integer");
    }
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
      throw new RangeError("timeoutMs must be a positive safe integer");
    }

    return await new Promise<CommandResult>((resolve, reject) => {
      const child = spawn(command, [...args], {
        cwd: options.cwd,
        env: { ...(options.env ?? process.env) },
        shell: false,
        detached: process.platform !== "win32",
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
      const stdout: Buffer[] = [];
      const stderr: Buffer[] = [];
      let outputBytes = 0;
      let outputLimitError: CommandOutputLimitError | undefined;
      let timeoutError: CommandTimeoutError | undefined;
      let settled = false;

      const timer = setTimeout(() => {
        if (settled) return;
        timeoutError = new CommandTimeoutError(timeoutMs);
        terminateProcessTree(child);
      }, timeoutMs);

      const rejectOnce = (error: unknown): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      };
      const resolveOnce = (result: CommandResult): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(result);
      };
      const collect = (target: Buffer[], chunk: Buffer | string): void => {
        if (outputLimitError || timeoutError) return;
        const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        outputBytes += buffer.byteLength;
        if (outputBytes > maxOutputBytes) {
          outputLimitError = new CommandOutputLimitError(maxOutputBytes);
          terminateProcessTree(child);
          return;
        }
        target.push(buffer);
      };

      child.stdout.on("data", (chunk: Buffer | string) => collect(stdout, chunk));
      child.stderr.on("data", (chunk: Buffer | string) => collect(stderr, chunk));
      child.once("error", (error) => rejectOnce(timeoutError ?? outputLimitError ?? error));
      child.once("close", (code) => {
        if (timeoutError) {
          rejectOnce(timeoutError);
          return;
        }
        if (outputLimitError) {
          rejectOnce(outputLimitError);
          return;
        }
        resolveOnce({
          exitCode: code ?? 1,
          stdout: Buffer.concat(stdout).toString("utf8"),
          stderr: Buffer.concat(stderr).toString("utf8"),
        });
      });
    });
  }
}

function controlledGitEnvironment(): Readonly<NodeJS.ProcessEnv> {
  const environment: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    const normalized = key.toUpperCase();
    if (normalized.startsWith("GIT_") || normalized === "GCM_INTERACTIVE") continue;
    environment[key] = value;
  }
  environment.GIT_CONFIG_NOSYSTEM = "1";
  environment.GIT_CONFIG_GLOBAL = process.platform === "win32" ? "NUL" : "/dev/null";
  environment.GIT_CONFIG_COUNT = "0";
  environment.GIT_ATTR_NOSYSTEM = "1";
  environment.GIT_TERMINAL_PROMPT = "0";
  environment.GCM_INTERACTIVE = "Never";
  return Object.freeze(environment);
}

function isErrno(error: unknown, code: string): boolean {
  return error instanceof Error && "code" in error && error.code === code;
}

function samePath(left: string, right: string): boolean {
  return path.relative(left, right) === "";
}

function isInside(parent: string, candidate: string): boolean {
  const relative = path.relative(parent, candidate);
  return relative !== ""
    && relative !== ".."
    && !relative.startsWith(`..${path.sep}`)
    && !path.isAbsolute(relative);
}

function isSameOrInside(parent: string, candidate: string): boolean {
  return samePath(parent, candidate) || isInside(parent, candidate);
}

function requireNonEmptyPath(value: string, code: CheckpointErrorCode, operation: CheckpointOperation, label: string): string {
  if (value.trim().length === 0) {
    throw new CheckpointError({ code, operation, message: `${label} path must not be empty` });
  }
  return path.resolve(value);
}

async function canonicalDirectory(
  value: string,
  code: CheckpointErrorCode,
  operation: CheckpointOperation,
  label: string,
): Promise<string> {
  const resolved = requireNonEmptyPath(value, code, operation, label);
  try {
    const canonical = await realpath(resolved);
    const metadata = await stat(canonical);
    if (!metadata.isDirectory()) {
      throw new CheckpointError({ code, operation, message: `${label} is not a directory: ${resolved}` });
    }
    return canonical;
  } catch (error) {
    if (error instanceof CheckpointError) throw error;
    throw new CheckpointError({
      code,
      operation,
      message: `${label} is unavailable: ${resolved}`,
      cause: error,
    });
  }
}

function readRequiredAbsolutePath(
  marker: Readonly<Record<string, unknown>>,
  key: "sourceRepository" | "repository" | "runDirectory" | "runRoot",
  markerPath: string,
  operation: CheckpointOperation,
): string {
  const value = marker[key];
  if (typeof value !== "string" || value.trim().length === 0 || !path.isAbsolute(value)) {
    throw new CheckpointError({
      code: "marker_invalid",
      operation,
      message: `run marker ${key} must be a non-empty absolute path: ${markerPath}`,
    });
  }
  return value;
}

function parseMarker(contents: string, markerPath: string, operation: CheckpointOperation): CheckpointRunMarker {
  let parsed: unknown;
  try {
    parsed = JSON.parse(contents) as unknown;
  } catch (error) {
    throw new CheckpointError({
      code: "marker_invalid",
      operation,
      message: `run marker is not valid JSON: ${markerPath}`,
      cause: error,
    });
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new CheckpointError({
      code: "marker_invalid",
      operation,
      message: `run marker must contain a JSON object: ${markerPath}`,
    });
  }

  const raw = parsed as Record<string, unknown>;
  if (raw.schemaVersion !== 1) {
    throw new CheckpointError({
      code: "marker_invalid",
      operation,
      message: `run marker schemaVersion must equal 1: ${markerPath}`,
    });
  }
  if (typeof raw.sessionId !== "string" || raw.sessionId.trim().length === 0) {
    throw new CheckpointError({
      code: "marker_invalid",
      operation,
      message: `run marker sessionId must be non-empty: ${markerPath}`,
    });
  }

  return {
    ...raw,
    schemaVersion: 1,
    sessionId: raw.sessionId,
    sourceRepository: readRequiredAbsolutePath(raw, "sourceRepository", markerPath, operation),
    repository: readRequiredAbsolutePath(raw, "repository", markerPath, operation),
    runDirectory: readRequiredAbsolutePath(raw, "runDirectory", markerPath, operation),
    runRoot: readRequiredAbsolutePath(raw, "runRoot", markerPath, operation),
  };
}

function commandFailureMessage(command: string, args: readonly string[], result: CommandResult): string {
  const detail = result.stderr.trim() || result.stdout.trim() || "no command output";
  return `${command} ${args.join(" ")} failed with exit code ${String(result.exitCode)}: ${detail}`;
}

function argumentChunks(paths: readonly string[]): readonly string[][] {
  const chunks: string[][] = [];
  let current: string[] = [];
  let currentBytes = 0;
  for (const entry of paths) {
    const entryBytes = Buffer.byteLength(entry, "utf8") + 1;
    if (current.length > 0 && currentBytes + entryBytes > MAX_ARGUMENT_BYTES) {
      chunks.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(entry);
    currentBytes += entryBytes;
  }
  if (current.length > 0) chunks.push(current);
  return chunks;
}

function validateBaselineOid(value: string): string | undefined {
  const oid = value.trim();
  return BASELINE_OID_PATTERN.test(oid) ? oid : undefined;
}

export class GitCheckpoint implements Checkpoint {
  readonly #runner: CommandRunner;
  readonly #maxDiffBytes: number;
  readonly #gitEnvironment = controlledGitEnvironment();
  #baselineOid: string | undefined;

  constructor(private readonly options: GitCheckpointOptions) {
    this.#runner = options.commandRunner ?? new SpawnCommandRunner();
    this.#maxDiffBytes = options.maxDiffBytes ?? DEFAULT_MAX_DIFF_BYTES;
    if (!Number.isSafeInteger(this.#maxDiffBytes) || this.#maxDiffBytes <= 0) {
      throw new CheckpointError({
        code: "diff_failed",
        operation: "validation",
        message: "maxDiffBytes must be a positive safe integer",
      });
    }
  }

  async initialize(): Promise<void> {
    const workspace = await this.#validateWorkspace("initialize");
    await this.#ensureNoGitMetadata(workspace.repository);
    this.#baselineOid = undefined;
    await this.#runGit(workspace.repository, ["init", "--template="], "initialize", "checkpoint_init_failed");
    await this.#runGit(
      workspace.repository,
      ["config", "--local", "user.name", "Code Agent"],
      "initialize",
      "checkpoint_init_failed",
    );
    await this.#runGit(
      workspace.repository,
      ["config", "--local", "user.email", "code-agent@localhost"],
      "initialize",
      "checkpoint_init_failed",
    );
    await this.#runGit(
      workspace.repository,
      ["config", "--local", "core.autocrlf", "false"],
      "initialize",
      "checkpoint_init_failed",
    );
    await this.#runGit(workspace.repository, ["add", "-A", "-f"], "initialize", "checkpoint_init_failed");
    await this.#runGit(
      workspace.repository,
      ["commit", "--allow-empty", "--no-verify", "--no-gpg-sign", "-m", "baseline"],
      "initialize",
      "checkpoint_init_failed",
    );
    const baseline = await this.#runGit(
      workspace.repository,
      ["rev-parse", "--verify", "HEAD"],
      "initialize",
      "checkpoint_init_failed",
    );
    const baselineOid = validateBaselineOid(baseline.stdout);
    if (baselineOid === undefined) {
      throw new CheckpointError({
        code: "checkpoint_init_failed",
        operation: "initialize",
        message: "Git returned an invalid baseline object identifier",
        command: "git",
        args: ["rev-parse", "--verify", "HEAD"],
        stdout: baseline.stdout,
        stderr: baseline.stderr,
      });
    }
    this.#baselineOid = baselineOid;
  }

  async diff(): Promise<string> {
    const workspace = await this.#validateWorkspace("diff");
    return await this.#generateDiff(
      workspace.repository,
      this.#requireBaseline("diff"),
      "diff",
      "diff_failed",
    );
  }

  async rollback(): Promise<void> {
    const workspace = await this.#validateWorkspace("rollback");
    const baselineOid = this.#requireBaseline("rollback");
    await this.#runGit(
      workspace.repository,
      ["reset", "--hard", baselineOid],
      "rollback",
      "rollback_failed",
    );
    await this.#runGit(
      workspace.repository,
      ["clean", "-ffdx"],
      "rollback",
      "rollback_failed",
    );
    const remaining = await this.#generateDiff(workspace.repository, baselineOid, "rollback", "rollback_failed");
    if (remaining.length > 0) {
      throw new CheckpointError({
        code: "rollback_failed",
        operation: "rollback",
        message: "rollback completed but repository diff is not empty",
      });
    }
  }

  #requireBaseline(operation: "diff" | "rollback"): string {
    if (this.#baselineOid !== undefined) return this.#baselineOid;
    throw new CheckpointError({
      code: operation === "diff" ? "diff_failed" : "rollback_failed",
      operation,
      message: "checkpoint must be initialized before it can be used",
    });
  }

  async #generateDiff(
    repository: string,
    baselineOid: string,
    operation: CheckpointOperation,
    failureCode: "diff_failed" | "rollback_failed",
  ): Promise<string> {
    const untracked = await this.#runGit(
      repository,
      ["ls-files", "--others", "-z"],
      operation,
      failureCode,
    );
    const paths = untracked.stdout.split("\0").filter((entry) => entry.length > 0);
    for (const chunk of argumentChunks(paths)) {
      await this.#runGit(
        repository,
        ["add", "--intent-to-add", "--force", "--", ...chunk],
        operation,
        failureCode,
      );
    }
    const result = await this.#runGit(
      repository,
      ["diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-color", baselineOid],
      operation,
      failureCode,
      this.#maxDiffBytes,
    );
    if (Buffer.byteLength(result.stdout, "utf8") > this.#maxDiffBytes) {
      throw new CheckpointError({
        code: failureCode,
        operation,
        message: `git diff exceeded ${String(this.#maxDiffBytes)} bytes`,
      });
    }
    return result.stdout;
  }

  async #validateWorkspace(operation: CheckpointOperation): Promise<ValidatedWorkspace> {
    const runRoot = await canonicalDirectory(
      this.options.runRoot,
      "run_root_invalid",
      operation,
      "run root",
    );
    const runDirectory = await canonicalDirectory(
      this.options.runDirectory,
      "run_directory_invalid",
      operation,
      "run directory",
    );
    if (!isInside(runRoot, runDirectory)) {
      throw new CheckpointError({
        code: "path_escape",
        operation,
        message: `run directory must be a child of run root: ${runDirectory}`,
      });
    }

    const repository = await canonicalDirectory(
      this.options.repository,
      "repository_invalid",
      operation,
      "isolated repository",
    );
    if (!isInside(runDirectory, repository)
      || !samePath(path.dirname(repository), runDirectory)
      || path.basename(repository).toLowerCase() !== "repository") {
      throw new CheckpointError({
        code: "path_escape",
        operation,
        message: `isolated repository must be the repository child of run directory: ${repository}`,
      });
    }

    const configuredMarker = this.options.markerPath === undefined
      ? path.join(runDirectory, "run.json")
      : path.isAbsolute(this.options.markerPath)
        ? path.resolve(this.options.markerPath)
        : path.resolve(runDirectory, this.options.markerPath);
    if (!isInside(runDirectory, configuredMarker) || isSameOrInside(repository, configuredMarker)) {
      throw new CheckpointError({
        code: "path_escape",
        operation,
        message: `run marker must be inside run directory and outside repository: ${configuredMarker}`,
      });
    }

    let markerMetadata;
    try {
      markerMetadata = await lstat(configuredMarker);
    } catch (error) {
      if (isErrno(error, "ENOENT")) {
        throw new CheckpointError({
          code: "marker_missing",
          operation,
          message: `run marker does not exist: ${configuredMarker}`,
          cause: error,
        });
      }
      throw new CheckpointError({
        code: "marker_invalid",
        operation,
        message: `run marker cannot be inspected: ${configuredMarker}`,
        cause: error,
      });
    }
    if (!markerMetadata.isFile() || markerMetadata.isSymbolicLink()) {
      throw new CheckpointError({
        code: "marker_invalid",
        operation,
        message: `run marker must be a regular file, not a link: ${configuredMarker}`,
      });
    }
    const markerPath = await realpath(configuredMarker);
    if (!isInside(runDirectory, markerPath) || isSameOrInside(repository, markerPath)) {
      throw new CheckpointError({
        code: "path_escape",
        operation,
        message: `resolved run marker escaped its trusted location: ${markerPath}`,
      });
    }

    let markerContents: string;
    try {
      markerContents = await readFile(markerPath, "utf8");
    } catch (error) {
      throw new CheckpointError({
        code: "marker_invalid",
        operation,
        message: `run marker cannot be read: ${markerPath}`,
        cause: error,
      });
    }
    const marker = parseMarker(markerContents, markerPath, operation);
    if (marker.sessionId !== path.basename(runDirectory)) {
      throw new CheckpointError({
        code: "marker_invalid",
        operation,
        message: "run marker sessionId does not match the validated run directory",
      });
    }

    const sourceRepository = await canonicalDirectory(
      marker.sourceRepository,
      "source_not_found",
      operation,
      "source repository",
    );
    if (!samePath(path.resolve(marker.sourceRepository), sourceRepository)) {
      throw new CheckpointError({
        code: "marker_invalid",
        operation,
        message: "run marker sourceRepository must be a canonical path",
      });
    }
    if (samePath(sourceRepository, repository)
      || isInside(sourceRepository, repository)
      || isInside(repository, sourceRepository)) {
      throw new CheckpointError({
        code: "source_repository_conflict",
        operation,
        message: "source repository and isolated repository must be separate directory trees",
      });
    }

    await this.#validateMarkerPath(marker.repository, repository, "repository", operation);
    await this.#validateMarkerPath(marker.runDirectory, runDirectory, "runDirectory", operation);
    await this.#validateMarkerPath(marker.runRoot, runRoot, "runRoot", operation);

    return { repository, runDirectory, runRoot, markerPath, sourceRepository };
  }

  async #validateMarkerPath(
    value: string,
    expected: string,
    label: "repository" | "runDirectory" | "runRoot",
    operation: CheckpointOperation,
  ): Promise<void> {
    const actual = await canonicalDirectory(value, "marker_invalid", operation, `run marker ${label}`);
    if (!samePath(path.resolve(value), expected) || !samePath(actual, expected)) {
      throw new CheckpointError({
        code: "marker_invalid",
        operation,
        message: `run marker ${label} does not exactly match the validated workspace`,
      });
    }
  }

  async #ensureNoGitMetadata(repository: string): Promise<void> {
    const gitMetadata = path.join(repository, ".git");
    try {
      await lstat(gitMetadata);
    } catch (error) {
      if (isErrno(error, "ENOENT")) return;
      throw new CheckpointError({
        code: "checkpoint_init_failed",
        operation: "initialize",
        message: `cannot inspect existing Git metadata: ${gitMetadata}`,
        cause: error,
      });
    }
    throw new CheckpointError({
      code: "checkpoint_init_failed",
      operation: "initialize",
      message: `isolated repository already contains Git metadata: ${gitMetadata}`,
    });
  }

  async #runGit(
    repository: string,
    args: readonly string[],
    operation: CheckpointOperation,
    failureCode: "checkpoint_init_failed" | "diff_failed" | "rollback_failed",
    maxOutputBytes?: number,
  ): Promise<CommandResult> {
    let result: CommandResult;
    try {
      const commandOptions: CommandRunOptions = maxOutputBytes === undefined
        ? {
            cwd: repository,
            timeoutMs: DEFAULT_GIT_TIMEOUT_MS,
            env: this.#gitEnvironment,
          }
        : {
            cwd: repository,
            maxOutputBytes,
            timeoutMs: DEFAULT_GIT_TIMEOUT_MS,
            env: this.#gitEnvironment,
          };
      result = await this.#runner.run("git", args, commandOptions);
    } catch (error) {
      if (isErrno(error, "ENOENT")) {
        throw new CheckpointError({
          code: "git_not_available",
          operation,
          message: "Git executable is not available",
          command: "git",
          args,
          cause: error,
        });
      }
      throw new CheckpointError({
        code: failureCode,
        operation,
        message: error instanceof Error ? error.message : "Git command failed before returning a result",
        command: "git",
        args,
        cause: error,
      });
    }
    if (result.exitCode !== 0) {
      throw new CheckpointError({
        code: result.exitCode === 127 ? "git_not_available" : failureCode,
        operation,
        message: commandFailureMessage("git", args, result),
        command: "git",
        args,
        exitCode: result.exitCode,
        stdout: result.stdout,
        stderr: result.stderr,
      });
    }
    return result;
  }
}
