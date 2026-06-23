"""Evaluation harness for fixed tasks."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from agent.profile import ProjectProfile, load_profile


AgentCallable = Callable[[Path, str, ProjectProfile], dict[str, Any]]


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


def run_task(task: EvalTask, agent: AgentCallable, work_root: Path) -> EvalResult:
    task_path = task.path.resolve()
    if work_root.exists():
        shutil.rmtree(work_root)
    shutil.copytree(task_path / "repo", work_root)
    prompt = (task_path / "prompt.md").read_text(encoding="utf-8")
    meta = agent(work_root, prompt, task.profile) or {}
    verify = task_path / "verify.py"
    proc = subprocess.run([sys.executable, "-c", verify.read_text(encoding="utf-8").lstrip("\ufeff")], cwd=work_root, text=True, capture_output=True)
    return EvalResult(task.id, "solved" if proc.returncode == 0 else "failed", int(meta.get("steps", 0)), float(meta.get("cost_usd", 0.0)))


def summarize(results: list[EvalResult]) -> dict[str, float | int]:
    total = len(results)
    solved = sum(1 for result in results if result.status == "solved")
    return {
        "total": total,
        "solved": solved,
        "solution_rate": solved / total if total else 0.0,
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
        result = AgentLoop(LLMClient(trace=trace), build_default_registry()).run(prompt, ctx)
        return {"steps": ctx.budget.steps, "cost_usd": 0.0, "reason": result.reason}
    return agent


def main(argv: list[str] | None = None, agent_factory: Callable[[], AgentCallable] | None = None, work_root: Path = Path("workspace")) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", type=Path, nargs="?", default=Path(__file__).parent / "tasks")
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args(argv)
    if args.fake:
        agent = fake_agent
    else:
        if agent_factory is None and not os.environ.get("DEEPSEEK_API_KEY"):
            print("DEEPSEEK_API_KEY is required for non-fake eval runs", file=sys.stderr)
            return 2
        agent = (agent_factory or real_agent_factory)()
    results = [run_task(task, agent, work_root / task.id) for task in discover(args.tasks)]
    summary = summarize(results)
    print(summary)
    return 0 if summary["solved"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


