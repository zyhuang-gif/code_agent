from pathlib import Path
import json
from dataclasses import dataclass
from agent.budget import Budget
from agent.editor import SearchReplaceEditor
from agent.locator import GrepLocator
from agent.loop import AgentLoop
from agent.profile import ProjectProfile
from agent.tools import RunContext, build_default_registry
from agent.trace import Trace


@dataclass
class Call:
    id: str; name: str; args: dict

@dataclass
class Resp:
    content: str | None; tool_calls: list; assistant_message: dict; prompt_tokens: int = 1; completion_tokens: int = 1; cost_usd: float = 0.0

class FakeLLM:
    def __init__(self, responses): self.responses = list(responses); self.messages_seen = []
    def chat(self, messages, tools):
        self.messages_seen.append([dict(m) for m in messages[:2]])
        return self.responses.pop(0)


def make_ctx(tmp_path: Path, budget=None):
    profile = ProjectProfile()
    return RunContext(tmp_path, profile, Trace(tmp_path / "trace.jsonl"), budget or Budget(max_steps=5), GrepLocator(tmp_path, profile), SearchReplaceEditor(profile))


def test_loop_read_edit_finish_produces_diff_and_stable_prefix(tmp_path: Path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    llm = FakeLLM([
        Resp(None, [Call("1", "read_file", {"path":"a.py"})], {}),
        Resp(None, [Call("2", "edit", {"path":"a.py", "search":"hello", "replace":"hi"})], {}),
        Resp(None, [Call("3", "finish", {"summary":"done"})], {}),
    ])
    result = AgentLoop(llm, build_default_registry()).run("change greeting", make_ctx(tmp_path))
    assert result.reason == "finished"
    assert "-hello" in result.diff and "+hi" in result.diff
    assert llm.messages_seen[0] == llm.messages_seen[-1]


def test_loop_budget_and_repetition_are_graceful(tmp_path: Path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    repeat = Resp(None, [Call("1", "read_file", {"path":"a.py"})], {})
    llm = FakeLLM([repeat, repeat, repeat, repeat])
    result = AgentLoop(llm, build_default_registry()).run("x", make_ctx(tmp_path, Budget(max_steps=3)))
    assert result.reason == "budget_exceeded"
    assert any("重复动作" in m["content"] for m in result.messages if m["role"] == "tool")


def test_loop_handles_plain_text_response(tmp_path: Path):
    llm = FakeLLM([Resp("I am done", [], {}), Resp(None, [Call("f", "finish", {"summary":"done"})], {})])
    result = AgentLoop(llm, build_default_registry()).run("x", make_ctx(tmp_path))
    assert result.reason == "finished"


def test_loop_records_cumulative_llm_cost_in_run_summary(tmp_path: Path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    llm = FakeLLM([
        Resp(None, [Call("1", "read_file", {"path":"a.py"})], {}, cost_usd=0.01),
        Resp(None, [Call("2", "edit", {"path":"a.py", "search":"hello", "replace":"hi"})], {}, cost_usd=0.02),
        Resp(None, [Call("3", "finish", {"summary":"done"})], {}, cost_usd=0.03),
    ])
    AgentLoop(llm, build_default_registry()).run("change greeting", make_ctx(tmp_path))
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    summary = [row for row in rows if row["t"] == "run_summary"][-1]
    assert summary["total_cost_usd"] == 0.06

