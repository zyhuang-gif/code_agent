"""CMake build/test command runner helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.profile import ProjectProfile
from agent.tools import truncate
from agent.trace import Trace


@dataclass(frozen=True)
class BuildAttempt:
    command: str
    phase: str
    exit_code: int
    output_preview: str


def _phase_for(command: str, index: int) -> str:
    stripped = command.strip()
    if stripped.startswith("ctest"):
        return "test"
    if stripped.startswith("cmake --build"):
        return "build"
    if stripped.startswith("cmake "):
        return "configure"
    return f"step_{index + 1}"


def split_cmake_test_command(profile: ProjectProfile) -> list[tuple[str, str]]:
    if not profile.test_cmd:
        return []
    commands = [part.strip() for part in profile.test_cmd.split("&&") if part.strip()]
    return [(_phase_for(command, index), command) for index, command in enumerate(commands)]


def run_cmake_verification(
    workspace: str | Path,
    profile: ProjectProfile,
    runner: Callable[..., dict[str, Any]],
    trace: Trace | None = None,
) -> list[BuildAttempt]:
    workspace = Path(workspace)
    attempts: list[BuildAttempt] = []
    for phase, command in split_cmake_test_command(profile):
        result = runner(command, cwd=workspace, timeout=profile.test_timeout, allow_network=False)
        exit_code = int(result.get("exit_code", 1))
        output = truncate(f"{result.get('stdout', '')}{result.get('stderr', '')}")
        attempt = BuildAttempt(command=command, phase=phase, exit_code=exit_code, output_preview=output)
        attempts.append(attempt)
        if trace:
            trace.write(
                {
                    "t": "build_attempt",
                    "phase": phase,
                    "command": command,
                    "exit_code": exit_code,
                    "output_preview": output,
                }
            )
        if exit_code != 0:
            break
    return attempts
