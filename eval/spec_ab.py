"""AgentSpec A/B/C evaluation runner.

This module reuses eval.run_eval and only adds treatment orchestration.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

from agent.profile import ProjectProfile
from eval.run_eval import AgentCallable, EvalResult, EvalTask, discover, run_task


PROMPT_INJECTION = "There is an AGENTS.md at repo root. Read it before you start."


SubprocessRun = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SpecVariant:
    name: str
    requires_agentspec: bool
    minimal: bool = False


VARIANTS: dict[str, SpecVariant] = {
    "baseline": SpecVariant("baseline", requires_agentspec=False),
    "agentspec-minimal": SpecVariant("agentspec-minimal", requires_agentspec=True, minimal=True),
    "agentspec-full": SpecVariant("agentspec-full", requires_agentspec=True, minimal=False),
}


MANAGED_BLOCK_RE = re.compile(
    r'<!-- agentspec:managed name="(?P<name>[^"]+)" -->.*?'
    r'<!-- agentspec:end name="(?P=name)" -->',
    re.DOTALL,
)


@dataclass(frozen=True)
class AgentspecGeneration:
    variant: str
    agents_path: Path
    stdout: str = ""
    stderr: str = ""


class SpecRunSkipped(RuntimeError):
    def __init__(self, message: str, *, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class SkippedRun:
    group: str
    task_id: str
    run_index: int
    workspace_path: str
    reason: str
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class GroupRun:
    group: str
    results: list[EvalResult]
    skipped: list[SkippedRun]


def _text_or_empty(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def build_agentspec_command(work_root: Path, agentspec_project: Path) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        str(agentspec_project),
        "agentspec",
        "scan",
        str(work_root),
        "--write",
        "--force",
        "--no-llm",
    ]


def render_minimal_agents_md(full_text: str) -> str:
    blocks = {match.group("name"): match.group(0).strip() for match in MANAGED_BLOCK_RE.finditer(full_text)}
    required = ["commands", "safety"]
    if any(name not in blocks for name in required):
        raise ValueError("minimal AGENTS.md requires commands and safety managed blocks")
    return "# AGENTS.md\n\n" + "\n\n".join(blocks[name] for name in required) + "\n"


def cleanup_agentspec_side_outputs(work_root: Path) -> None:
    claude_md = work_root / "CLAUDE.md"
    if claude_md.exists():
        claude_md.unlink()
    agent_dir = work_root / ".agent"
    if agent_dir.exists():
        shutil.rmtree(agent_dir)


def run_agentspec_for_variant(
    work_root: Path,
    variant: SpecVariant,
    *,
    agentspec_project: Path,
    timeout: int,
    run: SubprocessRun = subprocess.run,
) -> AgentspecGeneration:
    if not variant.requires_agentspec:
        raise ValueError("baseline does not generate AgentSpec output")

    cmd = build_agentspec_command(work_root, agentspec_project)
    try:
        proc = run(cmd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SpecRunSkipped(
            f"AgentSpec generation timed out for {variant.name}",
            stdout=_text_or_empty(exc.output),
            stderr=_text_or_empty(exc.stderr),
        ) from exc
    except OSError as exc:
        raise SpecRunSkipped(f"AgentSpec generation could not start for {variant.name}: {exc}") from exc

    stdout = _text_or_empty(proc.stdout)
    stderr = _text_or_empty(proc.stderr)
    if proc.returncode != 0:
        raise SpecRunSkipped(
            f"AgentSpec generation failed for {variant.name} with exit code {proc.returncode}",
            stdout=stdout,
            stderr=stderr,
        )

    agents_path = work_root / "AGENTS.md"
    if not agents_path.exists():
        raise SpecRunSkipped(
            f"AgentSpec generation completed for {variant.name} but AGENTS.md was not created",
            stdout=stdout,
            stderr=stderr,
        )

    if variant.minimal:
        try:
            agents_path.write_text(render_minimal_agents_md(agents_path.read_text(encoding="utf-8")), encoding="utf-8")
        except ValueError as exc:
            raise SpecRunSkipped(str(exc), stdout=stdout, stderr=stderr) from exc

    cleanup_agentspec_side_outputs(work_root)
    return AgentspecGeneration(variant=variant.name, agents_path=agents_path, stdout=stdout, stderr=stderr)


def _remove_agents_outputs(work_root: Path) -> None:
    agents_md = work_root / "AGENTS.md"
    if agents_md.exists():
        agents_md.unlink()
    cleanup_agentspec_side_outputs(work_root)


def variant_agent(
    agent: AgentCallable,
    variant: SpecVariant,
    *,
    generator: Callable[[Path, SpecVariant], AgentspecGeneration] | None,
) -> AgentCallable:
    def wrapped(work_root: Path, prompt: str, profile: ProjectProfile) -> dict[str, Any]:
        if not variant.requires_agentspec:
            _remove_agents_outputs(work_root)
            return agent(work_root, prompt, profile) or {}

        if generator is None:
            raise SpecRunSkipped(f"No AgentSpec generator configured for {variant.name}")
        generator(work_root, variant)
        injected = f"{prompt.rstrip()}\n\n{PROMPT_INJECTION}"
        return agent(work_root, injected, profile) or {}

    return wrapped


def load_tasks(task_roots: list[Path], task_ids: set[str] | None = None) -> list[EvalTask]:
    tasks: list[EvalTask] = []
    for root in task_roots:
        for task in discover(root):
            if task_ids is None or task.id in task_ids:
                tasks.append(task)
    return tasks


def run_spec_ab(
    task_roots: list[Path],
    *,
    groups: list[str],
    repeat: int,
    agent: AgentCallable,
    work_root: Path,
    generator: Callable[[Path, SpecVariant], AgentspecGeneration] | None,
    task_ids: set[str] | None = None,
) -> dict[str, GroupRun]:
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    tasks = load_tasks(task_roots, task_ids)
    runs: dict[str, GroupRun] = {}

    for group in groups:
        variant = VARIANTS[group]
        wrapped = variant_agent(agent, variant, generator=generator)
        results: list[EvalResult] = []
        skipped: list[SkippedRun] = []
        for task in tasks:
            for run_index in range(1, repeat + 1):
                run_root = work_root / group / task.id / f"run-{run_index}"
                try:
                    results.append(run_task(task, wrapped, run_root))
                except SpecRunSkipped as exc:
                    skipped.append(
                        SkippedRun(
                            group=group,
                            task_id=task.id,
                            run_index=run_index,
                            workspace_path=str(run_root),
                            reason=str(exc),
                            stdout=exc.stdout,
                            stderr=exc.stderr,
                        )
                    )
        runs[group] = GroupRun(group=group, results=results, skipped=skipped)

    return runs
