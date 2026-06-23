"""Multi-agent orchestration: Planner -> Coder -> Reviewer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.budget import Budget
from agent.loop import AgentLoop
from agent.tools import RunContext, build_readonly_registry


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


PLANNER_PROMPT = (
    "You are a planning agent. 用只读工具（list_dir/read_file/grep）探索相关代码，"
    "然后调用 finish，summary 给出简短、具体的修改计划（改哪些文件、怎么改）。"
    "文件路径用相对仓库根的路径，例如 greeting.py。你不能修改代码，只做规划。"
)
REVIEWER_PROMPT = (
    "You are a code reviewer。Coder 已经改了代码（diff 在任务里给出）。用只读工具读相关代码后判断。"
    "调用 finish，summary 以 'PASS' 开头表示改动正确且干净；以 'FAIL: ' 开头并写出具体问题表示需要返工。"
    "重点看：是否真正解决任务、有没有破坏无关代码、是否过度改动。"
)


def _role_ctx(base: RunContext, max_steps: int) -> RunContext:
    return RunContext(
        base.workspace, base.profile, base.trace,
        Budget(max_steps=max_steps), base.locator, base.editor, base.runner,
    )


def run_planner(llm: Any, task: str, base_ctx: RunContext, max_steps: int = 8) -> str:
    loop = AgentLoop(llm, build_readonly_registry(), checkpoint_factory=NoOpCheckpoint, system_prompt=PLANNER_PROMPT)
    result = loop.run(f"为以下任务制定修改计划：{task}", _role_ctx(base_ctx, max_steps))
    return result.finish_summary
