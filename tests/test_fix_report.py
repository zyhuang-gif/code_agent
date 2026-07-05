import json
from pathlib import Path

from agent.build_runner import BuildAttempt
from agent.fix_report import FixReport, build_fix_report, write_fix_report
from agent.loop import RunResult
from agent.trace import Trace


def test_build_fix_report_lists_edited_files_and_verification(tmp_path: Path):
    result = RunResult(
        reason="finished",
        diff="diff --git a/CMakeLists.txt b/CMakeLists.txt\n--- a/CMakeLists.txt\n+++ b/CMakeLists.txt\n",
        messages=[],
        cost_usd=0.0,
        finish_summary="linked mathx",
        steps=3,
    )
    attempts = [BuildAttempt("cmake --build build", "build", 0, "ok")]

    report = build_fix_report("Fix build", result, attempts, tmp_path)

    assert report.task == "Fix build"
    assert report.verification_status == "passed"
    assert report.edited_files == ["CMakeLists.txt"]
    assert "linked mathx" in report.summary


def test_write_fix_report_writes_markdown_and_trace(tmp_path: Path):
    report = FixReport(
        task="Fix build",
        summary="done",
        edited_files=["CMakeLists.txt"],
        commands=["cmake --build build"],
        verification_status="passed",
        risks=["none detected"],
    )
    trace = Trace(tmp_path / "trace.jsonl")

    write_fix_report(report, tmp_path / "fix_report.md", trace)

    text = (tmp_path / "fix_report.md").read_text(encoding="utf-8")
    assert "# Fix Report" in text
    assert "CMakeLists.txt" in text
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert rows[-1]["t"] == "fix_report"


def test_build_fix_report_records_initial_and_final_failures(tmp_path: Path):
    result = RunResult(
        reason="finished_with_failing_tests",
        diff="",
        messages=[],
        cost_usd=0.0,
        finish_summary="tried include dir",
        steps=3,
    )
    attempts = [BuildAttempt("cmake --build build", "build", 1, "undefined reference to `mathx::add(int, int)'")]
    initial_output = "fatal error: mathx/add.hpp: No such file or directory"
    final_output = attempts[-1].output_preview

    report = build_fix_report("Fix build", result, attempts, tmp_path, initial_output, final_output)

    assert report.initial_error_type == "missing_header"
    assert report.final_error_type == "undefined_reference"
    assert report.final_phase == "build"
    assert "mathx/add.hpp" in "\n".join(report.initial_evidence)
    assert "mathx::add" in "\n".join(report.final_evidence)


def test_build_fix_report_uses_initial_attempts_for_phase_and_command(tmp_path: Path):
    result = RunResult(
        reason="finished_with_failing_tests",
        diff="",
        messages=[],
        cost_usd=0.0,
        finish_summary="tried fixing include",
        steps=3,
    )
    final_attempts = [BuildAttempt("cmake --build build", "build", 1, "undefined reference to `y'")]
    initial_attempts = [
        BuildAttempt("cmake -S . -B build", "configure", 0, "configured"),
        BuildAttempt("cmake --build build", "build", 1, "fatal error: mathx/add.hpp: No such file or directory"),
    ]
    initial_output = "configured\nfatal error: mathx/add.hpp: No such file or directory"
    final_output = "undefined reference to `y'"

    report = build_fix_report(
        "Fix build",
        result,
        final_attempts,
        tmp_path,
        initial_output,
        final_output,
        initial_attempts=initial_attempts,
    )

    assert report.initial_phase == "build"
    assert report.initial_error_type == "missing_header"
    assert report.final_error_type == "undefined_reference"
    assert report.final_phase == "build"


def test_write_fix_report_includes_initial_and_final_sections(tmp_path: Path):
    report = FixReport(
        task="Fix build",
        summary="not fixed",
        error_type="missing_header",
        root_cause="Header file missing.",
        edited_files=[],
        commands=["cmake --build build"],
        verification_status="failed",
        risks=["verification did not pass"],
        initial_error_type="missing_header",
        initial_phase="build",
        initial_evidence=["fatal error: mathx/add.hpp: No such file or directory"],
        final_error_type="undefined_reference",
        final_phase="build",
        final_evidence=["undefined reference to `mathx::add(int, int)'"],
    )

    write_fix_report(report, tmp_path / "fix_report.md")

    text = (tmp_path / "fix_report.md").read_text(encoding="utf-8")
    assert "## Initial Failure" in text
    assert "missing_header" in text
    assert "## Final Failure" in text
    assert "undefined_reference" in text
