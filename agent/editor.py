"""SEARCH/REPLACE editor."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

from agent.profile import ProjectProfile


@dataclass
class EditResult:
    content: str
    is_error: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


def default_runner(cmd: str, cwd: Path | None = None, timeout: int | None = None) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True, timeout=timeout)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


class SearchReplaceEditor:
    def __init__(self, profile: ProjectProfile, runner: Callable[..., dict[str, Any]] = default_runner):
        self.profile = profile
        self.runner = runner

    def edit(self, path: str | Path, search: str, replace: str) -> EditResult:
        path = Path(path)
        original = path.read_text(encoding="utf-8")
        count = original.count(search)
        if count == 0:
            return EditResult("search text not found", is_error=True)
        if count > 1:
            return EditResult("search text is ambiguous; provide more context", is_error=True)
        updated = original.replace(search, replace, 1)
        check = self.profile.syntax_check.get(path.suffix)
        if check:
            path.write_text(updated, encoding="utf-8")
            cmd = check.format(file=str(path))
            result = self.runner(cmd, cwd=path.parent, timeout=30)
            if result.get("exit_code") != 0:
                path.write_text(original, encoding="utf-8")
                return EditResult(result.get("stderr") or result.get("stdout") or "syntax check failed", is_error=True)
        else:
            path.write_text(updated, encoding="utf-8")
        return EditResult("edit applied", meta={"path": str(path)})
