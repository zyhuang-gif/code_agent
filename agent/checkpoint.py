"""Git checkpoint helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Any


def run_subprocess(args: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


class GitCheckpoint:
    def __init__(self, workspace: str | Path, runner: Callable[[list[str], Path], dict[str, Any]] = run_subprocess):
        self.workspace = Path(workspace)
        self.runner = runner

    def _git(self, *args: str) -> dict[str, Any]:
        return self.runner(["git", *args], self.workspace)

    def init(self) -> None:
        self._git("init")
        self._git("config", "user.name", "Codex")
        self._git("config", "user.email", "noreply@anthropic.com")
        self._git("add", "-A")
        result = self._git("commit", "-m", "baseline")
        if result["exit_code"] != 0:
            raise RuntimeError(result["stderr"] or result["stdout"])

    def diff(self) -> str:
        return self._git("diff")["stdout"]

    def rollback(self) -> None:
        self._git("reset", "--hard", "HEAD")
