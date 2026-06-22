"""Minimal ReAct loop."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from agent.budget import LoopDetector
from agent.checkpoint import GitCheckpoint
from agent.tools import RunContext, ToolRegistry, ToolResult


@dataclass
class RunResult:
    reason: str
    diff: str
    messages: list[dict[str, Any]]


class AgentLoop:
    def __init__(self, llm: Any, tools: ToolRegistry):
        self.llm = llm
        self.tools = tools

    def run(self, task: str, ctx: RunContext) -> RunResult:
        checkpoint = GitCheckpoint(ctx.workspace)
        try:
            checkpoint.init()
        except Exception:
            pass
        prefix = [
            {"role": "system", "content": "You are a code agent. Use tools and call finish when done."},
            {"role": "user", "content": f"Repository: {ctx.workspace}\nTask: {task}"},
        ]
        messages = list(prefix)
        detector = LoopDetector()
        while ctx.budget.ok():
            response = self.llm.chat(messages, self.tools.to_openai_tools())
            ctx.budget.tick(getattr(response, "prompt_tokens", 0) + getattr(response, "completion_tokens", 0))
            assistant_message = getattr(response, "assistant_message", None) or {"role": "assistant", "content": response.content}
            if "role" not in assistant_message:
                assistant_message = {"role": "assistant", "content": response.content, **assistant_message}
            messages.append(assistant_message)
            if not response.tool_calls:
                messages.append({"role": "tool", "tool_call_id": "nudge", "content": "请调用 finish 或继续使用工具。"})
                continue
            for call in response.tool_calls:
                if call.name == "finish":
                    result = self._finalize(ctx, messages, "finished")
                    return result
                action = {"tool": call.name, "args": call.args}
                if detector.is_repeating(action):
                    result = ToolResult("检测到重复动作，请换思路", is_error=True)
                else:
                    result = self.tools.run(call.name, call.args, ctx)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content})
        return self._finalize(ctx, messages, "budget_exceeded")

    def _finalize(self, ctx: RunContext, messages: list[dict[str, Any]], reason: str) -> RunResult:
        proc = subprocess.run(["git", "diff"], cwd=ctx.workspace, text=True, capture_output=True)
        diff = proc.stdout if proc.returncode == 0 else ""
        ctx.trace.run_summary(task_id="manual", steps=ctx.budget.steps, total_tokens=ctx.budget.tokens, total_cost_usd=0.0, result=reason, diff_path="")
        return RunResult(reason, diff, messages)


