"""Language-agnostic test runner support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.profile import ProjectProfile
from agent.tools import truncate


@dataclass
class TestResult:
    passed: bool
    exit_code: int
    output: str


def run_tests(workspace: str | Path, profile: ProjectProfile, runner: Callable[..., dict[str, Any]]) -> TestResult | None:
    if not profile.test_cmd:
        return None

    result = runner(profile.test_cmd, cwd=Path(workspace), timeout=profile.test_timeout, allow_network=False)
    exit_code = int(result.get("exit_code", 1))
    output = truncate(f"{result.get('stdout', '')}{result.get('stderr', '')}")
    passed = exit_code == 0 if profile.pass_when == "exit_zero" else False
    return TestResult(passed=passed, exit_code=exit_code, output=output)

