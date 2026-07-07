"""Git checkpoint helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Any

from agent.profile import ProjectProfile


def run_subprocess(args: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


_CMAKE_ARTIFACT_PATTERNS = ["build/", "build/*", "cmake-build-*/", "_deps/", "CMakeFiles/", "CMakeCache.txt"]


def _append_git_exclude(workspace: Path, patterns: list[str]) -> None:
    exclude_path = workspace / ".git" / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if exclude_path.exists():
        existing = set(line.strip() for line in exclude_path.read_text(encoding="utf-8").splitlines())
    new_patterns = [p for p in patterns if p not in existing]
    if new_patterns:
        with exclude_path.open("a", encoding="utf-8") as handle:
            for pattern in new_patterns:
                handle.write(f"{pattern}\n")


class GitCheckpoint:
    def __init__(self, workspace: str | Path, runner: Callable[[list[str], Path], dict[str, Any]] = run_subprocess):
        self.workspace = Path(workspace)
        self.runner = runner
        # 排除 CMake build 生成物，避免污染基线 commit 和最终 diff
        _append_git_exclude(self.workspace, _CMAKE_ARTIFACT_PATTERNS)

    def _git(self, *args: str) -> dict[str, Any]:
        return self.runner(["git", *args], self.workspace)

    def init(self) -> None:
        self._git("init")
        self._git("config", "user.name", "Codex")
        self._git("config", "user.email", "noreply@anthropic.com")
        # Fix detached HEAD on shallow clones: checkout a branch first.
        # sympy shallow-cloned repos have HEAD detached at FETCH_HEAD,
        # which causes git add -A to succeed but git commit fails with
        # "nothing to commit" because there's no branch to commit onto.
        head = self._git("symbolic-ref", "-q", "HEAD")
        if head["exit_code"] != 0:
            self._git("checkout", "-b", "baseline")
        self._git("add", "-A")
        result = self._git("commit", "-m", "baseline")
        if result["exit_code"] != 0:
            raise RuntimeError(result["stderr"] or result["stdout"])

    def diff(self) -> str:
        return self._git("diff")["stdout"]

    def rollback(self) -> None:
        self._git("reset", "--hard", "HEAD")
