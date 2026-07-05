"""Markdown fix report generation for build-fix runs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from agent.build_errors import classify_build_output
from agent.build_runner import BuildAttempt
from agent.loop import RunResult
from agent.trace import Trace

if TYPE_CHECKING:
    from agent.repair_memory import RepairMemoryCase


@dataclass(frozen=True)
class FixReport:
    task: str
    summary: str
    error_type: str = "unknown"
    root_cause: str = ""
    edited_files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    verification_status: str = "not_run"
    risks: list[str] = field(default_factory=list)
    initial_error_type: str = "unknown"
    initial_phase: str | None = None
    initial_evidence: list[str] = field(default_factory=list)
    final_error_type: str = "unknown"
    final_phase: str | None = None
    final_evidence: list[str] = field(default_factory=list)
    repair_memory_cases: list[str] = field(default_factory=list)


def _files_from_diff(diff: str) -> list[str]:
    files = []
    for match in re.finditer(r"diff --git a/(.*?) b/", diff):
        files.append(match.group(1))
    return sorted(dict.fromkeys(files))


def build_fix_report(
    task: str,
    result: RunResult,
    attempts: list[BuildAttempt],
    workspace: Path,
    initial_output: str = "",
    final_output: str = "",
    initial_attempts: list[BuildAttempt] | None = None,
    repair_memory_matches: list | None = None,
) -> FixReport:
    status = "not_run"
    if attempts:
        status = "passed" if attempts[-1].exit_code == 0 else "failed"
    risks = []
    if result.reason not in {"finished"}:
        risks.append(f"agent finished with reason: {result.reason}")
    if status != "passed":
        risks.append("verification did not pass")
    if not risks:
        risks.append("none detected")

    initial_attempt = attempts[0] if attempts else None
    final_attempt = attempts[-1] if attempts else None
    # use initial_attempts to find the first failing attempt for accurate phase/command
    initial_failure = next((a for a in (initial_attempts or []) if a.exit_code != 0), None)
    initial_summary = classify_build_output(
        initial_output,
        phase=initial_failure.phase if initial_failure else None,
        command=initial_failure.command if initial_failure else None,
    )
    final_summary = classify_build_output(
        final_output,
        phase=final_attempt.phase if final_attempt else None,
        command=final_attempt.command if final_attempt else None,
    ) if final_output else classify_build_output("")

    # Keep error_type and root_cause based on the initial summary for backward compatibility
    error_type = initial_summary.error_type
    root_cause = ""
    if error_type == "missing_header" and initial_summary.missing_header:
        root_cause = f"Header file '{initial_summary.missing_header}' not found — likely missing target_include_directories."
    elif error_type == "undefined_reference" and initial_summary.missing_symbol:
        root_cause = f"Undefined reference to '{initial_summary.missing_symbol}' — likely missing source file in target or missing target_link_libraries."
    elif error_type == "missing_target" and initial_summary.missing_target:
        root_cause = f"Target '{initial_summary.missing_target}' referenced but not defined — likely a typo or missing local target definition."
    elif error_type == "missing_package" and initial_summary.missing_package:
        root_cause = f"Package '{initial_summary.missing_package}' not found — check find_package or use vendored local target."
    elif error_type == "test_failure":
        root_cause = "CTest/verification failed — check the failing test and the corresponding implementation logic."
    elif error_type == "cmake_config_error":
        root_cause = "CMake configure step failed — inspect CMakeLists.txt syntax and generator settings."

    report = FixReport(
        task=task,
        summary=result.finish_summary or result.reason,
        error_type=error_type,
        root_cause=root_cause,
        edited_files=_files_from_diff(result.diff),
        commands=[attempt.command for attempt in attempts],
        verification_status=status,
        risks=risks,
        initial_error_type=initial_summary.error_type,
        initial_phase=initial_summary.phase,
        initial_evidence=initial_summary.evidence_lines,
        final_error_type=final_summary.error_type,
        final_phase=final_summary.phase,
        final_evidence=final_summary.evidence_lines,
        repair_memory_cases=[
            m.case.case_id for m in (repair_memory_matches or [])
        ],
    )
    return report


def _markdown(report: FixReport) -> str:
    lines = [
        "# Fix Report",
        "",
        f"Task: {report.task}",
        "",
        "## Error Type",
        "",
        report.error_type,
        "",
        "## Root Cause",
        "",
        report.root_cause or "not determined",
        "",
        "## Initial Failure",
        "",
        f"Type: {report.initial_error_type}",
        f"Phase: {report.initial_phase or 'unknown'}",
        "",
    ]
    lines.extend(f"- {line}" for line in report.initial_evidence or ["none"])
    lines.extend(
        [
            "",
            "## Summary",
            "",
            report.summary,
            "",
            "## Edited Files",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path in report.edited_files or ["none"])
    lines.extend(["", "## Verification", "", f"Status: {report.verification_status}", ""])
    lines.extend(f"- `{command}`" for command in report.commands or ["not run"])

    # Final failure section
    lines.extend(["", "## Final Failure", "", f"Type: {report.final_error_type}", f"Phase: {report.final_phase or 'unknown'}", ""])
    lines.extend(f"- {line}" for line in report.final_evidence or ["none"])

    # Repair memory section — always present
    lines.extend(["", "## Repair Memory Used", ""])
    if report.repair_memory_cases:
        lines.extend(f"- {case_id}" for case_id in report.repair_memory_cases)
    else:
        lines.append("- none")

    lines.extend(["", "## Risks", ""])
    lines.extend(f"- {risk}" for risk in report.risks)
    return "\n".join(lines) + "\n"


def write_fix_report(report: FixReport, path: Path, trace: Trace | None = None) -> None:
    path.write_text(_markdown(report), encoding="utf-8")
    if trace:
        trace.write(
            {
                "t": "fix_report",
                "task": report.task,
                "error_type": report.error_type,
                "root_cause": report.root_cause,
                "edited_files": report.edited_files,
                "verification_status": report.verification_status,
                "commands": report.commands,
                "repair_memory_cases": report.repair_memory_cases,
            }
        )
