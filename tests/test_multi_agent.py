from pathlib import Path

from agent.multi_agent import NoOpCheckpoint, run_planner


class _Call:
    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args


class _Resp:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls
        self.assistant_message = {}
        self.prompt_tokens = 1
        self.completion_tokens = 1
        self.cost_usd = 0.0


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

    plan = run_planner(PlanLLM(), "实现 f", _ctx(tmp_path))
    assert plan == "改 a.py 的 f"
    assert seen["names"] == {"list_dir", "read_file", "grep", "finish"}
