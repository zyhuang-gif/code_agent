"""Tool registry and default code-agent tools."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.budget import Budget
from agent.editor import EditResult, SearchReplaceEditor
from agent.locator import Locator
from agent.profile import ProjectProfile
from agent.trace import Trace


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], "RunContext"], ToolResult]


@dataclass
class RunContext:
    workspace: Path
    profile: ProjectProfile
    trace: Trace
    budget: Budget
    locator: Locator
    editor: Any
    runner: Callable[..., dict[str, Any]] | None = None


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]):
        self.specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> ToolSpec:
        return self.specs[name]

    def run(self, name: str, args: dict[str, Any], ctx: RunContext) -> ToolResult:
        start = time.monotonic()
        try:
            result = self.get(name).handler(args, ctx)
        except Exception as exc:
            result = ToolResult(str(exc), is_error=True)
        ctx.trace.tool_exec(step=ctx.budget.steps, tool=name, args=args, result_preview=result.content, is_error=result.is_error, duration_ms=int((time.monotonic() - start) * 1000))
        return result

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters}} for spec in self.specs.values()]


def truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:2000] + "\n...<truncated>...\n" + text[-2000:]


def _resolve(ctx: RunContext, rel: str) -> Path:
    path = (ctx.workspace / rel).resolve()
    if ctx.workspace.resolve() not in [path, *path.parents]:
        raise ValueError("path escapes workspace")
    return path


def list_dir(args: dict[str, Any], ctx: RunContext) -> ToolResult:
    root = _resolve(ctx, args.get("path", "."))
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(ctx.workspace).as_posix()
        if ctx.profile.should_ignore(rel):
            continue
        lines.append(rel + ("/" if path.is_dir() else ""))
    return ToolResult(truncate("\n".join(lines)))


def read_file(args: dict[str, Any], ctx: RunContext) -> ToolResult:
    path = _resolve(ctx, args["path"])
    start = args.get("start_line")
    end = args.get("end_line")
    if path.stat().st_size > ctx.profile.max_file_bytes and (start is None or end is None):
        return ToolResult("file too large; specify start_line and end_line", is_error=True)
    lines = path.read_text(encoding="utf-8").splitlines()
    start = int(start or 1)
    end = int(end or len(lines))
    return ToolResult(truncate("\n".join(f"{i}: {lines[i-1]}" for i in range(start, min(end, len(lines)) + 1))))


def grep(args: dict[str, Any], ctx: RunContext) -> ToolResult:
    hits = ctx.locator.search(args["pattern"], args.get("glob"))
    return ToolResult(truncate("\n".join(f"{hit.path}:{hit.line_no}:{hit.line}" for hit in hits)))


def edit(args: dict[str, Any], ctx: RunContext) -> ToolResult:
    result: EditResult = ctx.editor.edit(_resolve(ctx, args["path"]), args["search"], args["replace"])
    return ToolResult(result.content, result.is_error, result.meta)


def default_runner(cmd: str, cwd: Path | None = None, timeout: int | None = None) -> dict[str, Any]:
    # MVP keeps allow_network as a future policy hook; real isolation arrives later.
    proc = subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True, timeout=timeout)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def run_command(args: dict[str, Any], ctx: RunContext) -> ToolResult:
    runner = ctx.runner or default_runner
    timeout = int(args.get("timeout", 60))
    result = runner(args["cmd"], cwd=ctx.workspace, timeout=timeout)
    content = f"exit_code={result.get('exit_code')}\nstdout:\n{result.get('stdout','')}\nstderr:\n{result.get('stderr','')}"
    return ToolResult(truncate(content), is_error=result.get("exit_code") != 0, meta={"exit_code": result.get("exit_code")})


def finish(args: dict[str, Any], ctx: RunContext) -> ToolResult:
    return ToolResult(args.get("summary", "finished"), meta={"finish": True})


def build_default_registry() -> ToolRegistry:
    any_schema = {"type": "object", "properties": {}, "additionalProperties": True}
    return ToolRegistry([
        ToolSpec("list_dir", "List files under a directory", any_schema, list_dir),
        ToolSpec("read_file", "Read a file range with line numbers", any_schema, read_file),
        ToolSpec("grep", "Search files with regex", any_schema, grep),
        ToolSpec("edit", "Apply a SEARCH/REPLACE edit", any_schema, edit),
        ToolSpec("run_command", "Run a command in the workspace", any_schema, run_command),
        ToolSpec("finish", "Finish the task", any_schema, finish),
    ])
