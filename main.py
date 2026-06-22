"""CLI entry point."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from agent.budget import Budget
from agent.editor import SearchReplaceEditor
from agent.locator import GrepLocator
from agent.loop import AgentLoop
from agent.profile import ProjectProfile, load_profile
from agent.tools import RunContext, build_default_registry
from agent.trace import Trace


@dataclass
class FakeCall:
    id: str
    name: str
    args: dict


@dataclass
class FakeResp:
    content: str | None
    tool_calls: list[FakeCall]
    assistant_message: dict
    prompt_tokens: int = 1
    completion_tokens: int = 1


class FakeLLM:
    def __init__(self):
        self.responses = [FakeResp(None, [FakeCall("f", "finish", {"summary": "fake run"})], {"role":"assistant", "content": None})]
    def chat(self, messages, tools):
        return self.responses.pop(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args(argv)
    profile = load_profile(args.profile) if args.profile else ProjectProfile()
    trace = Trace(args.repo / "trace.jsonl")
    ctx = RunContext(args.repo, profile, trace, Budget(), GrepLocator(args.repo, profile), SearchReplaceEditor(profile))
    llm = FakeLLM() if args.fake else None
    if llm is None:
        from agent.llm import LLMClient
        llm = LLMClient(trace=trace)
    result = AgentLoop(llm, build_default_registry()).run(args.task, ctx)
    diff_path = args.repo / "final.diff"
    diff_path.write_text(result.diff, encoding="utf-8")
    print(f"diff_path={diff_path}")
    print(f"reason={result.reason} cost_usd=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
