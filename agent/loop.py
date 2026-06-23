"""Minimal ReAct loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.budget import LoopDetector
from agent.checkpoint import GitCheckpoint
from agent.tester import run_tests
from agent.tools import RunContext, ToolRegistry, ToolResult, default_runner


MAX_FINISH_BLOCKS = 3


@dataclass
class RunResult:
    reason: str
    diff: str
    messages: list[dict[str, Any]]
    cost_usd: float = 0.0


def build_repo_overview(ctx: RunContext, max_files: int = 200, max_chars: int = 4000) -> str:
    paths: list[str] = []
    for path in sorted(ctx.workspace.rglob("*")):
        rel = path.relative_to(ctx.workspace).as_posix()
        if ctx.profile.should_ignore(rel):
            continue
        paths.append(rel + ("/" if path.is_dir() else ""))
        if len(paths) >= max_files:
            paths.append("...<truncated>")
            break
    body = "\n".join(paths) if paths else "(empty)"
    if len(body) > max_chars:
        body = body[:max_chars] + "\n...<truncated>"
    return "Repository files (relative to repo root):\n" + body

class AgentLoop:
    def __init__(self, llm: Any, tools: ToolRegistry, checkpoint_factory: Callable[[Any], Any] = GitCheckpoint):
        self.llm = llm
        self.tools = tools
        self.checkpoint_factory = checkpoint_factory

    def run(self, task: str, ctx: RunContext) -> RunResult:
        checkpoint = self.checkpoint_factory(ctx.workspace)
        try:
            checkpoint.init()
        except Exception as exc:
            ctx.trace.write({"t": "checkpoint_warning", "error": str(exc)})
        baseline = run_tests(ctx.workspace, ctx.profile, ctx.runner or default_runner)
        system_content = "You are a code agent. Use tools and call finish when done. Use file paths relative to the repo root, for example greeting.py. Do not add workspace/ or absolute path prefixes. The environment is Windows; run_command executes through cmd, so use Windows-compatible commands."
        if ctx.profile.test_cmd:
            system_content += f" 测试命令：{ctx.profile.test_cmd}。改完代码后用 run_command 跑测试验证，确认通过再调 finish。"
        prefix = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": build_repo_overview(ctx)},
            {"role": "user", "content": f"Task: {task}"},
        ]
        messages = list(prefix)
        detector = LoopDetector()
        finish_blocks = 0
        total_cost_usd = 0.0
        while ctx.budget.ok():
            response = self.llm.chat(messages, self.tools.to_openai_tools())
            ctx.budget.tick(getattr(response, "prompt_tokens", 0) + getattr(response, "completion_tokens", 0))
            total_cost_usd += float(getattr(response, "cost_usd", 0.0) or 0.0)
            assistant_message = getattr(response, "assistant_message", None) or {"role": "assistant", "content": response.content}
            if "role" not in assistant_message:
                assistant_message = {"role": "assistant", "content": response.content, **assistant_message}
            messages.append(assistant_message)
            if not response.tool_calls:
                messages.append({"role": "tool", "tool_call_id": "nudge", "content": "请调用 finish 或继续使用工具。"})
                continue
            for call in response.tool_calls:
                if call.name == "finish":
                    current = run_tests(ctx.workspace, ctx.profile, ctx.runner or default_runner)
                    if current is None or current.passed:
                        result = self._finalize(ctx, messages, "finished", total_cost_usd, checkpoint)
                        return result
                    if finish_blocks >= MAX_FINISH_BLOCKS:
                        result = self._finalize(ctx, messages, "finished_with_failing_tests", total_cost_usd, checkpoint)
                        return result
                    baseline_passed = baseline.passed if baseline is not None else None
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": f"测试未通过（基线 passed={baseline_passed}）。输出：{current.output}。请修复后再 finish。"})
                    finish_blocks += 1
                    break
                action = {"tool": call.name, "args": call.args}
                if detector.is_repeating(action):
                    result = ToolResult("检测到重复动作，请换思路", is_error=True)
                else:
                    result = self.tools.run(call.name, call.args, ctx)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content})
        return self._finalize(ctx, messages, "budget_exceeded", total_cost_usd, checkpoint)

    def _finalize(self, ctx: RunContext, messages: list[dict[str, Any]], reason: str, total_cost_usd: float, checkpoint: Any) -> RunResult:
        try:
            diff = checkpoint.diff()
        except Exception as exc:
            ctx.trace.write({"t": "checkpoint_warning", "error": str(exc)})
            diff = ""
        ctx.trace.run_summary(task_id="manual", steps=ctx.budget.steps, total_tokens=ctx.budget.tokens, total_cost_usd=total_cost_usd, result=reason, diff_path="")
        return RunResult(reason, diff, messages, total_cost_usd)





