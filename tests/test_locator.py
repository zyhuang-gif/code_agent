from pathlib import Path
import pytest
from agent.locator import GrepLocator
from agent.profile import ProjectProfile


def test_grep_locator_search_returns_hits(tmp_path: Path):
    (tmp_path / "a.py").write_text("one\nneedle here\n", encoding="utf-8")
    locator = GrepLocator(tmp_path, ProjectProfile())
    hits = locator.search("needle")
    assert len(hits) == 1
    assert hits[0].path == "a.py"
    assert hits[0].line_no == 2
    assert hits[0].line == "needle here"


def test_grep_locator_glob_and_ignore(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("needle\n", encoding="utf-8")
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "b.py").write_text("needle\n", encoding="utf-8")
    locator = GrepLocator(tmp_path, ProjectProfile(ignore=["node_modules"]))
    assert [hit.path for hit in locator.search("needle", glob="*.py")] == ["a.py"]


def test_grep_locator_symbols_not_implemented(tmp_path: Path):
    with pytest.raises(NotImplementedError):
        GrepLocator(tmp_path, ProjectProfile()).symbols("a.py")
