"""Multi-agent orchestration: Planner -> Coder -> Reviewer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.budget import Budget
from agent.checkpoint import GitCheckpoint
from agent.loop import AgentLoop, RunResult
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


def run_planner(llm: Any, task: str, base_ctx: RunContext, max_steps: int = 8) -> tuple[str, RunResult]:
    loop = AgentLoop(llm, build_readonly_registry(), checkpoint_factory=NoOpCheckpoint, system_prompt=PLANNER_PROMPT)
    result = loop.run(f"为以下任务制定修改计划：{task}", _role_ctx(base_ctx, max_steps))
    return result.finish_summary, result


def run_reviewer(llm: Any, task: str, diff: str, base_ctx: RunContext, max_steps: int = 8) -> tuple[bool, str, RunResult]:
    loop = AgentLoop(llm, build_readonly_registry(), checkpoint_factory=NoOpCheckpoint, system_prompt=REVIEWER_PROMPT)
    review_task = f"任务：{task}\n\nCoder 的改动 diff：\n{diff}\n\n请审查并 finish。"
    result = loop.run(review_task, _role_ctx(base_ctx, max_steps))
    summary = result.finish_summary.strip()
    passed = summary.upper().startswith("PASS")
    return passed, summary, result


class MultiAgentOrchestrator:
    def __init__(self, llm: Any, coder_tools, max_review_rounds: int = 2):
        self.llm = llm
        self.coder_tools = coder_tools
        self.max_review_rounds = max_review_rounds

    def run(self, task: str, ctx: RunContext) -> RunResult:
        checkpoint = GitCheckpoint(ctx.workspace)
        try:
            checkpoint.init()
        except Exception as exc:
            ctx.trace.write({"t": "checkpoint_warning", "error": str(exc)})

        total_steps = 0
        total_cost = 0.0
        plan, planner_result = run_planner(self.llm, task, ctx)
        total_steps += planner_result.steps
        total_cost += planner_result.cost_usd

        coder = AgentLoop(self.llm, self.coder_tools, checkpoint_factory=NoOpCheckpoint)
        coder_result = coder.run(f"{task}\n\n参考修改计划：\n{plan}", _role_ctx(ctx, 40))
        total_steps += coder_result.steps
        total_cost += coder_result.cost_usd

        reason = "finished"
        round_idx = -1
        for round_idx in range(self.max_review_rounds):
            diff = checkpoint.diff()
            passed, comments, reviewer_result = run_reviewer(self.llm, task, diff, ctx)
            total_steps += reviewer_result.steps
            total_cost += reviewer_result.cost_usd
            if passed:
                reason = "finished"
                break
            if round_idx == self.max_review_rounds - 1:
                reason = "review_unresolved"
                break
            coder_result = coder.run(f"{task}\n\n上轮改动被 Reviewer 打回：{comments}\n请在现有基础上修复。", _role_ctx(ctx, 40))
            total_steps += coder_result.steps
            total_cost += coder_result.cost_usd

        ctx.trace.write({"t": "multi_summary", "result": reason, "rounds": round_idx + 1})
        return RunResult(reason, checkpoint.diff(), [], total_cost, "", steps=total_steps)
