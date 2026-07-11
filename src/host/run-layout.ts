import path from "node:path";

export const RUN_MARKER_SCHEMA_VERSION = 1 as const;

export type WorkspaceErrorCode =
  | "source_not_found"
  | "source_not_directory"
  | "run_root_invalid"
  | "path_escape"
  | "run_directory_exists"
  | "unsupported_link"
  | "workspace_copy_failed"
  | "marker_write_failed";

export class WorkspaceError extends Error {
  readonly code: WorkspaceErrorCode;
  readonly details: Readonly<Record<string, unknown>>;

  constructor(
    code: WorkspaceErrorCode,
    message: string,
    details: Readonly<Record<string, unknown>> = {},
    cause?: unknown,
  ) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "WorkspaceError";
    this.code = code;
    this.details = Object.freeze({ ...details });
  }
}

export interface RunLayout {
  readonly runRoot: string;
  readonly runDirectory: string;
  readonly repository: string;
  readonly artifactsDirectory: string;
  readonly markerPath: string;
}

export interface RunMarker {
  readonly schemaVersion: typeof RUN_MARKER_SCHEMA_VERSION;
  readonly sessionId: string;
  readonly sourceRepository: string;
  readonly repository: string;
  readonly runDirectory: string;
  readonly runRoot: string;
}

function comparisonPath(value: string): string {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLocaleLowerCase("en-US") : resolved;
}

export function pathsEqual(left: string, right: string): boolean {
  return comparisonPath(left) === comparisonPath(right);
}

export function isPathWithin(parent: string, candidate: string, includeParent = true): boolean {
  const relative = path.relative(comparisonPath(parent), comparisonPath(candidate));
  if (relative === "") return includeParent;
  return relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function validateSessionId(sessionId: string): void {
  const invalidComponent = /[<>:"/\\|?*\u0000-\u001f]/u;
  if (
    sessionId.length === 0
    || sessionId.trim() !== sessionId
    || sessionId === "."
    || sessionId === ".."
    || sessionId.endsWith(".")
    || invalidComponent.test(sessionId)
  ) {
    throw new WorkspaceError(
      "run_root_invalid",
      "sessionId must be a single safe path component",
      { reason: "invalid_session_id", sessionId },
    );
  }

  const windowsDeviceStem = (sessionId.split(".", 1)[0] ?? "").replace(/[ .]+$/gu, "");
  if (/^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/iu.test(windowsDeviceStem)) {
    throw new WorkspaceError(
      "run_root_invalid",
      "sessionId must not use a Windows reserved device name",
      {
        reason: "invalid_session_id",
        rule: "windows_reserved_component",
        sessionId,
      },
    );
  }
}

function assertStrictlyInside(parent: string, candidate: string, field: string): void {
  if (!isPathWithin(parent, candidate, false)) {
    throw new WorkspaceError(
      "path_escape",
      `${field} must be located inside runRoot`,
      { field, parent, candidate },
    );
  }
}

export function createRunLayout(runRoot: string, sessionId: string): RunLayout {
  if (!path.isAbsolute(runRoot)) {
    throw new WorkspaceError(
      "run_root_invalid",
      "runRoot must be an absolute resolved path",
      { reason: "run_root_not_absolute", runRoot },
    );
  }

  validateSessionId(sessionId);

  const resolvedRunRoot = path.resolve(runRoot);
  const runDirectory = path.resolve(resolvedRunRoot, sessionId);
  const repository = path.resolve(runDirectory, "repository");
  const artifactsDirectory = path.resolve(runDirectory, "artifacts");
  const markerPath = path.resolve(runDirectory, "run.json");

  assertStrictlyInside(resolvedRunRoot, runDirectory, "runDirectory");
  assertStrictlyInside(resolvedRunRoot, repository, "repository");
  assertStrictlyInside(resolvedRunRoot, artifactsDirectory, "artifactsDirectory");
  assertStrictlyInside(resolvedRunRoot, markerPath, "markerPath");

  if (!isPathWithin(runDirectory, repository, false)) {
    throw new WorkspaceError(
      "path_escape",
      "repository must be located inside runDirectory",
      { runDirectory, repository },
    );
  }
  if (!isPathWithin(runDirectory, artifactsDirectory, false)) {
    throw new WorkspaceError(
      "path_escape",
      "artifactsDirectory must be located inside runDirectory",
      { runDirectory, artifactsDirectory },
    );
  }
  if (isPathWithin(repository, artifactsDirectory) || isPathWithin(artifactsDirectory, repository)) {
    throw new WorkspaceError(
      "path_escape",
      "repository and artifactsDirectory must be separate sibling directories",
      { repository, artifactsDirectory },
    );
  }

  return {
    runRoot: resolvedRunRoot,
    runDirectory,
    repository,
    artifactsDirectory,
    markerPath,
  };
}
