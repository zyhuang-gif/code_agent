"""Tests for agent/repair_memory.py."""

import json
from pathlib import Path

from agent.fix_report import FixReport
from agent.repair_memory import (
    RepairMemoryCase,
    RepairMemoryMatch,
    append_repair_case,
    extract_repair_case,
    load_repair_memory,
    repair_memory_jsonl,
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
