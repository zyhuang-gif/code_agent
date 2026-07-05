from pathlib import Path

import pytest

from eval.spec_ab import (
    PROMPT_INJECTION,
    VARIANTS,
    build_agentspec_command,
    cleanup_agentspec_side_outputs,
    render_minimal_agents_md,
)


def test_variants_define_baseline_minimal_and_full():
    assert list(VARIANTS) == ["baseline", "agentspec-minimal", "agentspec-full"]
    assert VARIANTS["baseline"].requires_agentspec is False
    assert VARIANTS["baseline"].minimal is False
    assert VARIANTS["agentspec-minimal"].requires_agentspec is True
    assert VARIANTS["agentspec-minimal"].minimal is True
    assert VARIANTS["agentspec-full"].requires_agentspec is True
    assert VARIANTS["agentspec-full"].minimal is False
    assert PROMPT_INJECTION == "There is an AGENTS.md at repo root. Read it before you start."


def test_build_agentspec_command_uses_uv_project_and_no_llm(tmp_path: Path):
    work_root = tmp_path / "work"
    project = Path("D:/source/agent/agentspec")

    cmd = build_agentspec_command(work_root, project)

    assert cmd == [
        "uv",
        "run",
        "--project",
        str(project),
        "agentspec",
        "scan",
        str(work_root),
        "--write",
        "--force",
        "--no-llm",
    ]


def test_render_minimal_agents_md_keeps_only_commands_and_safety():
    full = """# AGENTS.md

<!-- agentspec:managed name="overview" -->
## Project Overview
Python
<!-- agentspec:end name="overview" -->

<!-- agentspec:managed name="architecture-notes" -->
## Architecture Notes
Lots of architecture.
<!-- agentspec:end name="architecture-notes" -->

<!-- agentspec:managed name="commands" -->
## Commands
- Use `pytest`.
<!-- agentspec:end name="commands" -->

<!-- agentspec:managed name="safety" -->
## Safety
- Do not run destructive commands.
<!-- agentspec:end name="safety" -->
"""

    minimal = render_minimal_agents_md(full)

    assert minimal.startswith("# AGENTS.md\n")
    assert "## Commands" in minimal
    assert "Use `pytest`" in minimal
    assert "## Safety" in minimal
    assert "destructive" in minimal
    assert "Project Overview" not in minimal
    assert "Architecture Notes" not in minimal


def test_render_minimal_agents_md_requires_both_blocks():
    full = """# AGENTS.md
<!-- agentspec:managed name="commands" -->
## Commands
<!-- agentspec:end name="commands" -->
"""

    with pytest.raises(ValueError, match="commands and safety"):
        render_minimal_agents_md(full)


def test_cleanup_agentspec_side_outputs_removes_only_generated_side_outputs(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("keep", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("remove", encoding="utf-8")
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "source-map.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_text("print('ok')\n", encoding="utf-8")

    cleanup_agentspec_side_outputs(tmp_path)

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".agent").exists()
    assert (tmp_path / "src" / "code.py").exists()
