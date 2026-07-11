import { access, realpath } from "node:fs/promises";
import path from "node:path";

function assertInside(workspace: string, candidate: string): void {
  const relative = path.relative(workspace, candidate);
  if (relative === "" || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative))) {
    return;
  }
  throw new Error("path escapes workspace");
}

function assertWritableTarget(workspace: string, candidate: string): void {
  const parts = path.relative(workspace, candidate).split(path.sep).filter(Boolean);
  if (parts.some((part) => part.toLowerCase() === ".git")) {
    throw new Error("writing Git metadata through file tools is not allowed");
  }
}

async function exists(candidate: string): Promise<boolean> {
  try {
    await access(candidate);
    return true;
  } catch {
    return false;
  }
}

export async function resolveWorkspacePath(
  workspace: string,
  relativePath: string,
  options: { readonly mustExist?: boolean; readonly writable?: boolean } = {},
): Promise<string> {
  if (path.isAbsolute(relativePath)) {
    throw new Error("absolute paths are not allowed");
  }

  const realWorkspace = await realpath(workspace);
  const candidate = path.resolve(realWorkspace, relativePath || ".");
  assertInside(realWorkspace, candidate);

  if (options.writable) assertWritableTarget(realWorkspace, candidate);

  if (options.mustExist) {
    const realCandidate = await realpath(candidate);
    assertInside(realWorkspace, realCandidate);
    if (options.writable) assertWritableTarget(realWorkspace, realCandidate);
    return realCandidate;
  }

  let ancestor = candidate;
  while (!(await exists(ancestor))) {
    const parent = path.dirname(ancestor);
    if (parent === ancestor) {
      throw new Error("could not resolve writable path ancestor");
    }
    ancestor = parent;
  }
  const realAncestor = await realpath(ancestor);
  assertInside(realWorkspace, realAncestor);
  if (options.writable) assertWritableTarget(realWorkspace, realAncestor);
  return candidate;
}
