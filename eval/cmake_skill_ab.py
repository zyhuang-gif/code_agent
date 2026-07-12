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
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.run_eval import (
    AgentCallable,
    CommandRunner,
    EvalTask,
    default_command_runner,
    discover,
    run_task,
)
from eval.ts_bridge import typescript_agent_factory

from eval.cmake_skill_ab_report import build_cm02_report


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
    result_path: str
    verification_path: str
    diff_path: str


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
        "result_path": result.result_path,
        "verification_path": result.verification_path,
        "diff_path": result.diff_path,
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
# Agent builders
# ---------------------------------------------------------------------------

def _build_agent(
    variant: str,
    *,
    budget_steps: int,
    fake: bool,
    model_script: Path | None,
    output_dir: Path,
    run_root_parent: Path,
    cli_root: Path | None = None,
    timeout_seconds: int = AGENT_TIMEOUT_SECONDS,
    command_runner: Any = None,
) -> AgentCallable:
    """Build an AgentCallable for *variant*.

    control   -- real cli_root + empty extensions root (no invoke_skill)
    treatment -- real cli_root + workspace default extensions (cmake skill)
    """
    real_root = (cli_root or Path(__file__).resolve().parents[1]).resolve()
    use_fake = fake and model_script is None
    kwargs: dict[str, Any] = dict(
        budget_steps=budget_steps,
        fake=use_fake,
        model_script=model_script,
        cli_root=real_root,
        run_root_parent=run_root_parent,
        timeout_seconds=timeout_seconds,
        allow_unsafe_host_shell=False,
    )
    if command_runner is not None:
        kwargs["command_runner"] = command_runner
    if variant == "control":
        control_ext = output_dir / "_control_ext"
        if control_ext.exists():
            shutil.rmtree(control_ext)
        control_ext.mkdir(parents=True)
        return typescript_agent_factory(extensions_root=control_ext, **kwargs)
    if variant == "treatment":
        return typescript_agent_factory(extensions_root=None, **kwargs)
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
    command_runner: Any = None,
    cli_root: Path | None = None,
) -> list[CM02Result]:
    """Run paired A/B evaluation for CMake Skill.

    Each (task, repeat_index) pair runs both control and treatment variants
    with alternating AB/BA order.  Every run gets an independent workspace
    and session managed by the TS Bridge.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    run_root_parent = output_dir / "_runs"
    run_root_parent.mkdir(parents=True, exist_ok=True)
    work_root = output_dir / "_workspaces"

    results: list[CM02Result] = []

    for task in tasks:
        # Fake mode: each variant has a deterministic sidecar.
        # control -> model-script-control.json, treatment -> model-script.json
        if fake:
            control_sidecar = task.path / "model-script-control.json"
            treatment_sidecar = task.path / "model-script.json"
            sidecar_map: dict[str, Path] = {
                "control": control_sidecar,
                "treatment": treatment_sidecar,
            }
        else:
            sidecar_map = {}

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
                    # Fake mode: resolve sidecar per variant, fail closed if missing
                    model_script: Path | None = None
                    if fake:
                        sc = sidecar_map[variant_name]
                        if not sc.is_file():
                            raise FileNotFoundError(
                                f"Fake mode requires sidecar file: {sc}"
                            )
                        model_script = sc

                    task_agent = _build_agent(
                        variant_name,
                        budget_steps=budget_steps,
                        fake=fake,
                        model_script=model_script,
                        output_dir=output_dir,
                        run_root_parent=run_root_parent,
                        cli_root=cli_root,
                        command_runner=command_runner,
                    )
                    eval_result = run_task(task, task_agent, run_ws, command_runner=command_runner if command_runner is not None else default_command_runner)
                    latency_ms = int((time.time() - session_start) * 1000)

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
                            invoke_skill_count=0,
                            skill_selected_count=0,
                            skill_not_found_count=0,
                            bash_call_count=0,
                            infrastructure_error=eval_result.infrastructure_error,
                            trace_path=eval_result.trace_path,
                            result_path=eval_result.result_path,
                            verification_path=eval_result.verification_path,
                            diff_path=eval_result.diff_path,
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
                            result_path="",
                            verification_path="",
                            diff_path="",
                        )
                    )

    return results


# ---------------------------------------------------------------------------
# Pilot gate validation (CM-02 spec section 7)
# ---------------------------------------------------------------------------

def _validate_pilot_gate(summary_path: Path) -> None:
    """Validate pilot gate criteria from cm02-summary.json.

    Gate criteria:
      - r08 treatment: at least 2 of *repeat* runs have selected > 0
      - r08 control: all runs have selected == 0
      - Both variants: bash_call_count == 0 for all runs

    Prints a reason and raises SystemExit(2) if the gate is not passed.
    """
    if not summary_path.is_file():
        print(
            f"Pilot summary not found: {summary_path}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"Cannot parse pilot summary {summary_path}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    results = summary.get("results", [])
    if not isinstance(results, list):
        print(
            f"Pilot summary {summary_path} has no results array",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Filter to r08
    r08 = [r for r in results if r.get("task_id") == PILOT_TASK_ID]
    if not r08:
        print(
            f"Pilot summary {summary_path} contains no results for "
            f"{PILOT_TASK_ID}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    treatment_runs = [
        r for r in r08 if r.get("variant") == "treatment"
    ]
    control_runs = [r for r in r08 if r.get("variant") == "control"]

    # Gate 1: treatment repeat -- at least 2 runs with skill_selected > 0
    t_selected = sum(
        1 for r in treatment_runs
        if r.get("skill_selected_count", 0) > 0
    )
    if t_selected < 2:
        print(
            "Pilot gate NOT passed: treatment variant for r08 had "
            f"{t_selected} repeat(s) with skill_selected > 0 "
            "(need >= 2)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Gate 2: control -- all runs have skill_selected == 0
    c_selected_any = sum(
        1 for r in control_runs
        if r.get("skill_selected_count", 0) != 0
    )
    if c_selected_any > 0:
        print(
            "Pilot gate NOT passed: control variant for r08 had "
            f"{c_selected_any} run(s) with skill_selected != 0 "
            "(need 0)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Gate 3: bash_call_count == 0 for ALL r08 runs
    bash_nonzero = [
        r for r in r08 if r.get("bash_call_count", 0) != 0
    ]
    if bash_nonzero:
        print(
            "Pilot gate NOT passed: r08 had "
            f"{len(bash_nonzero)} run(s) with bash calls != 0 "
            "(need 0)",
            file=sys.stderr,
        )
        raise SystemExit(2)


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

    # Pilot real run (requires API key + consent)
    python eval/cmake_skill_ab.py --phase pilot --external-consent pilot

    # Full real run (requires API key + consent + pilot summary)
    python eval/cmake_skill_ab.py --phase full --repeat 3 --budget-steps 60
        --external-consent full --pilot-summary eval/output/cm02/cm02-summary.json
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
    parser.add_argument(
        "--external-consent",
        choices=("pilot", "full"),
        default=None,
        help="Real-run consent gate: must match --phase. "
        "Not required with --fake.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="fake",
        help="Model identifier for report metadata (default: fake)",
    )
    parser.add_argument(
        "--pilot-summary",
        type=Path,
        default=None,
        help="Path to cm02-summary.json from a prior pilot run. "
        "Required with --external-consent full.",
    )
    args = parser.parse_args(argv)

    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if args.budget_steps < 1:
        parser.error("--budget-steps must be >= 1")

    # ---- Real fail-closed consent gate ----
    if not args.fake:
        if args.external_consent is None:
            print(
                "Non-fake runs require --external-consent (pilot or full).",
                file=sys.stderr,
            )
            return 2
        if args.external_consent != args.phase:
            print(
                f"--external-consent ({args.external_consent}) "
                f"must match --phase ({args.phase}).",
                file=sys.stderr,
            )
            return 2

        # API key check
        if not (
            os.environ.get("CODE_AGENT_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
        ):
            print(
                "CODE_AGENT_API_KEY or DEEPSEEK_API_KEY is required "
                "for real eval runs",
                file=sys.stderr,
            )
            return 2

        # Full mode extra: pilot-summary required
        if args.phase == "full":
            if args.pilot_summary is None:
                print(
                    "--external-consent full requires --pilot-summary PATH",
                    file=sys.stderr,
                )
                return 2
            _validate_pilot_gate(args.pilot_summary.resolve())

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
    if not args.fake:
        print(f"External consent: {args.external_consent}")
    print(f"Output: {output_dir}")

    results = run_cmake_skill_ab(
        tasks,
        repeat=args.repeat,
        budget_steps=args.budget_steps,
        output_dir=output_dir,
        fake=args.fake,
    )

    result_dicts = [_cm02_result_to_dict(r) for r in results]
    json_path, report_path = build_cm02_report(
        result_dicts,
        phase=args.phase,
        model=args.model,
        repeat=args.repeat,
        output_dir=output_dir,
    )
    print(f"Summary JSON: {json_path}")
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
