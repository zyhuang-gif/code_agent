import { randomUUID } from "node:crypto";
import { mkdir, open, rename, rm } from "node:fs/promises";
import type { FileHandle } from "node:fs/promises";
import path from "node:path";

export interface ArtifactWorkspace {
  readonly runDirectory: string;
  readonly repository: string;
  readonly artifactsDirectory: string;
}

export interface ArtifactPaths {
  readonly directory: string;
  readonly diffPath: string;
  readonly resultPath: string;
}

export interface ArtifactStore {
  readonly paths: ArtifactPaths;
  initialize(): Promise<void>;
  writeFinalDiff(diff: string): Promise<string>;
  writeResult(result: unknown): Promise<string>;
}

export class ArtifactError extends Error {
  constructor(
    readonly code: "artifact_path_invalid" | "artifact_path_escape" | "artifact_write_failed",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ArtifactError";
  }
}

function isStrictChild(parent: string, candidate: string): boolean {
  const relative = path.relative(parent, candidate);
  return relative !== ""
    && relative !== ".."
    && !relative.startsWith(".." + path.sep)
    && !path.isAbsolute(relative);
}

function childPath(directory: string, name: string): string {
  const candidate = path.resolve(directory, name);
  if (!isStrictChild(directory, candidate)) {
    throw new ArtifactError("artifact_path_escape", "artifact path escapes the artifact directory");
  }
  return candidate;
}

function validateWorkspace(workspace: ArtifactWorkspace): ArtifactWorkspace {
  const runDirectory = path.resolve(workspace.runDirectory);
  const repository = path.resolve(workspace.repository);
  const artifactsDirectory = path.resolve(workspace.artifactsDirectory);
  if (!isStrictChild(runDirectory, repository) || !isStrictChild(runDirectory, artifactsDirectory)) {
    throw new ArtifactError(
      "artifact_path_invalid",
      "repository and artifactsDirectory must be children of runDirectory",
    );
  }
  if (isStrictChild(repository, artifactsDirectory) || isStrictChild(artifactsDirectory, repository)) {
    throw new ArtifactError(
      "artifact_path_invalid",
      "artifactsDirectory must be outside the isolated repository",
    );
  }
  return { runDirectory, repository, artifactsDirectory };
}

async function atomicWrite(target: string, content: string): Promise<void> {
  const temporary = target + "." + randomUUID() + ".tmp";
  let handle: FileHandle | undefined;
  try {
    handle = await open(temporary, "wx");
    await handle.writeFile(content, "utf8");
    await handle.sync();
    await handle.close();
    handle = undefined;
    await rm(target, { force: true });
    await rename(temporary, target);
  } catch (error) {
    if (handle) await handle.close().catch(() => undefined);
    await rm(temporary, { force: true }).catch(() => undefined);
    throw new ArtifactError(
      "artifact_write_failed",
      "failed to write artifact: " + target,
      { cause: error },
    );
  }
}

export class FileSystemArtifactStore implements ArtifactStore {
  readonly paths: ArtifactPaths;

  constructor(workspace: ArtifactWorkspace) {
    const validated = validateWorkspace(workspace);
    this.paths = Object.freeze({
      directory: validated.artifactsDirectory,
      diffPath: childPath(validated.artifactsDirectory, "final.diff"),
      resultPath: childPath(validated.artifactsDirectory, "result.json"),
    });
  }

  async initialize(): Promise<void> {
    try {
      await mkdir(this.paths.directory, { recursive: true });
    } catch (error) {
      throw new ArtifactError(
        "artifact_write_failed",
        "failed to initialize artifact directory: " + this.paths.directory,
        { cause: error },
      );
    }
  }

  async writeFinalDiff(diff: string): Promise<string> {
    await this.initialize();
    await atomicWrite(this.paths.diffPath, diff);
    return this.paths.diffPath;
  }

  async writeResult(result: unknown): Promise<string> {
    await this.initialize();
    await atomicWrite(this.paths.resultPath, JSON.stringify(result, null, 2) + "\n");
    return this.paths.resultPath;
  }
}
