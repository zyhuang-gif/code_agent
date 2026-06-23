"""Multi-agent orchestration: Planner -> Coder -> Reviewer."""

from __future__ import annotations

from pathlib import Path


class NoOpCheckpoint:
    """Checkpoint for read-only roles: do not touch git or produce diffs."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace)

    def init(self) -> None:
        return None

    def diff(self) -> str:
        return ""

    def rollback(self) -> None:
        return None
