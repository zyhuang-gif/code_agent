from pathlib import Path
from agent.editor import SearchReplaceEditor
from agent.profile import ProjectProfile


def test_editor_replaces_unique_search(tmp_path: Path):
    path = tmp_path / "a.py"
    path.write_text("hello\nworld\n", encoding="utf-8")
    result = SearchReplaceEditor(ProjectProfile()).edit(path, "world", "Codex")
    assert not result.is_error
    assert path.read_text(encoding="utf-8") == "hello\nCodex\n"


def test_editor_missing_or_ambiguous_search_does_not_modify(tmp_path: Path):
    path = tmp_path / "a.py"
    path.write_text("x\nx\n", encoding="utf-8")
    assert SearchReplaceEditor(ProjectProfile()).edit(path, "y", "z").is_error
    assert path.read_text(encoding="utf-8") == "x\nx\n"
    assert SearchReplaceEditor(ProjectProfile()).edit(path, "x", "z").is_error
    assert path.read_text(encoding="utf-8") == "x\nx\n"


def test_editor_runs_injected_syntax_check_and_keeps_failure_content(tmp_path: Path):
    path = tmp_path / "a.py"
    path.write_text("ok\n", encoding="utf-8")
    calls = []
    def runner(cmd, cwd=None, timeout=None):
        calls.append((cmd, cwd, timeout))
        return {"exit_code": 1, "stderr": "bad syntax", "stdout": ""}
    profile = ProjectProfile(syntax_check={".py": "python -m py_compile {file}"})
    result = SearchReplaceEditor(profile, runner=runner).edit(path, "ok", "bad")
    assert result.is_error
    assert "bad syntax" in result.content
    assert path.read_text(encoding="utf-8") == "ok\n"
    assert calls
