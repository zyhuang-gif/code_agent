from pathlib import Path

from agent.multi_agent import MultiAgentOrchestrator, NoOpCheckpoint, run_planner, run_reviewer
from agent.tools import build_default_registry


class _Call:
    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args


class _Resp:
    def __init__(self, content, tool_calls, cost_usd=0.0):
        self.content = content
        self.tool_calls = tool_calls
        self.assistant_message = {}
        self.prompt_tokens = 1
        self.completion_tokens = 1
        self.cost_usd = cost_usd


def _ctx(tmp_path):
    from agent.profile import ProjectProfile
    from agent.trace import Trace
    from agent.locator import GrepLocator
    from agent.editor import SearchReplaceEditor
    from agent.budget import Budget
    from agent.tools import RunContext

    profile = ProjectProfile()
    return RunContext(tmp_path, profile, Trace(tmp_path / "trace.jsonl"), Budget(), GrepLocator(tmp_path, profile), SearchReplaceEditor(profile))


def test_noop_checkpoint_is_inert(tmp_path: Path):
    cp = NoOpCheckpoint(tmp_path)
    cp.init()
    assert cp.diff() == ""
    cp.rollback()


def test_run_planner_returns_plan_with_readonly_tools(tmp_path):
    (tmp_path / "a.py").write_text("def f(): pass\n", encoding="utf-8")
    seen = {}

    class PlanLLM:
        def chat(self, messages, tools):
            seen["names"] = {t["function"]["name"] for t in tools}
            return _Resp(None, [_Call("1", "finish", {"summary": "改 a.py 的 f"})])

    plan, result = run_planner(PlanLLM(), "实现 f", _ctx(tmp_path))
    assert plan == "改 a.py 的 f"
    assert result.steps > 0
    assert seen["names"] == {"list_dir", "read_file", "grep", "finish"}


def test_run_reviewer_parses_pass_and_fail(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")

    class RevLLM:
        def __init__(self, s):
            self.s = s

        def chat(self, messages, tools):
            return _Resp(None, [_Call("1", "finish", {"summary": self.s})])

    passed, comments, result = run_reviewer(RevLLM("PASS 看起来对"), "t", "diff...", _ctx(tmp_path))
    assert passed is True
    assert result.steps > 0
    passed2, comments2, result2 = run_reviewer(RevLLM("FAIL: 改坏了 x"), "t", "diff...", _ctx(tmp_path))
    assert passed2 is False
    assert "改坏" in comments2
    assert result2.steps > 0


def _script_llm(script):
    class ScriptLLM:
        def __init__(self):
            self.q = list(script)

        def chat(self, messages, tools):
            return self.q.pop(0)

    return ScriptLLM()


def test_orchestrator_planner_coder_reviewer_pass(tmp_path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    llm = _script_llm([
        _Resp(None, [_Call("p", "finish", {"summary": "把 hello 改成 hi"})]),
        _Resp(None, [_Call("c1", "edit", {"path": "a.py", "search": "hello", "replace": "hi"})]),
        _Resp(None, [_Call("c2", "finish", {"summary": "done"})]),
        _Resp(None, [_Call("r", "finish", {"summary": "PASS"})]),
    ])
    result = MultiAgentOrchestrator(llm, build_default_registry()).run("change hello", _ctx(tmp_path))
    assert result.reason == "finished"
    assert "-hello" in result.diff and "+hi" in result.diff


def test_orchestrator_uses_role_specific_llms_for_planner_and_reviewer(tmp_path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    planner_llm = _script_llm([
        _Resp(None, [_Call("p", "finish", {"summary": "plan from planner llm"})]),
    ])
    main_llm = _script_llm([
        _Resp(None, [_Call("c1", "edit", {"path": "a.py", "search": "hello", "replace": "hi"})]),
        _Resp(None, [_Call("c2", "finish", {"summary": "done"})]),
    ])
    reviewer_llm = _script_llm([
        _Resp(None, [_Call("r", "finish", {"summary": "PASS"})]),
    ])

    result = MultiAgentOrchestrator(
        main_llm,
        build_default_registry(),
        planner_llm=planner_llm,
        reviewer_llm=reviewer_llm,
    ).run("change hello", _ctx(tmp_path))

    assert result.reason == "finished"
    assert len(planner_llm.q) == 0
    assert len(main_llm.q) == 0
    assert len(reviewer_llm.q) == 0
def test_orchestrator_review_loop_then_pass(tmp_path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    llm = _script_llm([
        _Resp(None, [_Call("p", "finish", {"summary": "计划"})]),
        _Resp(None, [_Call("c1", "edit", {"path": "a.py", "search": "hello", "replace": "hi"})]),
        _Resp(None, [_Call("c2", "finish", {"summary": "done"})]),
        _Resp(None, [_Call("r1", "finish", {"summary": "FAIL: 还要改"})]),
        _Resp(None, [_Call("c3", "edit", {"path": "a.py", "search": "hi", "replace": "hey"})]),
        _Resp(None, [_Call("c4", "finish", {"summary": "done2"})]),
        _Resp(None, [_Call("r2", "finish", {"summary": "PASS"})]),
    ])
    result = MultiAgentOrchestrator(llm, build_default_registry(), max_review_rounds=2).run("x", _ctx(tmp_path))
    assert result.reason == "finished"
    assert "+hey" in result.diff


def test_orchestrator_review_unresolved_after_max_rounds(tmp_path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    base = [
        _Resp(None, [_Call("c", "edit", {"path": "a.py", "search": "hello", "replace": "hi"})]),
        _Resp(None, [_Call("cf", "finish", {"summary": "done"})]),
        _Resp(None, [_Call("rf", "finish", {"summary": "FAIL: 不行"})]),
    ]
    script = [_Resp(None, [_Call("p", "finish", {"summary": "计划"})])] + base * 2
    result = MultiAgentOrchestrator(_script_llm(script), build_default_registry(), max_review_rounds=2).run("x", _ctx(tmp_path))
    assert result.reason == "review_unresolved"

def test_orchestrator_accumulates_role_steps_and_cost(tmp_path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    llm = _script_llm([
        _Resp(None, [_Call("p", "finish", {"summary": "plan"})], cost_usd=0.10),
        _Resp(None, [_Call("c1", "edit", {"path": "a.py", "search": "hello", "replace": "hi"})], cost_usd=0.20),
        _Resp(None, [_Call("c2", "finish", {"summary": "done"})], cost_usd=0.30),
        _Resp(None, [_Call("r", "finish", {"summary": "PASS"})], cost_usd=0.40),
    ])

    result = MultiAgentOrchestrator(llm, build_default_registry()).run("change hello", _ctx(tmp_path))

    assert result.steps == 4
    assert result.cost_usd == 1.0
