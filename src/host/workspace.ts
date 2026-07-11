import type { Dirent, Stats } from "node:fs";
import {
  copyFile,
  lstat,
  mkdir,
  readdir,
  realpath,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import {
  RUN_MARKER_SCHEMA_VERSION,
  WorkspaceError,
  createRunLayout,
  isPathWithin,
  pathsEqual,
} from "./run-layout.js";
import type { RunMarker } from "./run-layout.js";

export { RUN_MARKER_SCHEMA_VERSION, WorkspaceError } from "./run-layout.js";
export type { RunLayout, RunMarker, WorkspaceErrorCode } from "./run-layout.js";

export const DEFAULT_WORKSPACE_IGNORE_PATTERNS: readonly string[] = Object.freeze([
  ".git",
  ".Codex/worktrees",
  "node_modules",
  ".venv",
  "__pycache__",
  ".pytest_cache",
  "dist",
  "coverage",
  "workspace",
  "trace",
  ".tmp",
]);

export interface WorkspaceRequest {
  readonly sourceRepository: string;
  readonly runRoot: string;
  readonly sessionId: string;
  readonly ignorePatterns?: readonly string[];
}

export interface WorkspaceSession {
  readonly sessionId: string;
  readonly sourceRepository: string;
  readonly runRoot: string;
  readonly runDirectory: string;
  readonly repository: string;
  readonly artifactsDirectory: string;
  readonly markerPath: string;
}

export interface WorkspaceProvider {
  create(request: WorkspaceRequest): Promise<WorkspaceSession>;
}

export interface WorkspaceFileSystem {
  stat(target: string): Promise<Stats>;
  lstat(target: string): Promise<Stats>;
  realpath(target: string): Promise<string>;
  mkdir(target: string, options: { readonly recursive: boolean }): Promise<void>;
  readdir(target: string): Promise<Dirent[]>;
  copyFile(source: string, destination: string): Promise<void>;
  writeFile(
    target: string,
    data: string,
    options: { readonly encoding: "utf8"; readonly flag: "wx" },
  ): Promise<void>;
}

export interface FileSystemWorkspaceProviderOptions {
  readonly fileSystem?: WorkspaceFileSystem;
}

const nodeFileSystem: WorkspaceFileSystem = {
  stat,
  lstat,
  realpath,
  async mkdir(target, options) {
    await mkdir(target, options);
  },
  async readdir(target) {
    return readdir(target, { withFileTypes: true });
  },
  async copyFile(source, destination) {
    await copyFile(source, destination);
  },
  async writeFile(target, data, options) {
    await writeFile(target, data, options);
  },
};

function systemErrorCode(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("code" in error)) return undefined;
  const code = (error as { readonly code?: unknown }).code;
  return typeof code === "string" ? code : undefined;
}

function normalizeRelativePath(relativePath: string): string {
  return relativePath.split(path.sep).join("/");
}

function normalizeIgnorePattern(pattern: string): string {
  let normalized = pattern.trim().replaceAll("\\", "/");
  while (normalized.startsWith("./")) normalized = normalized.slice(2);
  normalized = normalized.replace(/^\/+|\/+$/gu, "");
  return normalized;
}

function globExpression(pattern: string): RegExp {
  let expression = "^";
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index];
    if (character === "*") {
      if (pattern[index + 1] === "*") {
        expression += ".*";
        index += 1;
      } else {
        expression += "[^/]*";
      }
      continue;
    }
    if (character === "?") {
      expression += "[^/]";
      continue;
    }
    if (character !== undefined && "\\^$+.()|{}[]".includes(character)) expression += "\\";
    expression += character;
  }
  expression += "$";
  return new RegExp(expression, process.platform === "win32" ? "iu" : "u");
}

interface CompiledIgnorePattern {
  readonly includesPath: boolean;
  readonly expression: RegExp;
}

class IgnoreMatcher {
  private readonly patterns: readonly CompiledIgnorePattern[];

  constructor(patterns: readonly string[]) {
    this.patterns = patterns
      .map(normalizeIgnorePattern)
      .filter((pattern) => pattern.length > 0)
      .map((pattern) => ({
        includesPath: pattern.includes("/"),
        expression: globExpression(pattern),
      }));
  }

  matches(relativePath: string): boolean {
    const normalized = normalizeRelativePath(relativePath);
    const segments = normalized.split("/");
    return this.patterns.some((pattern) => (
      pattern.includesPath
        ? pattern.expression.test(normalized)
        : segments.some((segment) => pattern.expression.test(segment))
    ));
  }
}

async function resolveSourceRepository(fileSystem: WorkspaceFileSystem, input: string): Promise<string> {
  const absolute = path.resolve(input);
  let sourceStats: Stats;
  try {
    sourceStats = await fileSystem.stat(absolute);
  } catch (error) {
    throw new WorkspaceError(
      "source_not_found",
      `sourceRepository does not exist or cannot be accessed: ${absolute}`,
      { sourceRepository: absolute, systemCode: systemErrorCode(error) },
      error,
    );
  }

  if (!sourceStats.isDirectory()) {
    throw new WorkspaceError(
      "source_not_directory",
      `sourceRepository is not a directory: ${absolute}`,
      { sourceRepository: absolute },
    );
  }

  try {
    return await fileSystem.realpath(absolute);
  } catch (error) {
    throw new WorkspaceError(
      "source_not_found",
      `sourceRepository cannot be resolved: ${absolute}`,
      { sourceRepository: absolute, systemCode: systemErrorCode(error) },
      error,
    );
  }
}

async function resolveProspectivePath(fileSystem: WorkspaceFileSystem, input: string): Promise<string> {
  let cursor = path.resolve(input);
  const missingComponents: string[] = [];

  while (true) {
    try {
      const existingAncestor = await fileSystem.realpath(cursor);
      return path.resolve(existingAncestor, ...missingComponents);
    } catch (error) {
      if (systemErrorCode(error) !== "ENOENT") {
        throw new WorkspaceError(
          "run_root_invalid",
          `runRoot cannot be resolved: ${path.resolve(input)}`,
          { reason: "run_root_unresolvable", runRoot: path.resolve(input), systemCode: systemErrorCode(error) },
          error,
        );
      }

      const parent = path.dirname(cursor);
      if (parent === cursor) {
        throw new WorkspaceError(
          "run_root_invalid",
          `runRoot has no resolvable ancestor: ${path.resolve(input)}`,
          { reason: "run_root_unresolvable", runRoot: path.resolve(input) },
          error,
        );
      }
      missingComponents.unshift(path.basename(cursor));
      cursor = parent;
    }
  }
}

function assertExternalRunRoot(sourceRepository: string, runRoot: string): void {
  if (isPathWithin(sourceRepository, runRoot)) {
    throw new WorkspaceError(
      "run_root_invalid",
      "runRoot must be outside sourceRepository to prevent recursive workspace copies",
      {
        reason: "run_root_inside_source",
        sourceRepository,
        runRoot,
      },
    );
  }
  if (isPathWithin(runRoot, sourceRepository)) {
    throw new WorkspaceError(
      "run_root_invalid",
      "sourceRepository and runRoot must be completely disjoint directory trees",
      {
        reason: "source_repository_inside_run_root",
        sourceRepository,
        runRoot,
      },
    );
  }
}

async function ensureRunRoot(
  fileSystem: WorkspaceFileSystem,
  sourceRepository: string,
  input: string,
): Promise<string> {
  const prospectiveRunRoot = await resolveProspectivePath(fileSystem, input);
  assertExternalRunRoot(sourceRepository, prospectiveRunRoot);

  try {
    let runRootStats: Stats | undefined;
    try {
      runRootStats = await fileSystem.stat(prospectiveRunRoot);
    } catch (error) {
      if (systemErrorCode(error) !== "ENOENT") throw error;
    }

    if (runRootStats !== undefined && !runRootStats.isDirectory()) {
      throw new WorkspaceError(
        "run_root_invalid",
        `runRoot is not a directory: ${prospectiveRunRoot}`,
        { reason: "run_root_not_directory", runRoot: prospectiveRunRoot },
      );
    }

    await fileSystem.mkdir(prospectiveRunRoot, { recursive: true });
    const resolvedRunRoot = await fileSystem.realpath(prospectiveRunRoot);
    assertExternalRunRoot(sourceRepository, resolvedRunRoot);
    return resolvedRunRoot;
  } catch (error) {
    if (error instanceof WorkspaceError) throw error;
    throw new WorkspaceError(
      "run_root_invalid",
      `runRoot cannot be created or accessed: ${prospectiveRunRoot}`,
      { reason: "run_root_unusable", runRoot: prospectiveRunRoot, systemCode: systemErrorCode(error) },
      error,
    );
  }
}

async function createRunDirectories(fileSystem: WorkspaceFileSystem, session: WorkspaceSession): Promise<void> {
  try {
    await fileSystem.mkdir(session.runDirectory, { recursive: false });
  } catch (error) {
    if (systemErrorCode(error) === "EEXIST") {
      throw new WorkspaceError(
        "run_directory_exists",
        `run directory already exists for sessionId ${session.sessionId}`,
        { sessionId: session.sessionId, runDirectory: session.runDirectory },
        error,
      );
    }
    throw new WorkspaceError(
      "workspace_copy_failed",
      `run directory could not be created: ${session.runDirectory}`,
      { reason: "run_directory_create_failed", runDirectory: session.runDirectory, systemCode: systemErrorCode(error) },
      error,
    );
  }

  try {
    await fileSystem.mkdir(session.repository, { recursive: false });
    await fileSystem.mkdir(session.artifactsDirectory, { recursive: false });
  } catch (error) {
    throw new WorkspaceError(
      "workspace_copy_failed",
      "workspace repository or artifacts directory could not be created",
      {
        reason: "workspace_layout_create_failed",
        repository: session.repository,
        artifactsDirectory: session.artifactsDirectory,
        systemCode: systemErrorCode(error),
      },
      error,
    );
  }
}

async function writeRunMarker(fileSystem: WorkspaceFileSystem, session: WorkspaceSession): Promise<void> {
  const marker: RunMarker = {
    schemaVersion: RUN_MARKER_SCHEMA_VERSION,
    sessionId: session.sessionId,
    sourceRepository: session.sourceRepository,
    repository: session.repository,
    runDirectory: session.runDirectory,
    runRoot: session.runRoot,
  };

  try {
    await fileSystem.writeFile(
      session.markerPath,
      `${JSON.stringify(marker, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" },
    );
  } catch (error) {
    throw new WorkspaceError(
      "marker_write_failed",
      `run marker could not be written: ${session.markerPath}`,
      { markerPath: session.markerPath, systemCode: systemErrorCode(error) },
      error,
    );
  }
}

interface CopyContext {
  readonly fileSystem: WorkspaceFileSystem;
  readonly sourceRoot: string;
  readonly destinationRoot: string;
  readonly matcher: IgnoreMatcher;
}

async function copyDirectoryContents(
  context: CopyContext,
  sourceDirectory: string,
  destinationDirectory: string,
): Promise<void> {
  const entries = await context.fileSystem.readdir(sourceDirectory);
  entries.sort((left, right) => left.name.localeCompare(right.name));

  for (const entry of entries) {
    const sourcePath = path.resolve(sourceDirectory, entry.name);
    const relativePath = path.relative(context.sourceRoot, sourcePath);
    if (!isPathWithin(context.sourceRoot, sourcePath, false)) {
      throw new WorkspaceError(
        "path_escape",
        "source entry escaped sourceRepository during copy",
        { sourceRoot: context.sourceRoot, sourcePath },
      );
    }
    if (context.matcher.matches(relativePath)) continue;

    const destinationPath = path.resolve(destinationDirectory, entry.name);
    if (!isPathWithin(context.destinationRoot, destinationPath, false)) {
      throw new WorkspaceError(
        "path_escape",
        "destination entry escaped isolated repository during copy",
        { destinationRoot: context.destinationRoot, destinationPath },
      );
    }

    const entryStats = await context.fileSystem.lstat(sourcePath);
    if (entryStats.isSymbolicLink()) {
      throw new WorkspaceError(
        "unsupported_link",
        `symbolic links and junctions are not copied in the first workspace implementation: ${relativePath}`,
        { reason: "all_links_rejected", relativePath: normalizeRelativePath(relativePath) },
      );
    }

    if (entryStats.isDirectory()) {
      const resolvedDirectory = await context.fileSystem.realpath(sourcePath);
      if (!isPathWithin(context.sourceRoot, resolvedDirectory)) {
        throw new WorkspaceError(
          "unsupported_link",
          `directory resolves outside sourceRepository: ${relativePath}`,
          {
            reason: "link_escapes_source",
            relativePath: normalizeRelativePath(relativePath),
            resolvedPath: resolvedDirectory,
          },
        );
      }
      await context.fileSystem.mkdir(destinationPath, { recursive: false });
      await copyDirectoryContents(context, sourcePath, destinationPath);
      continue;
    }

    if (entryStats.isFile()) {
      await context.fileSystem.copyFile(sourcePath, destinationPath);
      continue;
    }

    throw new WorkspaceError(
      "workspace_copy_failed",
      `unsupported filesystem entry in sourceRepository: ${relativePath}`,
      { reason: "unsupported_file_type", relativePath: normalizeRelativePath(relativePath) },
    );
  }
}

export class FileSystemWorkspaceProvider implements WorkspaceProvider {
  private readonly fileSystem: WorkspaceFileSystem;

  constructor(options: FileSystemWorkspaceProviderOptions = {}) {
    this.fileSystem = options.fileSystem ?? nodeFileSystem;
  }

  async create(request: WorkspaceRequest): Promise<WorkspaceSession> {
    const sourceRepository = await resolveSourceRepository(this.fileSystem, request.sourceRepository);
    const runRoot = await ensureRunRoot(this.fileSystem, sourceRepository, request.runRoot);
    const layout = createRunLayout(runRoot, request.sessionId);

    if (pathsEqual(sourceRepository, layout.repository)) {
      throw new WorkspaceError(
        "path_escape",
        "sourceRepository and isolated repository must not resolve to the same path",
        { sourceRepository, repository: layout.repository },
      );
    }

    const session: WorkspaceSession = {
      sessionId: request.sessionId,
      sourceRepository,
      runRoot: layout.runRoot,
      runDirectory: layout.runDirectory,
      repository: layout.repository,
      artifactsDirectory: layout.artifactsDirectory,
      markerPath: layout.markerPath,
    };

    await createRunDirectories(this.fileSystem, session);
    await writeRunMarker(this.fileSystem, session);

    const matcher = new IgnoreMatcher([
      ...DEFAULT_WORKSPACE_IGNORE_PATTERNS,
      ...(request.ignorePatterns ?? []),
    ]);
    try {
      await copyDirectoryContents(
        {
          fileSystem: this.fileSystem,
          sourceRoot: sourceRepository,
          destinationRoot: session.repository,
          matcher,
        },
        sourceRepository,
        session.repository,
      );
    } catch (error) {
      if (error instanceof WorkspaceError) throw error;
      throw new WorkspaceError(
        "workspace_copy_failed",
        "sourceRepository could not be copied into the isolated repository",
        {
          sourceRepository,
          repository: session.repository,
          systemCode: systemErrorCode(error),
        },
        error,
      );
    }

    return session;
  }
}
