"""Evaluation harness for fixed tasks."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any


@dataclass
class EvalTask:
    id: str
    path: Path


@dataclass
class EvalResult:
    task_id: str
    status: str
    steps: int
    cost_usd: float


def run_task(task: EvalTask, agent: Callable[[Path, str], dict[str, Any]], work_root: Path) -> EvalResult:
    task_path = task.path.resolve()
    if work_root.exists():
        shutil.rmtree(work_root)
    shutil.copytree(task_path / "repo", work_root)
    prompt = (task_path / "prompt.md").read_text(encoding="utf-8")
    meta = agent(work_root, prompt) or {}
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


def fake_agent(workspace: Path, prompt: str) -> dict[str, Any]:
    if (workspace / "greeting.py").exists():
        (workspace / "greeting.py").write_text("def greet(name):\n    return f'Hello, {name}!'\n", encoding="utf-8")
    if (workspace / "count.py").exists():
        (workspace / "count.py").write_text("def inclusive_count(n):\n    return list(range(n + 1))\n", encoding="utf-8")
    if (workspace / "first.py").exists():
        (workspace / "first.py").write_text("def first(items):\n    return None if not items else items[0]\n", encoding="utf-8")
    return {"steps": 1, "cost_usd": 0.0}


def discover(root: Path) -> list[EvalTask]:
    return [EvalTask(path.name, path) for path in sorted(root.iterdir()) if path.is_dir()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", type=Path, nargs="?", default=Path(__file__).parent / "tasks")
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args(argv)
    agent = fake_agent if args.fake else fake_agent
    results = [run_task(task, agent, Path("workspace") / task.id) for task in discover(args.tasks)]
    summary = summarize(results)
    print(summary)
    return 0 if summary["solved"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())



