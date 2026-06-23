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
    def __init__(self, responses): self.responses = list(responses); self.messages_seen = []; self.prefix_len = None
    def chat(self, messages, tools):
        if self.prefix_len is None:
            self.prefix_len = len(messages)
        self.messages_seen.append([dict(m) for m in messages[:self.prefix_len]])
        return self.responses.pop(0)


def make_ctx(tmp_path: Path, budget=None, profile=None, runner=None):
    profile = profile or ProjectProfile()
    return RunContext(tmp_path, profile, Trace(tmp_path / "trace.jsonl"), budget or Budget(max_steps=5), GrepLocator(tmp_path, profile), SearchReplaceEditor(profile), runner)


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


def test_loop_runs_baseline_tests_when_profile_has_test_cmd(tmp_path: Path):
    calls = []

    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        calls.append((cmd, cwd, timeout, allow_network))
        return {"exit_code": 0, "stdout": "green\n", "stderr": ""}

    profile = ProjectProfile(test_cmd="pytest -q")
    ctx = make_ctx(tmp_path, Budget(max_steps=0), profile, fake_runner)

    result = AgentLoop(FakeLLM([]), build_default_registry()).run("x", ctx)

    assert result.reason == "budget_exceeded"
    assert calls == [("pytest -q", tmp_path, 60, False)]


def test_loop_skips_baseline_tests_without_test_cmd(tmp_path: Path):
    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        raise AssertionError("runner should not be called")

    ctx = make_ctx(tmp_path, Budget(max_steps=0), ProjectProfile(), fake_runner)

    result = AgentLoop(FakeLLM([]), build_default_registry()).run("x", ctx)
    assert result.reason == "budget_exceeded"


def test_loop_includes_repo_overview_in_stable_prefix(tmp_path: Path):
    (tmp_path / "greeting.py").write_text("hello\n", encoding="utf-8")
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "x.js").write_text("ignored\n", encoding="utf-8")
    profile = ProjectProfile(ignore=["node_modules"])
    ctx = RunContext(tmp_path, profile, Trace(tmp_path / "trace.jsonl"), Budget(max_steps=5), GrepLocator(tmp_path, profile), SearchReplaceEditor(profile))
    llm = FakeLLM([
        Resp(None, [Call("1", "read_file", {"path":"greeting.py"})], {}),
        Resp(None, [Call("2", "finish", {"summary":"done"})], {}),
    ])

    AgentLoop(llm, build_default_registry()).run("change greeting", ctx)

    prefix_text = "\n".join(message["content"] for message in llm.messages_seen[0])
    assert "greeting.py" in prefix_text
    assert "node_modules" not in prefix_text
    assert llm.messages_seen[0] == llm.messages_seen[-1]


def test_loop_prompt_uses_relative_paths_and_windows_context(tmp_path: Path):
    (tmp_path / "greeting.py").write_text("hello\n", encoding="utf-8")
    llm = FakeLLM([Resp(None, [Call("1", "finish", {"summary":"done"})], {})])

    AgentLoop(llm, build_default_registry()).run("change greeting", make_ctx(tmp_path))

    prefix = llm.messages_seen[0]
    prefix_text = "\n".join(message["content"] for message in prefix)
    system_text = prefix[0]["content"]
    assert str(tmp_path) not in prefix_text
    assert "relative" in system_text.lower()
    assert "repo root" in system_text.lower()
    assert "workspace/" in system_text
    assert "absolute" in system_text.lower()
    assert "Windows" in system_text
    assert "cmd" in system_text

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



import pytest


@pytest.mark.parametrize("profile", [ProjectProfile(), ProjectProfile(syntax_check={".py": "fake-check {file}"})])
def test_loop_runs_same_read_edit_finish_sequence_across_profiles(tmp_path: Path, profile: ProjectProfile):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    syntax_calls = []
    def syntax_runner(cmd, cwd=None, timeout=None):
        syntax_calls.append((cmd, cwd, timeout))
        return {"exit_code": 0, "stdout": "", "stderr": ""}
    ctx = RunContext(tmp_path, profile, Trace(tmp_path / "trace.jsonl"), Budget(max_steps=5), GrepLocator(tmp_path, profile), SearchReplaceEditor(profile, runner=syntax_runner))
    llm = FakeLLM([
        Resp(None, [Call("1", "read_file", {"path":"a.py"})], {}),
        Resp(None, [Call("2", "edit", {"path":"a.py", "search":"hello", "replace":"hi"})], {}),
        Resp(None, [Call("3", "finish", {"summary":"done"})], {}),
    ])

    result = AgentLoop(llm, build_default_registry()).run("change greeting", ctx)

    assert result.reason == "finished"
    assert "-hello" in result.diff and "+hi" in result.diff
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "hi\n"


class FakeCheckpoint:
    def __init__(self, diff_text="sentinel diff", fail_init=False):
        self.diff_text = diff_text
        self.fail_init = fail_init
    def init(self):
        if self.fail_init:
            raise RuntimeError("checkpoint init failed")
    def diff(self):
        return self.diff_text


def test_loop_finalizes_with_checkpoint_diff(tmp_path: Path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    llm = FakeLLM([Resp(None, [Call("f", "finish", {"summary":"done"})], {})])
    result = AgentLoop(llm, build_default_registry(), checkpoint_factory=lambda workspace: FakeCheckpoint("from checkpoint")).run("x", make_ctx(tmp_path))
    assert result.diff == "from checkpoint"


def test_loop_records_checkpoint_warning_when_init_fails(tmp_path: Path):
    llm = FakeLLM([Resp(None, [Call("f", "finish", {"summary":"done"})], {})])
    AgentLoop(llm, build_default_registry(), checkpoint_factory=lambda workspace: FakeCheckpoint("", fail_init=True)).run("x", make_ctx(tmp_path))
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    warnings = [row for row in rows if row["t"] == "checkpoint_warning"]
    assert warnings
    assert "checkpoint init failed" in warnings[0]["error"]


def test_finish_is_blocked_until_configured_tests_pass(tmp_path: Path):
    calls = []
    results = [
        {"exit_code": 1, "stdout": "baseline red\n", "stderr": ""},
        {"exit_code": 1, "stdout": "still red\n", "stderr": "details\n"},
        {"exit_code": 0, "stdout": "green\n", "stderr": ""},
    ]

    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        calls.append((cmd, cwd, timeout, allow_network))
        return results.pop(0)

    profile = ProjectProfile(test_cmd="pytest -q")
    ctx = make_ctx(tmp_path, Budget(max_steps=5), profile, fake_runner)
    llm = FakeLLM([
        Resp(None, [Call("f1", "finish", {"summary": "done"})], {}),
        Resp(None, [Call("f2", "finish", {"summary": "done"})], {}),
    ])

    result = AgentLoop(llm, build_default_registry()).run("x", ctx)

    assert result.reason == "finished"
    assert calls == [("pytest -q", tmp_path, 60, False)] * 3
    tool_messages = [m["content"] for m in result.messages if m["role"] == "tool"]
    assert any("测试未通过（基线 passed=False）" in message for message in tool_messages)
    assert any("still red" in message and "details" in message for message in tool_messages)


def test_finish_without_test_cmd_is_not_gated(tmp_path: Path):
    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        raise AssertionError("runner should not be called")

    ctx = make_ctx(tmp_path, Budget(max_steps=5), ProjectProfile(), fake_runner)
    llm = FakeLLM([Resp(None, [Call("f", "finish", {"summary": "done"})], {})])

    result = AgentLoop(llm, build_default_registry()).run("x", ctx)

    assert result.reason == "finished"
    assert len(llm.messages_seen) == 1


def test_finish_with_failing_tests_is_released_after_block_limit(tmp_path: Path):
    calls = []

    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        calls.append((cmd, cwd, timeout, allow_network))
        return {"exit_code": 1, "stdout": "red\n", "stderr": ""}

    profile = ProjectProfile(test_cmd="pytest -q")
    ctx = make_ctx(tmp_path, Budget(max_steps=10), profile, fake_runner)
    llm = FakeLLM([Resp(None, [Call(f"f{i}", "finish", {"summary": "done"})], {}) for i in range(4)])

    result = AgentLoop(llm, build_default_registry()).run("x", ctx)

    assert result.reason == "finished_with_failing_tests"
    assert len(calls) == 5
    blocked_messages = [m for m in result.messages if m["role"] == "tool" and "测试未通过" in m["content"]]
    assert len(blocked_messages) == 3


def test_loop_adds_test_guidance_to_stable_prefix_when_test_cmd_exists(tmp_path: Path):
    calls = []

    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        calls.append(cmd)
        return {"exit_code": 0, "stdout": "green\n", "stderr": ""}

    profile = ProjectProfile(test_cmd="pytest -q")
    ctx = make_ctx(tmp_path, Budget(max_steps=5), profile, fake_runner)
    llm = FakeLLM([
        Resp("thinking", [], {}),
        Resp(None, [Call("f", "finish", {"summary": "done"})], {}),
    ])

    result = AgentLoop(llm, build_default_registry()).run("x", ctx)

    assert result.reason == "finished"
    prefix_text = "\n".join(message["content"] for message in llm.messages_seen[0])
    assert "测试命令：pytest -q" in prefix_text
    assert "run_command" in prefix_text
    assert "跑测试" in prefix_text
    assert "finish" in prefix_text
    assert llm.messages_seen[0] == llm.messages_seen[-1]


def test_loop_omits_test_guidance_without_test_cmd(tmp_path: Path):
    llm = FakeLLM([Resp(None, [Call("f", "finish", {"summary": "done"})], {})])

    AgentLoop(llm, build_default_registry()).run("x", make_ctx(tmp_path))

    prefix_text = "\n".join(message["content"] for message in llm.messages_seen[0])
    assert "测试命令：" not in prefix_text
