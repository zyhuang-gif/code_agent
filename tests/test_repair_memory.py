"""Tests for agent/repair_memory.py."""

import json
from pathlib import Path

from agent.fix_report import FixReport
from agent.build_errors import BuildErrorSummary
from agent.repair_memory import (
    RepairMemoryCase,
    RepairMemoryMatch,
    append_repair_case,
    extract_repair_case,
    extract_repair_case_from_artifacts,
    load_repair_memory,
    match_repair_memory,
    render_repair_memory,
    repair_memory_jsonl,
    select_cmake_repair_memory,
)


def test_repair_memory_case_fields():
    case = RepairMemoryCase(
        case_id="abc12345",
        schema_version=1,
        task="Fix build",
        error_type="missing_header",
        root_cause="Header file not found",
        edited_files=["CMakeLists.txt"],
        verification_status="passed",
        verification_commands=["cmake --build build"],
        initial_phase="build",
        final_phase="build",
        evidence=["fatal error: mathx/add.hpp: No such file or directory"],
        diff_excerpt="+target_include_directories(app PRIVATE include)",
        source="eval/tasks_cmake/c01_missing_project_header",
    )
    assert case.case_id == "abc12345"
    assert case.schema_version == 1
    assert case.error_type == "missing_header"
    assert case.verification_status == "passed"


def test_repair_memory_match_fields():
    case = RepairMemoryCase(
        case_id="abc",
        schema_version=1,
        task="t",
        error_type="missing_header",
        root_cause="",
        edited_files=[],
        verification_status="passed",
        verification_commands=[],
        initial_phase="",
        final_phase="",
        evidence=[],
        diff_excerpt="",
        source="",
    )
    match = RepairMemoryMatch(case=case, score=0.85)
    assert match.case is case
    assert match.score == 0.85


def test_load_repair_memory_returns_empty_list_for_missing_file(tmp_path: Path):
    result = load_repair_memory(tmp_path / "nonexistent.jsonl")
    assert result == []


def test_load_repair_memory_reads_jsonl(tmp_path: Path):
    path = tmp_path / "memory.jsonl"
    cases = [
        {"case_id": "a", "schema_version": 1, "task": "t1", "error_type": "missing_header"},
        {"case_id": "b", "schema_version": 1, "task": "t2", "error_type": "undefined_reference"},
    ]
    with path.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case) + "\n")

    result = load_repair_memory(path)
    assert len(result) == 2
    assert result[0].case_id == "a"
    assert result[0].error_type == "missing_header"
    assert result[1].case_id == "b"


def test_load_repair_memory_skips_malformed_lines(tmp_path: Path):
    path = tmp_path / "memory.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write('{"case_id": "ok", "schema_version": 1, "task": "t", "error_type": "x"}\n')
        f.write("not json\n")
        f.write('{"case_id": "ok2", "schema_version": 1, "task": "t2", "error_type": "y"}\n')

    result = load_repair_memory(path)
    assert len(result) == 2
    assert result[0].case_id == "ok"
    assert result[1].case_id == "ok2"


def test_append_repair_case_writes_jsonl(tmp_path: Path):
    path = tmp_path / "memory.jsonl"
    case = RepairMemoryCase(
        case_id="abc",
        schema_version=1,
        task="Fix build",
        error_type="missing_header",
        root_cause="bad include",
        edited_files=["CMakeLists.txt"],
        verification_status="passed",
        verification_commands=["cmake --build build"],
        initial_phase="build",
        final_phase="build",
        evidence=["error line"],
        diff_excerpt="+target_include",
        source="eval/c01",
    )

    append_repair_case(path, case)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["case_id"] == "abc"
    assert data["verification_status"] == "passed"


def test_append_repair_case_dedupes_by_case_id(tmp_path: Path):
    path = tmp_path / "memory.jsonl"
    case1 = RepairMemoryCase(
        case_id="dup", schema_version=1, task="t1", error_type="e1",
        root_cause="", edited_files=[], verification_status="passed",
        verification_commands=[], initial_phase="", final_phase="",
        evidence=[], diff_excerpt="", source="",
    )
    case2 = RepairMemoryCase(
        case_id="dup", schema_version=1, task="t1", error_type="e1",
        root_cause="", edited_files=[], verification_status="failed",
        verification_commands=[], initial_phase="", final_phase="",
        evidence=[], diff_excerpt="", source="",
    )

    append_repair_case(path, case1)
    append_repair_case(path, case2)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # deduped


def test_append_repair_case_allows_different_case_ids(tmp_path: Path):
    path = tmp_path / "memory.jsonl"
    case1 = RepairMemoryCase(
        case_id="a", schema_version=1, task="t1", error_type="e1",
        root_cause="", edited_files=[], verification_status="passed",
        verification_commands=[], initial_phase="", final_phase="",
        evidence=[], diff_excerpt="", source="",
    )
    case2 = RepairMemoryCase(
        case_id="b", schema_version=1, task="t2", error_type="e2",
        root_cause="", edited_files=[], verification_status="passed",
        verification_commands=[], initial_phase="", final_phase="",
        evidence=[], diff_excerpt="", source="",
    )

    append_repair_case(path, case1)
    append_repair_case(path, case2)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_extract_repair_case_from_fix_report_and_diff(tmp_path: Path):
    report = FixReport(
        task="Fix CMake build",
        summary="added include dir",
        error_type="missing_header",
        root_cause="Header file 'mathx/add.hpp' not found — likely missing target_include_directories.",
        edited_files=["CMakeLists.txt"],
        commands=["cmake --build build"],
        verification_status="passed",
        initial_error_type="missing_header",
        initial_phase="build",
        initial_evidence=["fatal error: mathx/add.hpp: No such file or directory"],
        final_error_type="unknown",
        final_phase="build",
        final_evidence=[],
    )
    diff = (
        "diff --git a/CMakeLists.txt b/CMakeLists.txt\n"
        "--- a/CMakeLists.txt\n"
        "+++ b/CMakeLists.txt\n"
        "@@ -1 +1,2 @@\n"
        " add_executable(app src/main.cpp)\n"
        "+target_include_directories(app PRIVATE include)\n"
    )
    source = "eval/tasks_cmake/c01_missing_project_header"

    case = extract_repair_case(report, diff, source)

    assert case.schema_version == 1
    assert case.error_type == "missing_header"
    assert case.root_cause == report.root_cause
    assert case.edited_files == ["CMakeLists.txt"]
    assert case.verification_status == "passed"
    assert case.verification_commands == ["cmake --build build"]
    assert case.initial_phase == "build"
    assert case.final_phase == "build"
    assert case.evidence == ["fatal error: mathx/add.hpp: No such file or directory"]
    assert "+target_include_directories" in case.diff_excerpt
    assert case.source == source
    assert case.task == "Fix CMake build"
    assert len(case.case_id) == 8  # SHA256 first 8 hex chars


def test_extract_repair_case_generates_deterministic_case_id(tmp_path: Path):
    report1 = FixReport(
        task="Fix build", summary="", error_type="missing_header",
        root_cause="", edited_files=["CMakeLists.txt"], commands=[],
        verification_status="passed",
    )
    report2 = FixReport(
        task="Fix build", summary="", error_type="missing_header",
        root_cause="", edited_files=["CMakeLists.txt"], commands=[],
        verification_status="passed",
    )

    case1 = extract_repair_case(report1, "", "")
    case2 = extract_repair_case(report2, "", "")

    assert case1.case_id == case2.case_id  # same inputs → same id


def test_extract_repair_case_truncates_diff_excerpt(tmp_path: Path):
    report = FixReport(
        task="t", summary="", error_type="e", root_cause="",
        edited_files=[], commands=[], verification_status="passed",
    )
    long_diff = "x" * 5000

    case = extract_repair_case(report, long_diff, "")
    assert len(case.diff_excerpt) <= 2000


def test_repair_memory_jsonl_returns_default_path():
    repo = Path("/some/repo")
    assert repair_memory_jsonl(repo) == Path("/some/repo/repair_memory.jsonl")


# ---------------------------------------------------------------------------
#  Matching tests
# ---------------------------------------------------------------------------


def _make_case(**overrides) -> RepairMemoryCase:
    """Factory for RepairMemoryCase with sensible defaults."""
    defaults = {
        "case_id": "test0001",
        "schema_version": 1,
        "task": "Fix build",
        "error_type": "missing_header",
        "root_cause": "Missing target_include_directories for include/.",
        "edited_files": ["CMakeLists.txt"],
        "verification_status": "passed",
        "verification_commands": ["cmake --build build"],
        "initial_phase": "build",
        "final_phase": "build",
        "evidence": ["fatal error: mathx/add.hpp: No such file or directory"],
        "diff_excerpt": "+target_include_directories(app PRIVATE include)",
        "source": "eval/tasks_cmake/c01",
    }
    defaults.update(overrides)
    return RepairMemoryCase(**defaults)


def test_match_exact_error_type_scores_high():
    memory = [
        _make_case(case_id="a", error_type="missing_header"),
        _make_case(case_id="b", error_type="undefined_reference", evidence=["undefined reference to `foo'"]),
    ]
    error = BuildErrorSummary(error_type="missing_header", message="fatal error: mathx/add.hpp: No such file or directory", evidence_lines=[])

    matches = match_repair_memory(memory, error)
    assert len(matches) >= 1
    assert matches[0].case.case_id == "a"
    assert matches[0].score >= 40.0


def test_match_excludes_failed_cases():
    memory = [
        _make_case(case_id="a", verification_status="passed"),
        _make_case(case_id="b", verification_status="failed"),
    ]
    error = BuildErrorSummary(error_type="missing_header", message="fatal error: x", evidence_lines=[])

    matches = match_repair_memory(memory, error)
    case_ids = {m.case.case_id for m in matches}
    assert "a" in case_ids
    assert "b" not in case_ids


def test_match_respects_max_matches():
    memory = [_make_case(case_id=f"c{i}") for i in range(5)]
    error = BuildErrorSummary(error_type="missing_header", message="fatal error: x", evidence_lines=[])

    matches = match_repair_memory(memory, error, max_matches=2)
    assert len(matches) == 2


def test_match_keyword_overlap_boosts_score():
    memory = [
        _make_case(case_id="a", evidence=["mathx/add.hpp not found"], root_cause="add.hpp missing"),
        _make_case(case_id="b", evidence=["unrelated.cpp error"], root_cause="something else"),
    ]
    error = BuildErrorSummary(
        error_type="missing_header",
        message="fatal error: add.hpp: No such file or directory",
        missing_header="add.hpp",
        evidence_lines=["fatal error: add.hpp: No such file or directory"],
    )

    matches = match_repair_memory(memory, error)
    scores = {m.case.case_id: m.score for m in matches}
    assert scores["a"] > scores["b"]


def test_match_no_passed_cases_returns_empty():
    memory = [
        _make_case(case_id="a", verification_status="failed"),
    ]
    error = BuildErrorSummary(error_type="missing_header", message="x", evidence_lines=[])
    matches = match_repair_memory(memory, error)
    assert matches == []


def test_render_repair_memory_empty_matches():
    result = render_repair_memory([])
    assert result == ""


def test_render_repair_memory_includes_case_info():
    case = _make_case(case_id="abc12345", error_type="missing_header")
    matches = [RepairMemoryMatch(case=case, score=85.0)]
    result = render_repair_memory(matches)

    assert "Relevant repair memory:" in result
    assert "Case 1" in result
    assert "abc12345" in result
    assert "score: 85.0" in result
    assert "missing_header" in result
    assert "target_include_directories" in result


def test_select_cmake_repair_memory_loads_and_matches(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    jsonl_path = repair_memory_jsonl(repo)
    case = _make_case(case_id="mem01", error_type="missing_header")
    append_repair_case(jsonl_path, case)

    error = BuildErrorSummary(
        error_type="missing_header",
        message="fatal error: add.hpp: No such file or directory",
        missing_header="add.hpp",
        evidence_lines=["fatal error: add.hpp: No such file or directory"],
    )

    matches = select_cmake_repair_memory(repo, error)
    assert len(matches) == 1
    assert matches[0].case.case_id == "mem01"


def test_select_cmake_repair_memory_missing_file_returns_empty(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    error = BuildErrorSummary(error_type="missing_header", message="x", evidence_lines=[])
    matches = select_cmake_repair_memory(repo, error)
    assert matches == []


# ---------------------------------------------------------------------------
#  Artifact-based extraction tests
# ---------------------------------------------------------------------------


def test_extract_repair_case_from_artifacts_reads_report_and_diff(tmp_path: Path):
    """从 fix_report.md + final.diff + trace 提取 case。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    report_path = workspace / "fix_report.md"
    report_path.write_text(
        "# Fix Report\n\n"
        "Task: Fix CMake build\n\n"
        "## Error Type\n\n"
        "missing_header\n\n"
        "## Root Cause\n\n"
        "Header file 'mathx/add.hpp' not found — likely missing target_include_directories.\n\n"
        "## Edited Files\n\n"
        "- `CMakeLists.txt`\n\n"
        "## Verification\n\n"
        "Status: passed\n"
        "- `cmake --build build`\n\n"
        "## Repair Memory Used\n\n"
        "- none\n\n", encoding="utf-8",
    )

    diff_path = workspace / "final.diff"
    diff_path.write_text("+target_include_directories(app PRIVATE include)\n", encoding="utf-8")

    case = extract_repair_case_from_artifacts(workspace, source="eval/c01")

    assert case.task == "Fix CMake build"
    assert case.error_type == "missing_header"
    assert "Header file" in case.root_cause
    assert case.edited_files == ["CMakeLists.txt"]
    assert case.verification_status == "passed"
    assert case.verification_commands == ["cmake --build build"]
    assert "target_include_directories" in case.diff_excerpt
    assert case.source == "eval/c01"


def test_extract_repair_case_from_artifacts_reads_trace_evidence(tmp_path: Path):
    """从 trace JSONL 补充 evidence。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    (workspace / "fix_report.md").write_text(
        "# Fix Report\n\nTask: t\n\n## Error Type\n\nmissing_header\n\n"
        "## Root Cause\n\nnot determined\n\n"
        "## Edited Files\n\n- `none`\n\n"
        "## Verification\n\nStatus: passed\n\n"
        "## Repair Memory Used\n\n- none\n\n", encoding="utf-8",
    )
    (workspace / "final.diff").write_text("+ dummy\n", encoding="utf-8")

    trace_path = workspace.parent / f"{workspace.name}.trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        '{"t": "build_error_summary", "error_type": "missing_header", "message": "x", '
        '"missing_header": "mathx/add.hpp", "evidence_lines": ["fatal error: mathx/add.hpp: No such file or directory"]}\n'
        '{"t": "fix_report", "task": "Fix CMake build", "error_type": "missing_header", '
        '"root_cause": "Header file not found", "edited_files": ["CMakeLists.txt"], '
        '"verification_status": "passed", "commands": ["cmake --build build"]}\n',
        encoding="utf-8",
    )

    case = extract_repair_case_from_artifacts(
        workspace, trace_path=trace_path, source="trace-test",
    )

    assert case.task == "Fix CMake build"
    assert case.error_type == "missing_header"
    assert case.root_cause == "Header file not found"
    assert case.edited_files == ["CMakeLists.txt"]
    assert case.verification_status == "passed"
    assert case.verification_commands == ["cmake --build build"]
    assert "mathx/add.hpp" in "\n".join(case.evidence)
    assert case.diff_excerpt == "+ dummy\n"
    assert case.source == "trace-test"


def test_extract_repair_case_from_artifacts_missing_files_returns_minimal(tmp_path: Path):
    """所有文件缺失时返回最小可行 case。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # 不创建任何文件

    case = extract_repair_case_from_artifacts(workspace, source="empty")

    assert case.task == ""
    assert case.error_type == "unknown"
    assert case.source == "empty"
