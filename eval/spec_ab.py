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


import statistics
from typing import Iterable

from eval.run_eval import summarize


def _mean_std(values: Iterable[float]) -> dict[str, float]:
    vals = list(values)
    if not vals:
        return {"mean": 0.0, "std": 0.0}
    return {"mean": statistics.mean(vals), "std": statistics.pstdev(vals)}


def _result_to_dict(result: EvalResult) -> dict[str, object]:
    return {
        "task_id": result.task_id,
        "status": result.status,
        "steps": result.steps,
        "cost_usd": result.cost_usd,
        "reason": result.reason,
        "trace_path": result.trace_path,
        "report_path": result.report_path,
        "diff_path": result.diff_path,
        "workspace_path": result.workspace_path,
        "verify_output": result.verify_output,
    }


def _task_summary(task_id: str, results: list[EvalResult], skipped: list[SkippedRun]) -> dict[str, object]:
    solved_flags = [1.0 if result.status == "solved" else 0.0 for result in results]
    return {
        "task_id": task_id,
        "runs": len(results),
        "skipped": len(skipped),
        "pass_rate": _mean_std(solved_flags),
        "steps": _mean_std(float(result.steps) for result in results),
        "cost_usd": _mean_std(float(result.cost_usd) for result in results),
        "results": [_result_to_dict(result) for result in results],
        "skips": [asdict(skip) for skip in skipped],
    }


def summarize_groups(runs: dict[str, GroupRun]) -> dict[str, object]:
    groups: dict[str, object] = {}
    for group, group_run in runs.items():
        results = group_run.results
        skipped = group_run.skipped
        task_ids = sorted({result.task_id for result in results} | {skip.task_id for skip in skipped})
        tasks = {}
        for task_id in task_ids:
            task_results = [result for result in results if result.task_id == task_id]
            task_skips = [skip for skip in skipped if skip.task_id == task_id]
            tasks[task_id] = _task_summary(task_id, task_results, task_skips)

        solved_flags = [1.0 if result.status == "solved" else 0.0 for result in results]
        trace_samples = [result.trace_path for result in results if result.trace_path][:1]
        groups[group] = {
            "base_summary": summarize(results),
            "metrics": {
                "pass_rate": _mean_std(solved_flags),
                "steps": _mean_std(float(result.steps) for result in results),
                "cost_usd": _mean_std(float(result.cost_usd) for result in results),
            },
            "tasks": tasks,
            "skipped_runs": len(skipped),
            "skips": [asdict(skip) for skip in skipped],
            "trace_samples": trace_samples,
        }

    return {
        "noise_warning": "LLM evals are noisy: never draw conclusions from a single solution_rate. Use mean±std and inspect traces.",
        "groups": groups,
    }


def _metric_cell(metric: dict[str, float]) -> str:
    return f"{metric['mean']:.3f}±{metric['std']:.3f}"


def render_markdown_report(summary: dict[str, object]) -> str:
    lines = [
        "# AgentSpec A/B Evaluation Report",
        "",
        str(summary["noise_warning"]),
        "",
        "## Group Summary",
        "",
        "| Group | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped | Trace Sample |",
        "|---|---:|---:|---:|---:|---|",
    ]
    groups = summary["groups"]
    for group_name, group_data in groups.items():
        metrics = group_data["metrics"]
        trace = ", ".join(group_data["trace_samples"]) or ""
        lines.append(
            f"| {group_name} | {_metric_cell(metrics['pass_rate'])} | "
            f"{_metric_cell(metrics['steps'])} | {_metric_cell(metrics['cost_usd'])} | "
            f"{group_data['skipped_runs']} | {trace} |"
        )

    lines.extend(["", "## Per Task", ""])
    for group_name, group_data in groups.items():
        lines.extend([f"### {group_name}", ""])
        lines.append("| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for task_id, task_data in group_data["tasks"].items():
            lines.append(
                f"| {task_id} | {task_data['runs']} | {_metric_cell(task_data['pass_rate'])} | "
                f"{_metric_cell(task_data['steps'])} | {_metric_cell(task_data['cost_usd'])} | "
                f"{task_data['skipped']} |"
            )
        lines.append("")

    lines.extend(["## Skipped Runs", ""])
    any_skip = False
    for group_name, group_data in groups.items():
        for skip in group_data["skips"]:
            any_skip = True
            lines.append(
                f"- {group_name}/{skip['task_id']}/run-{skip['run_index']}: {skip['reason']} "
                f"workspace={skip['workspace_path']}"
            )
    if not any_skip:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


import argparse
import json
import os
import sys

from eval.run_eval import fake_agent, multi_agent_factory, real_agent_factory


def default_task_roots(eval_dir: Path | None = None) -> list[Path]:
    root = eval_dir or Path(__file__).resolve().parent
    return [root / "tasks_real", root / "tasks_swebench"]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AgentSpec A/B/C evals on code_agent tasks.")
    parser.add_argument("--tasks", type=Path, action="append", default=None)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--groups", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--multi", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--work-root", type=Path, default=Path("workspace") / "spec-ab")
    parser.add_argument("--agentspec-project", type=Path, default=Path(os.environ.get("AGENTSPEC_PROJECT", "D:/source/agent/agentspec")))
    parser.add_argument("--agentspec-timeout", type=int, default=120)
    parser.add_argument("--json-summary", type=Path)
    parser.add_argument("--markdown-report", type=Path)
    return parser.parse_args(argv)


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main(
    argv: list[str] | None = None,
    *,
    agent_factory: Callable[[], AgentCallable] | None = None,
    work_root: Path | None = None,
    generator: Callable[[Path, SpecVariant], AgentspecGeneration] | None = None,
) -> int:
    args = _parse_args(argv)
    if args.repeat < 1:
        print("--repeat must be >= 1", file=sys.stderr)
        return 2

    task_roots = args.tasks or default_task_roots()
    selected_task_ids = set(args.task_id) if args.task_id else None

    if args.fake:
        agent = fake_agent
    else:
        if agent_factory is None and not os.environ.get("DEEPSEEK_API_KEY"):
            print("DEEPSEEK_API_KEY is required for non-fake spec_ab runs", file=sys.stderr)
            return 2
        factory = agent_factory or (multi_agent_factory if args.multi else real_agent_factory)
        agent = factory()

    def default_generator(workspace: Path, variant: SpecVariant) -> AgentspecGeneration:
        return run_agentspec_for_variant(
            workspace,
            variant,
            agentspec_project=args.agentspec_project,
            timeout=args.agentspec_timeout,
        )

    runs = run_spec_ab(
        task_roots,
        groups=args.groups,
        repeat=args.repeat,
        agent=agent,
        work_root=work_root or args.work_root,
        generator=generator or default_generator,
        task_ids=selected_task_ids,
    )
    summary = summarize_groups(runs)
    markdown = render_markdown_report(summary)

    if args.json_summary:
        args.json_summary.parent.mkdir(parents=True, exist_ok=True)
        args.json_summary.write_text(json.dumps(summary, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
    if args.markdown_report:
        args.markdown_report.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_report.write_text(markdown, encoding="utf-8")

    print(markdown)
    any_failed = any(
        result.status != "solved"
        for group_run in runs.values()
        for result in group_run.results
    )
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
