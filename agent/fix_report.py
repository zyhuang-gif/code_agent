"""Markdown fix report generation for build-fix runs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from agent.build_runner import BuildAttempt
from agent.loop import RunResult
from agent.trace import Trace


@dataclass(frozen=True)
class FixReport:
    task: str
    summary: str
    edited_files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    verification_status: str = "not_run"
    risks: list[str] = field(default_factory=list)


def _files_from_diff(diff: str) -> list[str]:
    files = []
    for match in re.finditer(r"diff --git a/(.*?) b/", diff):
        files.append(match.group(1))
    return sorted(dict.fromkeys(files))


def build_fix_report(task: str, result: RunResult, attempts: list[BuildAttempt], workspace: Path) -> FixReport:
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
    return FixReport(
        task=task,
        summary=result.finish_summary or result.reason,
        edited_files=_files_from_diff(result.diff),
        commands=[attempt.command for attempt in attempts],
        verification_status=status,
        risks=risks,
    )


def _markdown(report: FixReport) -> str:
    lines = [
        "# Fix Report",
        "",
        f"Task: {report.task}",
        "",
        "## Summary",
        "",
        report.summary,
        "",
        "## Edited Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in report.edited_files or ["none"])
    lines.extend(["", "## Verification", "", f"Status: {report.verification_status}", ""])
    lines.extend(f"- `{command}`" for command in report.commands or ["not run"])
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
                "edited_files": report.edited_files,
                "verification_status": report.verification_status,
                "commands": report.commands,
            }
        )
