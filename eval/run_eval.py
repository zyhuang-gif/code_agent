"""Evaluation harness for fixed tasks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.profile import ProjectProfile, load_profile


AgentCallable = Callable[[Path, str, ProjectProfile], dict[str, Any]]
CommandRunner = Callable[..., dict[str, Any]]


@dataclass
class EvalTask:
    id: str
    path: Path
    profile: ProjectProfile


@dataclass
class EvalResult:
    task_id: str
    status: str
    steps: int
    cost_usd: float
    reason: str = ""
    trace_path: str = ""
    report_path: str = ""
    diff_path: str = ""
    workspace_path: str = ""
    verify_output: str = ""



def _retry_readonly_remove(func: Callable[[str], None], path: str, exc: BaseException) -> None:
    if not isinstance(exc, PermissionError):
        raise exc
    os.chmod(path, stat.S_IWRITE)
    func(path)


def robust_rmtree(path: Path) -> None:
    shutil.rmtree(path, onexc=_retry_readonly_remove)


def default_command_runner(cmd: str, cwd: Path | None = None, timeout: int | None = None, allow_network: bool = False) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True, timeout=timeout)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def run_task(task: EvalTask, agent: AgentCallable, work_root: Path, command_runner: CommandRunner = default_command_runner) -> EvalResult:
    task_path = task.path.resolve()
    if work_root.exists():
        robust_rmtree(work_root)
    local_repo = task_path / "repo"
    if local_repo.is_dir():
        shutil.copytree(str(local_repo), str(work_root))
    else:
        # Fallback: shallow clone from task.json metadata
        task_json = task_path / "task.json"
        if not task_json.exists():
            raise FileNotFoundError(f"No repo/ and no task.json in {task_path}")
        meta = json.loads(task_json.read_text(encoding="utf-8"))
        url = f"https://github.com/{meta['repo']}.git"
        subprocess.run(["git", "init", str(work_root)], check=True, capture_output=True, timeout=60)
        subprocess.run(["git", "-C", str(work_root), "remote", "add", "origin", url], check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "-C", str(work_root), "fetch", "--depth", "1", "origin", meta["base_commit"]], check=True, capture_output=True, timeout=300)
        subprocess.run(["git", "-C", str(work_root), "checkout", "FETCH_HEAD"], check=True, capture_output=True, timeout=60)
    if task.profile.setup_cmd:
        setup = command_runner(
            task.profile.setup_cmd,
            cwd=work_root,
            timeout=task.profile.setup_timeout,
            allow_network=task.profile.setup_needs_network,
        )
        if int(setup.get("exit_code", 1)) != 0:
            output = f"{setup.get('stdout', '')}{setup.get('stderr', '')}"
            raise RuntimeError(f"setup_cmd failed for {task.id}: {output}")
    prompt = (task_path / "prompt.md").read_text(encoding="utf-8")
    meta = agent(work_root, prompt, task.profile) or {}
    verify = task_path / "verify.py"
    proc = subprocess.run(
        [sys.executable, "-c", verify.read_text(encoding="utf-8").lstrip("\ufeff")],
        cwd=work_root,
        text=True,
        capture_output=True,
        timeout=task.profile.test_timeout,
    )
    verify_output = f"{proc.stdout}{proc.stderr}"
    trace_path = work_root.parent / f"{work_root.name}.trace.jsonl"
    report_path = work_root / "fix_report.md"
    diff_path = work_root / "final.diff"
    return EvalResult(
        task.id,
        "solved" if proc.returncode == 0 else "failed",
        int(meta.get("steps", 0)),
        float(meta.get("cost_usd", 0.0)),
        str(meta.get("reason", "")),
        str(trace_path) if trace_path.exists() else "",
        str(report_path) if report_path.exists() else "",
        str(diff_path) if diff_path.exists() else "",
        str(work_root),
        verify_output[:4000],
    )


def summarize(results: list[EvalResult]) -> dict[str, Any]:
    total = len(results)
    solved = sum(1 for result in results if result.status == "solved")
    by_task: dict[str, list[EvalResult]] = {}
    for result in results:
        by_task.setdefault(getattr(result, "task_id", "__all__"), []).append(result)

    task_summaries = {}
    for task_id, task_results in by_task.items():
        task_total = len(task_results)
        task_solved = sum(1 for result in task_results if result.status == "solved")
        task_summaries[task_id] = {
            "runs": task_total,
            "solved": task_solved,
            "pass_rate": task_solved / task_total if task_total else 0.0,
            "avg_steps": sum(result.steps for result in task_results) / task_total if task_total else 0.0,
            "avg_cost_usd": sum(result.cost_usd for result in task_results) / task_total if task_total else 0.0,
            "results": [
                {
                    "status": result.status,
                    "steps": result.steps,
                    "cost_usd": result.cost_usd,
                    "reason": getattr(result, "reason", ""),
                    "trace_path": getattr(result, "trace_path", ""),
                    "report_path": getattr(result, "report_path", ""),
                    "diff_path": getattr(result, "diff_path", ""),
                    "workspace_path": getattr(result, "workspace_path", ""),
                    "verify_output": getattr(result, "verify_output", ""),
                }
                for result in task_results
            ],
        }

    pass_rates = [float(task["pass_rate"]) for task in task_summaries.values()]
    return {
        "total": total,
        "solved": solved,
        "solution_rate": solved / total if total else 0.0,
        "tasks": task_summaries,
        "mean_solution_rate": statistics.mean(pass_rates) if pass_rates else 0.0,
        "std_solution_rate": statistics.pstdev(pass_rates) if pass_rates else 0.0,
        "avg_steps": sum(result.steps for result in results) / total if total else 0.0,
        "avg_cost_usd": sum(result.cost_usd for result in results) / total if total else 0.0,
    }


def fake_agent(workspace: Path, prompt: str, profile: ProjectProfile) -> dict[str, Any]:
    if (workspace / "greeting.py").exists():
        (workspace / "greeting.py").write_text("def greet(name):\n    return f'Hello, {name}!'\n", encoding="utf-8")
    if (workspace / "count.py").exists():
        (workspace / "count.py").write_text("def inclusive_count(n):\n    return list(range(n + 1))\n", encoding="utf-8")
    if (workspace / "first.py").exists():
        (workspace / "first.py").write_text("def first(items):\n    return None if not items else items[0]\n", encoding="utf-8")
    if (workspace / "pricing.py").exists():
        (workspace / "pricing.py").write_text("def apply_discount(price, percent):\n    return price * (1 - percent / 100)\n", encoding="utf-8")
    if (workspace / "normalizer.py").exists():
        (workspace / "normalizer.py").write_text("def normalize_name(value):\n    return value.strip().lower().replace(\" \", \"-\")\n", encoding="utf-8")

    cmake = workspace / "CMakeLists.txt"
    if cmake.exists():
        text = cmake.read_text(encoding="utf-8")
        if "add_executable(app src/main.cpp)" in text and (workspace / "include").exists():
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_include_directories(app PRIVATE include)\n",
                1,
            )
        if "add_executable(app src/main.cpp)" in text and (workspace / "src" / "add.cpp").exists():
            text = text.replace("add_executable(app src/main.cpp)", "add_executable(app src/main.cpp src/add.cpp)", 1)
        if "add_executable(app src/main.cpp)\nadd_test" in text and "add_library(mathx" in text:
            text = text.replace("add_executable(app src/main.cpp)\nadd_test", "add_executable(app src/main.cpp)\ntarget_link_libraries(app PRIVATE mathx)\nadd_test", 1)
        text = text.replace("MathX::Core", "mathx")
        cmake.write_text(text, encoding="utf-8")

    scale_cpp = workspace / "src" / "scale.cpp"
    if scale_cpp.exists():
        scale_cpp.write_text(
            '#include "mathx/scale.hpp"\n\nnamespace mathx {\ndouble scale(double value, double factor) {\n    return value * factor;\n}\n}\n',
            encoding="utf-8",
        )

    # Real-inspired task: r01 — include local PostgreSQLClient.cmake
    pg_client = workspace / "cmake" / "PostgreSQLClient.cmake"
    if pg_client.exists():
        text = cmake.read_text(encoding="utf-8")
        if "include(cmake/PostgreSQLClient.cmake)" not in text:
            text = text.replace(
                "project(R01PocoPostgreSQL LANGUAGES CXX)\n\nenable_testing()",
                "project(R01PocoPostgreSQL LANGUAGES CXX)\n\ninclude(cmake/PostgreSQLClient.cmake)\n\nenable_testing()",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    # Real-inspired task: r02 — use add_subdirectory instead of find_package
    json_cmake = workspace / "third_party" / "json" / "CMakeLists.txt"
    if json_cmake.exists():
        text = cmake.read_text(encoding="utf-8")
        text = text.replace("find_package(nlohmann_json REQUIRED)", "add_subdirectory(third_party/json)")
        cmake.write_text(text, encoding="utf-8")

    # r03 — add boost_graph include dir
    if (workspace / "third_party" / "boost_graph" / "include").exists():
        text = cmake.read_text(encoding="utf-8")
        if "third_party/boost_graph/include" not in text:
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_include_directories(app PRIVATE third_party/boost_graph/include)\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    # r04 — include GperftoolsProfiler.cmake
    if (workspace / "cmake" / "GperftoolsProfiler.cmake").exists():
        text = cmake.read_text(encoding="utf-8")
        if "include(cmake/GperftoolsProfiler.cmake)" not in text:
            text = text.replace(
                "project(R04Gperftools LANGUAGES CXX)\n\n",
                "project(R04Gperftools LANGUAGES CXX)\n\ninclude(cmake/GperftoolsProfiler.cmake)\n\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    # r05 — replace pkg-config block with offline PETSc
    if (workspace / "cmake" / "PETScOffline.cmake").exists():
        text = cmake.read_text(encoding="utf-8")
        text = text.replace(
            "find_package(PkgConfig REQUIRED)\npkg_check_modules(PETSC REQUIRED IMPORTED_TARGET PETSc)\n\n",
            "include(cmake/PETScOffline.cmake)\n\n",
        )
        text = text.replace("PkgConfig::PETSC", "PETSc::petsc")
        cmake.write_text(text, encoding="utf-8")

    # r06 — add ${CMAKE_CURRENT_BINARY_DIR} include
    if (workspace / "config" / "app_config.hpp.in").exists():
        text = cmake.read_text(encoding="utf-8")
        if "${CMAKE_CURRENT_BINARY_DIR}" not in text:
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_include_directories(app PRIVATE ${CMAKE_CURRENT_BINARY_DIR})\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    # r07 — set WORKING_DIRECTORY for reads_fixture test
    if (workspace / "data" / "value.txt").exists():
        text = cmake.read_text(encoding="utf-8")
        text = text.replace(
            "add_test(NAME reads_fixture COMMAND app)",
            "add_test(NAME reads_fixture COMMAND app)\nset_tests_properties(reads_fixture PROPERTIES WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})",
        )
        cmake.write_text(text, encoding="utf-8")

    # r08 — add src/add.cpp when R08LocalSourceOmitted
    if (workspace / "src" / "add.cpp").exists() and "R08LocalSourceOmitted" in cmake.read_text(encoding="utf-8"):
        text = cmake.read_text(encoding="utf-8")
        text = text.replace("add_executable(app src/main.cpp)", "add_executable(app src/main.cpp src/add.cpp)", 1)
        cmake.write_text(text, encoding="utf-8")

    # r09 — link mathapp -> mathcore
    if (workspace / "src" / "core.cpp").exists() and (workspace / "src" / "app_math.cpp").exists():
        text = cmake.read_text(encoding="utf-8")
        if "target_link_libraries(mathapp PUBLIC mathcore)" not in text:
            text = text.replace(
                "target_include_directories(mathapp PUBLIC include)\n",
                "target_include_directories(mathapp PUBLIC include)\ntarget_link_libraries(mathapp PUBLIC mathcore)\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    # r10 — define ENABLE_FAST_PATH
    if "R10CompileDefinition" in cmake.read_text(encoding="utf-8"):
        text = cmake.read_text(encoding="utf-8")
        if "ENABLE_FAST_PATH" not in text:
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_compile_definitions(app PRIVATE ENABLE_FAST_PATH)\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    return {"steps": 1, "cost_usd": 0.0}


def discover(root: Path) -> list[EvalTask]:
    tasks = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        profile_path = path / "profile.yaml"
        profile = load_profile(profile_path) if profile_path.exists() else ProjectProfile()
        tasks.append(EvalTask(path.name, path, profile))
    return tasks


def _llm_env_kwargs(prefix: str) -> dict[str, str]:
    kwargs = {}
    model = os.environ.get(f"{prefix}_MODEL")
    effort = os.environ.get(f"{prefix}_REASONING_EFFORT")
    if model:
        kwargs["model"] = model
    if effort:
        kwargs["reasoning_effort"] = effort
    return kwargs


def _has_llm_env(prefix: str) -> bool:
    return bool(os.environ.get(f"{prefix}_MODEL") or os.environ.get(f"{prefix}_REASONING_EFFORT"))

def _maybe_enrich_prompt(workspace: Path, prompt: str, profile: ProjectProfile, runner: CommandRunner, trace=None) -> tuple[str, str, list, list]:
    if profile.language != "cmake":
        return prompt, "", [], []
    from agent.build_runner import run_cmake_verification
    from agent.build_errors import classify_build_output
    from agent.cmake_prompt import build_cmake_task_prompt
    from agent.repair_memory import select_cmake_repair_memory

    attempts = run_cmake_verification(workspace, profile, runner, trace)
    initial_output = "\n".join(attempt.output_preview for attempt in attempts)
    first_failure = next((a for a in attempts if a.exit_code != 0), None)
    error = classify_build_output(initial_output, phase=first_failure.phase if first_failure else None, command=first_failure.command if first_failure else None)
    repair_memory_matches = select_cmake_repair_memory(workspace, error)
    return build_cmake_task_prompt(prompt, workspace, profile, initial_output, trace,
                                   initial_attempts=attempts,
                                   repair_memory_matches=repair_memory_matches), initial_output, attempts, repair_memory_matches


def real_agent_factory() -> AgentCallable:
    def agent(workspace: Path, prompt: str, profile: ProjectProfile) -> dict[str, Any]:
        from agent.budget import Budget
        from agent.editor import SearchReplaceEditor
        from agent.llm import LLMClient
        from agent.locator import GrepLocator
        from agent.loop import AgentLoop
        from agent.tools import RunContext, build_default_registry
        from agent.trace import Trace

        trace = Trace(workspace.parent / f"{workspace.name}.trace.jsonl")
        ctx = RunContext(workspace, profile, trace, Budget(), GrepLocator(workspace, profile), SearchReplaceEditor(profile))
        task_prompt, initial_output, initial_attempts, repair_memory_matches = _maybe_enrich_prompt(workspace, prompt, profile, ctx.runner or default_command_runner, trace)
        result = AgentLoop(LLMClient(trace=trace, **_llm_env_kwargs("DEEPSEEK")), build_default_registry()).run(task_prompt, ctx)
        if profile.language == "cmake":
            from agent.build_runner import run_cmake_verification
            from agent.fix_report import build_fix_report, write_fix_report
            from agent.repair_memory import append_repair_case, extract_repair_case_from_artifacts, repair_memory_jsonl

            attempts = run_cmake_verification(workspace, profile, ctx.runner or default_command_runner, trace)
            final_output = "\n".join(attempt.output_preview for attempt in attempts)
            report = build_fix_report(prompt, result, attempts, workspace, initial_output, final_output, initial_attempts=initial_attempts, repair_memory_matches=repair_memory_matches)
            write_fix_report(report, workspace / "fix_report.md", trace)

            # 先写 final.diff，再用 artifact extractor 读取文件提取 repair case
            (workspace / "final.diff").write_text(getattr(result, "diff", ""), encoding="utf-8")
            repair_case = extract_repair_case_from_artifacts(workspace, source=str(workspace))
            append_repair_case(repair_memory_jsonl(workspace), repair_case)
        else:
            (workspace / "final.diff").write_text(getattr(result, "diff", ""), encoding="utf-8")
        return {"steps": ctx.budget.steps, "cost_usd": result.cost_usd, "reason": result.reason}
    return agent


def multi_agent_factory() -> AgentCallable:
    def agent(workspace: Path, prompt: str, profile: ProjectProfile) -> dict[str, Any]:
        from agent.budget import Budget
        from agent.editor import SearchReplaceEditor
        from agent.llm import LLMClient
        from agent.locator import GrepLocator
        from agent.multi_agent import MultiAgentOrchestrator
        from agent.tools import RunContext, build_default_registry
        from agent.trace import Trace

        trace = Trace(workspace.parent / f"{workspace.name}.trace.jsonl")
        ctx = RunContext(workspace, profile, trace, Budget(), GrepLocator(workspace, profile), SearchReplaceEditor(profile))
        llm = LLMClient(trace=trace, **_llm_env_kwargs("DEEPSEEK"))
        role_llms = {}
        if _has_llm_env("PLANNER"):
            role_llms["planner_llm"] = LLMClient(trace=trace, **_llm_env_kwargs("PLANNER"))
        if _has_llm_env("REVIEWER"):
            role_llms["reviewer_llm"] = LLMClient(trace=trace, **_llm_env_kwargs("REVIEWER"))
        task_prompt, initial_output, initial_attempts, repair_memory_matches = _maybe_enrich_prompt(workspace, prompt, profile, ctx.runner or default_command_runner, trace)
        result = MultiAgentOrchestrator(llm, build_default_registry(), **role_llms).run(task_prompt, ctx)
        if profile.language == "cmake":
            from agent.build_runner import run_cmake_verification
            from agent.fix_report import build_fix_report, write_fix_report
            from agent.repair_memory import append_repair_case, extract_repair_case_from_artifacts, repair_memory_jsonl

            attempts = run_cmake_verification(workspace, profile, ctx.runner or default_command_runner, trace)
            final_output = "\n".join(attempt.output_preview for attempt in attempts)
            report = build_fix_report(prompt, result, attempts, workspace, initial_output, final_output, initial_attempts=initial_attempts, repair_memory_matches=repair_memory_matches)
            write_fix_report(report, workspace / "fix_report.md", trace)

            # 先写 final.diff，再用 artifact extractor 读取文件
            (workspace / "final.diff").write_text(getattr(result, "diff", ""), encoding="utf-8")
            repair_case = extract_repair_case_from_artifacts(workspace, source=str(workspace))
            append_repair_case(repair_memory_jsonl(workspace), repair_case)
        else:
            (workspace / "final.diff").write_text(getattr(result, "diff", ""), encoding="utf-8")
        return {"steps": result.steps, "cost_usd": result.cost_usd, "reason": result.reason}
    return agent

def main(argv: list[str] | None = None, agent_factory: Callable[[], AgentCallable] | None = None, work_root: Path = Path("workspace")) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", type=Path, nargs="?", default=Path(__file__).parent / "tasks")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--multi", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--json-summary", type=Path)
    args = parser.parse_args(argv)
    if args.fake:
        agent = fake_agent
    else:
        if agent_factory is None and not os.environ.get("DEEPSEEK_API_KEY"):
            print("DEEPSEEK_API_KEY is required for non-fake eval runs", file=sys.stderr)
            return 2
        default_factory = multi_agent_factory if args.multi else real_agent_factory
        agent = (agent_factory or default_factory)()
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    results = []
    for task in discover(args.tasks):
        for run_index in range(1, args.repeat + 1):
            results.append(run_task(task, agent, work_root / task.id / f"run-{run_index}"))
    summary = summarize(results)
    print(summary)
    if args.json_summary:
        args.json_summary.parent.mkdir(parents=True, exist_ok=True)
        args.json_summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if summary["solved"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
