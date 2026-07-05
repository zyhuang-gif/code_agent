"""CMake-specific task prompt enrichment."""

from __future__ import annotations

from pathlib import Path

from agent.build_errors import BuildErrorSummary, classify_build_output
from agent.build_runner import BuildAttempt, summarize_cmake_attempts
from agent.cmake_context import CMakeContext, render_cmake_context, scan_cmake_context
from agent.profile import ProjectProfile
from agent.repair_hints import render_repair_hints
from agent.trace import Trace


def _render_error_summary(output: str, phase: str | None = None, command: str | None = None) -> str:
    summary = classify_build_output(output, phase=phase, command=command)
    lines = [
        "Build error summary:",
        f"- type: {summary.error_type}",
        f"- message: {summary.message}",
    ]
    if summary.missing_header:
        lines.append(f"- missing header: {summary.missing_header}")
    if summary.missing_symbol:
        lines.append(f"- missing symbol: {summary.missing_symbol}")
    if summary.missing_package:
        lines.append(f"- missing package: {summary.missing_package}")
    if summary.missing_target:
        lines.append(f"- missing target: {summary.missing_target}")
    if summary.evidence_lines:
        lines.append("- evidence:")
        lines.extend(f"  - {line}" for line in summary.evidence_lines[:5])
    return "\n".join(lines)


def _render_attempts(attempts: list[BuildAttempt]) -> str:
    if not attempts:
        return "Initial verification attempts: none"
    lines = ["Initial verification attempts:"]
    for attempt in attempts:
        lines.append(f"- {attempt.phase}: exit_code={attempt.exit_code} command={attempt.command}")
        if attempt.output_preview:
            lines.append(f"  output: {attempt.output_preview}")
    return "\n".join(lines)


def _write_attempt_trace(attempts: list[BuildAttempt], trace: Trace | None) -> None:
    if trace is None:
        return
    summary = summarize_cmake_attempts(attempts)
    trace.write({"t": "cmake_attempt_summary", **summary})


def _write_context_trace(context: CMakeContext, trace: Trace | None) -> None:
    if trace is None:
        return
    trace.write({
        "t": "cmake_context",
        "cmake_files": context.cmake_files,
        "presets": context.presets,
        "targets": context.targets,
        "packages": context.packages,
        "source_dirs": context.source_dirs,
        "include_dirs": context.include_dirs,
        "test_dirs": context.test_dirs,
    })


def _write_error_trace(summary: BuildErrorSummary, trace: Trace | None) -> None:
    if trace is None:
        return
    trace.write({
        "t": "build_error_summary",
        "error_type": summary.error_type,
        "message": summary.message,
        "missing_header": summary.missing_header,
        "missing_symbol": summary.missing_symbol,
        "missing_package": summary.missing_package,
        "missing_target": summary.missing_target,
        "source_file": summary.source_file,
        "target": summary.target,
        "evidence_lines": summary.evidence_lines[:5],
    })


def build_cmake_task_prompt(
    task: str,
    workspace: str | Path,
    profile: ProjectProfile,
    initial_output: str = "",
    trace: Trace | None = None,
    initial_attempts: list[BuildAttempt] | None = None,
) -> str:
    context = scan_cmake_context(Path(workspace), profile)
    attempts = initial_attempts or []
    if attempts and not initial_output:
        initial_output = summarize_cmake_attempts(attempts)["combined_output"]
    first_failure = next((attempt for attempt in attempts if attempt.exit_code != 0), None)
    summary = classify_build_output(
        initial_output,
        phase=first_failure.phase if first_failure else None,
        command=first_failure.command if first_failure else None,
    )
    _write_context_trace(context, trace)
    _write_error_trace(summary, trace)
    _write_attempt_trace(attempts, trace)
    return "\n\n".join(
        [
            f"Task: {task}",
            render_cmake_context(context),
            _render_attempts(attempts),
            _render_error_summary(
                initial_output,
                phase=first_failure.phase if first_failure else None,
                command=first_failure.command if first_failure else None,
            ),
            render_repair_hints(summary, context),
            (
                "CMake Build-Fix rules:\n"
                "- Inspect relevant CMake and C++ files before editing.\n"
                "- Prefer target-based CMake fixes such as target_include_directories and target_link_libraries.\n"
                "- Re-run the configured CMake command with run_command before finish.\n"
                "- Do not install packages or fetch from network.\n"
                "- Keep changes narrow and explain verification in finish summary."
            ),
        ]
    )
