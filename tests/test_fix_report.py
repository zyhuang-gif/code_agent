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
