from pathlib import Path
from agent.editor import EditResult
from agent.locator import Hit
from agent.profile import ProjectProfile
from agent.tools import RunContext, ToolRegistry, ToolResult, build_default_registry
from agent.trace import Trace
from agent.budget import Budget


class FakeLocator:
    def __init__(self): self.calls = []
    def search(self, pattern, glob=None):
        self.calls.append((pattern, glob)); return [Hit("a.py", 1, "needle")]
    def symbols(self, path): raise NotImplementedError


class FakeEditor:
    def edit(self, path, search, replace): return EditResult("ok", meta={"path": str(path)})


def ctx(tmp_path: Path, runner=None):
    locator = FakeLocator()
    context = RunContext(workspace=tmp_path, profile=ProjectProfile(ignore=["node_modules"], max_file_bytes=10), trace=Trace(tmp_path / "trace.jsonl"), budget=Budget(), locator=locator, editor=FakeEditor(), runner=runner)
    return context, locator


def test_tools_list_read_grep_edit_run_finish(tmp_path: Path):
    (tmp_path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    ignored = tmp_path / "node_modules"; ignored.mkdir(); (ignored / "x.js").write_text("x", encoding="utf-8")
    def runner(cmd, cwd=None, timeout=None, allow_network=False):
        assert cwd == tmp_path; assert timeout == 5; assert allow_network is False
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}
    context, locator = ctx(tmp_path, runner=runner)
    registry = build_default_registry()
    assert "node_modules" not in registry.run("list_dir", {"path": "."}, context).content
    assert "1: one" in registry.run("read_file", {"path": "a.py", "start_line": 1, "end_line": 1}, context).content
    assert registry.run("grep", {"pattern": "needle", "glob": "*.py"}, context).content == "a.py:1:needle"
    assert locator.calls == [("needle", "*.py")]
    assert not registry.run("edit", {"path": "a.py", "search": "one", "replace": "uno"}, context).is_error
    assert "exit_code=0" in registry.run("run_command", {"cmd": "pytest", "timeout": 5}, context).content
    assert registry.run("finish", {"summary": "done"}, context).meta["finish"] is True
    assert registry.to_openai_tools()[0]["type"] == "function"
from agent.tools import build_default_registry


def test_default_tool_schemas_are_precise_for_llm_function_calling():
    registry = build_default_registry()
    edit_schema = registry.get("edit").parameters
    assert edit_schema["required"] == ["path", "search", "replace"]
    assert edit_schema["additionalProperties"] is False
    assert set(edit_schema["properties"]) == {"path", "search", "replace"}

    read_schema = registry.get("read_file").parameters
    assert read_schema["required"] == ["path"]
    assert read_schema["additionalProperties"] is False
    assert read_schema["properties"]["start_line"]["type"] == "integer"
    assert read_schema["properties"]["end_line"]["type"] == "integer"

    run_schema = registry.get("run_command").parameters
    assert run_schema["required"] == ["cmd"]
    assert run_schema["additionalProperties"] is False
    assert run_schema["properties"]["allow_network"]["type"] == "boolean"

    finish_schema = registry.get("finish").parameters
    assert finish_schema["required"] == ["summary"]


def test_run_command_passes_allow_network_policy_to_runner(tmp_path: Path):
    calls = []
    def runner(cmd, **kwargs):
        calls.append(kwargs)
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}
    context, _ = ctx(tmp_path, runner=runner)
    registry = build_default_registry()

    registry.run("run_command", {"cmd": "pytest"}, context)
    registry.run("run_command", {"cmd": "pytest", "allow_network": True}, context)

    assert calls[0]["allow_network"] is False
    assert calls[1]["allow_network"] is True

