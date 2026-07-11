"""CMake Skill paired A/B evaluation orchestrator (CM-02).

Implements paired A/B orchestration for evaluating the CMake build-fix skill.
Control uses an empty extensions root (no invoke_skill tool in the catalog).
Treatment uses the workspace extensions directory (cmake skill available).

AB/BA alternation: repeat 0 -> A(control) then B(treatment),
repeat 1 -> B(treatment) then A(control), and so on.

Reuses run_eval discovery, run_task, verify.py, workspace isolation, and
the TS Bridge.  Does NOT duplicate run_eval execution logic or reimplement
verify.py subprocess calls.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.run_eval import (
    AgentCallable,
    EvalTask,
    discover,
    run_task,
)
from eval.ts_bridge import TsBridgeError, typescript_agent_factory


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASKS_CMAKE_REAL_DIR = "tasks_cmake_real"
PILOT_TASK_ID = "r08_local_library_source_omitted"
FULL_TASK_COUNT = 10

AGENT_TIMEOUT_SECONDS = 3600


# ---------------------------------------------------------------------------
# CM02 Result
# ---------------------------------------------------------------------------

@dataclass
class CM02Result:
    """A single paired A/B run result (schema v1)."""

    task_id: str
    repeat_index: int
    variant: str  # "control" | "treatment"
    order_index: int  # 0 or 1 within the pair
    session_id: str
    solved: bool
    reason: str
    steps: int
    latency_ms: int
    cost_usd: float
    token_usage: dict[str, int]
    invoke_skill_count: int
    skill_selected_count: int
    skill_not_found_count: int
    bash_call_count: int
    infrastructure_error: dict[str, str] | None
    trace_path: str


def _cm02_result_to_dict(result: CM02Result) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "repeat_index": result.repeat_index,
        "variant": result.variant,
        "order_index": result.order_index,
        "session_id": result.session_id,
        "solved": result.solved,
        "reason": result.reason,
        "steps": result.steps,
        "latency_ms": result.latency_ms,
        "cost_usd": result.cost_usd,
        "token_usage": result.token_usage,
        "invoke_skill_count": result.invoke_skill_count,
        "skill_selected_count": result.skill_selected_count,
        "skill_not_found_count": result.skill_not_found_count,
        "bash_call_count": result.bash_call_count,
        "infrastructure_error": result.infrastructure_error,
        "trace_path": result.trace_path,
    }


# ---------------------------------------------------------------------------
# Task discovery
# ---------------------------------------------------------------------------

def discover_cmake_tasks(eval_dir: Path, phase: str) -> list[EvalTask]:
    """Discover tasks based on phase.

    pilot -- r08_local_library_source_omitted only
    full  -- all 10 tasks from tasks_cmake_real
    """
    tasks_dir = eval_dir / TASKS_CMAKE_REAL_DIR
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"Tasks directory not found: {tasks_dir}")
    all_tasks = discover(tasks_dir)
    if phase == "pilot":
        filtered = [t for t in all_tasks if t.id == PILOT_TASK_ID]
        if not filtered:
            raise FileNotFoundError(
                f"Pilot task {PILOT_TASK_ID!r} not found in {tasks_dir}"
            )
        return filtered
    if phase == "full":
        if len(all_tasks) != FULL_TASK_COUNT:
            raise RuntimeError(
                f"Expected {FULL_TASK_COUNT} tasks in {tasks_dir}, "
                f"found {len(all_tasks)}"
            )
        return all_tasks
    raise ValueError(f"Unknown phase: {phase!r}")


# ---------------------------------------------------------------------------
# Control variant -- empty extensions root
# ---------------------------------------------------------------------------

def _create_control_root(real_root: Path, staging: Path) -> Path:
    """Create a staging root with an empty extensions/ directory and junctions
    to the real node_modules/ and src/ directories.

    The TS CLI requires node_modules/tsx/dist/cli.mjs and src/cli.ts under
    the root.  With an empty extensions/ directory, loadExtensions returns []
    and the invoke_skill tool is never registered, ensuring the control
    variant has no access to the cmake build-fix skill.
    """
    control_root = staging / "control-root"
    control_root.mkdir(parents=True, exist_ok=True)

    # Empty extensions directory -- no skills, no tools
    (control_root / "extensions").mkdir(exist_ok=True)

    # Create junctions for directories the TS CLI requires at runtime
    for subdir in ["node_modules", "src"]:
        src = real_root / subdir
        dst = control_root / subdir
        if dst.exists():
            continue
        if not src.is_dir():
            raise TsBridgeError(
                "cli_not_found",
                f"Required directory not found for control root: {src}",
            )
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                # Junction may already exist in a broken state; remove and retry
                subprocess.run(
                    ["cmd", "/c", "rmdir", str(dst)],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    raise TsBridgeError(
                        "cli_not_found",
                        f"Failed to create junction {dst} -> {src}: "
                        f"{result.stderr.strip()}",
                    )
        else:
            os.symlink(str(src), str(dst), target_is_directory=True)

    return control_root


# ---------------------------------------------------------------------------
# Trace analysis
# ---------------------------------------------------------------------------

def _parse_trace_metrics(trace_path: str) -> dict[str, int]:
    """Parse a trace JSONL file to extract skill- and bash-invocation counts.

    Returns a dict with keys:
      invoke_skill_count, skill_selected_count, skill_not_found_count,
      bash_call_count.
    """
    metrics = {
        "invoke_skill_count": 0,
        "skill_selected_count": 0,
        "skill_not_found_count": 0,
        "bash_call_count": 0,
    }
    tp = Path(trace_path)
    if not tp.is_file():
        return metrics

    try:
        with open(tp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    continue

                # skill_selection events are produced by the
                # registerSkillSelectionTraceProjection hook for every
                # invoke_skill tool call (both success and failure).
                if etype == "skill_selection":
                    metrics["invoke_skill_count"] += 1
                    outcome = payload.get("outcome", "")
                    if outcome == "selected":
                        metrics["skill_selected_count"] += 1
                    elif outcome == "not_found":
                        metrics["skill_not_found_count"] += 1

                # Count bash invocations from tool_end events.
                if etype == "tool_end":
                    invocation = payload.get("invocation", {})
                    if (
                        isinstance(invocation, dict)
                        and invocation.get("name") == "bash"
                    ):
                        metrics["bash_call_count"] += 1

    except OSError:
        pass

    return metrics


# ---------------------------------------------------------------------------
# Agent builders
# ---------------------------------------------------------------------------

def _build_agent(
    variant: str,
    *,
    budget_steps: int,
    fake: bool,
    model_script: Path | None,
    control_root: Path,
    run_root_parent: Path,
    timeout_seconds: int = AGENT_TIMEOUT_SECONDS,
) -> AgentCallable:
    """Build an AgentCallable for *variant*.

    control   -- empty extensions root (no invoke_skill in tool catalog)
    treatment -- default workspace extensions (cmake build-fix skill available)
    """
    use_fake = fake and model_script is None
    if variant == "control":
        return typescript_agent_factory(
            budget_steps=budget_steps,
            fake=use_fake,
            model_script=model_script,
            cli_root=control_root,
            run_root_parent=run_root_parent,
            timeout_seconds=timeout_seconds,
            allow_unsafe_host_shell=False,
        )
    if variant == "treatment":
        return typescript_agent_factory(
            budget_steps=budget_steps,
            fake=use_fake,
            model_script=model_script,
            run_root_parent=run_root_parent,
            timeout_seconds=timeout_seconds,
            allow_unsafe_host_shell=False,
        )
    raise ValueError(f"Unknown variant: {variant!r}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_cmake_skill_ab(
    tasks: list[EvalTask],
    *,
    repeat: int,
    budget_steps: int,
    output_dir: Path,
    fake: bool,
) -> list[CM02Result]:
    """Run paired A/B evaluation for CMake Skill.

    Each (task, repeat_index) pair runs both control and treatment variants
    with alternating AB/BA order.  Every run gets an independent workspace
    and session managed by the TS Bridge.
    """
    real_root = Path(__file__).resolve().parents[1]
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prepare control root once (empty extensions + junctions to src & node_modules)
    staging = output_dir / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    control_root = _create_control_root(real_root, staging)

    run_root_parent = output_dir / "_runs"
    run_root_parent.mkdir(parents=True, exist_ok=True)
    work_root = output_dir / "_workspaces"

    results: list[CM02Result] = []

    for task in tasks:
        model_script_path = task.path / "model-script.json"
        has_model_script = model_script_path.is_file()

        for repeat_idx in range(repeat):
            # AB/BA alternation
            first, second = (
                ("control", "treatment")
                if repeat_idx % 2 == 0
                else ("treatment", "control")
            )

            for order_idx, variant_name in enumerate([first, second]):
                session_start = time.time()
                run_ws = work_root / task.id / variant_name / f"repeat-{repeat_idx}"

                try:
                    task_agent = _build_agent(
                        variant_name,
                        budget_steps=budget_steps,
                        fake=fake,
                        model_script=(
                            model_script_path if has_model_script else None
                        ),
                        control_root=control_root,
                        run_root_parent=run_root_parent,
                    )
                    eval_result = run_task(task, task_agent, run_ws)
                    latency_ms = int((time.time() - session_start) * 1000)

                    tp = eval_result.trace_path
                    trace_metrics = (
                        _parse_trace_metrics(tp) if tp else {}
                    )

                    results.append(
                        CM02Result(
                            task_id=task.id,
                            repeat_index=repeat_idx,
                            variant=variant_name,
                            order_index=order_idx,
                            session_id=eval_result.session_id,
                            solved=eval_result.status == "solved",
                            reason=eval_result.reason,
                            steps=eval_result.steps,
                            latency_ms=latency_ms,
                            cost_usd=eval_result.cost_usd,
                            token_usage=eval_result.usage,
                            invoke_skill_count=trace_metrics.get(
                                "invoke_skill_count", 0
                            ),
                            skill_selected_count=trace_metrics.get(
                                "skill_selected_count", 0
                            ),
                            skill_not_found_count=trace_metrics.get(
                                "skill_not_found_count", 0
                            ),
                            bash_call_count=trace_metrics.get(
                                "bash_call_count", 0
                            ),
                            infrastructure_error=eval_result.infrastructure_error,
                            trace_path=eval_result.trace_path,
                        )
                    )
                except Exception as exc:
                    latency_ms = int((time.time() - session_start) * 1000)
                    error_code = getattr(exc, "code", "unhandled_exception")
                    results.append(
                        CM02Result(
                            task_id=task.id,
                            repeat_index=repeat_idx,
                            variant=variant_name,
                            order_index=order_idx,
                            session_id="",
                            solved=False,
                            reason="infrastructure_error",
                            steps=0,
                            latency_ms=latency_ms,
                            cost_usd=0.0,
                            token_usage={},
                            invoke_skill_count=0,
                            skill_selected_count=0,
                            skill_not_found_count=0,
                            bash_call_count=0,
                            infrastructure_error={
                                "code": str(error_code),
                                "type": type(exc).__name__,
                                "message": str(exc)[:2000],
                            },
                            trace_path="",
                        )
                    )

    return results


# ---------------------------------------------------------------------------
# JSON summary output
# ---------------------------------------------------------------------------

def _variant_stats(variant_results: list[CM02Result]) -> dict[str, Any]:
    total = len(variant_results)
    if total == 0:
        return {"total": 0, "solved": 0, "solution_rate": 0.0}
    solved = sum(1 for r in variant_results if r.solved)
    errors = sum(
        1 for r in variant_results if r.infrastructure_error is not None
    )
    steps = [r.steps for r in variant_results]
    latencies = [r.latency_ms for r in variant_results]
    costs = [r.cost_usd for r in variant_results]
    invoke = [r.invoke_skill_count for r in variant_results]
    selected = [r.skill_selected_count for r in variant_results]
    not_found = [r.skill_not_found_count for r in variant_results]
    bash = [r.bash_call_count for r in variant_results]
    return {
        "total": total,
        "solved": solved,
        "solution_rate": solved / total,
        "infrastructure_errors": errors,
        "avg_steps": statistics.mean(steps) if steps else 0.0,
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "avg_cost_usd": statistics.mean(costs) if costs else 0.0,
        "avg_invoke_skill_count": (
            statistics.mean(invoke) if invoke else 0.0
        ),
        "avg_skill_selected_count": (
            statistics.mean(selected) if selected else 0.0
        ),
        "avg_skill_not_found_count": (
            statistics.mean(not_found) if not_found else 0.0
        ),
        "avg_bash_call_count": statistics.mean(bash) if bash else 0.0,
    }


def write_summary_json(results: list[CM02Result], output_dir: Path) -> Path:
    """Write cm02-summary.json (schema v1)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "cm02-summary.json"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "evaluation": "cmake-skill-ab",
                "control": _variant_stats(
                    [r for r in results if r.variant == "control"]
                ),
                "treatment": _variant_stats(
                    [r for r in results if r.variant == "treatment"]
                ),
                "results": [_cm02_result_to_dict(r) for r in results],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return json_path


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def write_markdown_report(
    results: list[CM02Result],
    phase: str,
    repeat: int,
    budget_steps: int,
    fake: bool,
    output_dir: Path,
) -> Path:
    """Write cm02-report.md.

    The report deliberately omits source code, prompt content, tool result
    content, absolute paths, and secrets.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    control = [r for r in results if r.variant == "control"]
    treatment = [r for r in results if r.variant == "treatment"]

    cs = _variant_stats(control)
    ts = _variant_stats(treatment)

    def _delta(ctrl_val: float, treat_val: float) -> str:
        d = treat_val - ctrl_val
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.3f}"

    lines = [
        "# CM-02 CMake Skill A/B Evaluation Report",
        "",
        f"- **Phase**: {phase}",
        f"- **Repeat**: {repeat}",
        f"- **Budget steps**: {budget_steps}",
        f"- **Mode**: {'fake' if fake else 'real'}",
        "- **Control**: empty extensions root (no invoke_skill tool)",
        "- **Treatment**: workspace extensions (cmake build-fix skill)",
        "",
        "## Summary",
        "",
        "| Metric | Control | Treatment | Delta |",
        "|---|---:|---:|---:|",
        f"| Solution Rate | {cs['solution_rate']:.3f} | {ts['solution_rate']:.3f} | {_delta(cs['solution_rate'], ts['solution_rate'])} |",
        f"| Solved / Total | {cs['solved']}/{cs['total']} | {ts['solved']}/{ts['total']} | |",
        f"| Infrastructure Errors | {cs['infrastructure_errors']} | {ts['infrastructure_errors']} | |",
        f"| Avg Steps | {cs['avg_steps']:.1f} | {ts['avg_steps']:.1f} | {_delta(cs['avg_steps'], ts['avg_steps'])} |",
        f"| Avg Latency (ms) | {cs['avg_latency_ms']:.0f} | {ts['avg_latency_ms']:.0f} | |",
        f"| Avg Cost (USD) | {cs['avg_cost_usd']:.4f} | {ts['avg_cost_usd']:.4f} | |",
        f"| Avg invoke_skill Calls | {cs['avg_invoke_skill_count']:.1f} | {ts['avg_invoke_skill_count']:.1f} | |",
        f"| Avg Skill Selected | {cs['avg_skill_selected_count']:.1f} | {ts['avg_skill_selected_count']:.1f} | |",
        f"| Avg Skill Not Found | {cs['avg_skill_not_found_count']:.1f} | {ts['avg_skill_not_found_count']:.1f} | |",
        f"| Avg Bash Calls | {cs['avg_bash_call_count']:.1f} | {ts['avg_bash_call_count']:.1f} | |",
        "",
    ]

    # Per-task breakdown
    task_ids = sorted({r.task_id for r in results})
    lines.extend(["## Per-Task Results", ""])
    for tid in task_ids:
        lines.append(f"### {tid}")
        lines.append("")
        lines.append(
            "| Repeat | Variant | Order | Solved | Steps | "
            "Latency (ms) | Cost (USD) | invoke_skill | "
            "selected | not_found | bash |"
        )
        lines.append(
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
        )
        task_runs = sorted(
            [r for r in results if r.task_id == tid],
            key=lambda r: (r.repeat_index, r.order_index),
        )
        for r in task_runs:
            lines.append(
                f"| {r.repeat_index} | {r.variant} | {r.order_index} | "
                f"{'yes' if r.solved else 'no'} | {r.steps} | "
                f"{r.latency_ms} | {r.cost_usd:.4f} | "
                f"{r.invoke_skill_count} | {r.skill_selected_count} | "
                f"{r.skill_not_found_count} | {r.bash_call_count} |"
            )
        lines.append("")

    # Infrastructure errors
    errors = [r for r in results if r.infrastructure_error is not None]
    if errors:
        lines.extend(["## Infrastructure Errors", ""])
        for r in errors:
            ie = r.infrastructure_error
            msg = (ie.get("message", "") or "")[:200]
            lines.append(
                f"- **{r.task_id}** repeat={r.repeat_index} "
                f"variant={r.variant}: "
                f"`{ie.get('type', '')}` code={ie.get('code', '')}"
                f"{': ' + msg if msg else ''}"
            )
        lines.append("")

    # Noise warning
    lines.extend(
        [
            "## Notes",
            "",
            "LLM evals are inherently noisy. Never draw conclusions from a "
            "single solution rate. Use mean +/- std across repeated runs and "
            "inspect traces for qualitative differences.",
            "",
        ]
    )

    report_path = output_dir / "cm02-report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Entry point for CM-02 CMake Skill paired A/B evaluation.

    Examples
    --------
    # Pilot fake smoke test (r08 only, 1 repeat)
    python eval/cmake_skill_ab.py --phase pilot --fake

    # Full fake run with 3 repeats
    python eval/cmake_skill_ab.py --phase full --repeat 3 --fake

    # Full real run (requires API key)
    python eval/cmake_skill_ab.py --phase full --repeat 3 --budget-steps 60
    """
    parser = argparse.ArgumentParser(
        description="CM-02: CMake Skill paired A/B evaluation orchestrator",
    )
    parser.add_argument(
        "--phase",
        choices=("pilot", "full"),
        default="pilot",
        help="pilot: r08 only; full: all 10 tasks (default: pilot)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of repeat runs per variant per task (default: 1)",
    )
    parser.add_argument(
        "--budget-steps",
        type=int,
        default=40,
        help="Maximum agent steps per run (default: 40)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for results and workspaces "
        "(default: eval/output/cm02)",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Run in fake mode using model-script.json or default fake finish",
    )
    args = parser.parse_args(argv)

    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if args.budget_steps < 1:
        parser.error("--budget-steps must be >= 1")

    if not args.fake and not (
        os.environ.get("CODE_AGENT_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
    ):
        print(
            "CODE_AGENT_API_KEY or DEEPSEEK_API_KEY is required "
            "for real eval runs",
            file=sys.stderr,
        )
        return 2

    eval_dir = Path(__file__).resolve().parent
    try:
        tasks = discover_cmake_tasks(eval_dir, args.phase)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not tasks:
        print(
            f"No tasks found for phase {args.phase!r}", file=sys.stderr
        )
        return 2

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (eval_dir / "output" / "cm02").resolve()
    )

    print(
        f"Phase: {args.phase}  Tasks: {len(tasks)}  Repeat: {args.repeat}  "
        f"Budget: {args.budget_steps}  Fake: {args.fake}"
    )
    print(f"Output: {output_dir}")

    results = run_cmake_skill_ab(
        tasks,
        repeat=args.repeat,
        budget_steps=args.budget_steps,
        output_dir=output_dir,
        fake=args.fake,
    )

    json_path = write_summary_json(results, output_dir)
    print(f"Summary JSON: {json_path}")

    report_path = write_markdown_report(
        results,
        phase=args.phase,
        repeat=args.repeat,
        budget_steps=args.budget_steps,
        fake=args.fake,
        output_dir=output_dir,
    )
    print(f"Report: {report_path}")

    # Quick summary
    control_results = [r for r in results if r.variant == "control"]
    treatment_results = [r for r in results if r.variant == "treatment"]
    c_solved = sum(1 for r in control_results if r.solved)
    t_solved = sum(1 for r in treatment_results if r.solved)
    c_total = len(control_results)
    t_total = len(treatment_results)
    if c_total:
        print(f"\nControl:   {c_solved}/{c_total} solved ({c_solved / c_total:.1%})")
    else:
        print("\nControl:   0 runs")
    if t_total:
        print(f"Treatment: {t_solved}/{t_total} solved ({t_solved / t_total:.1%})")
    else:
        print("Treatment: 0 runs")

    infrastructure_errors = sum(
        1 for r in results if r.infrastructure_error is not None
    )
    if infrastructure_errors:
        print(f"\nInfrastructure errors: {infrastructure_errors}")
        return 2

    return 0 if all(
        r.solved or r.infrastructure_error is not None for r in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
