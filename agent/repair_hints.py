"""Prompt hints for CMake/C++ build repair."""

from __future__ import annotations

from agent.build_errors import BuildErrorSummary
from agent.cmake_context import CMakeContext


def _context_files(context: CMakeContext | None) -> str:
    if not context:
        return "CMakeLists.txt"
    files = context.cmake_files or ["CMakeLists.txt"]
    return ", ".join(files[:5])


def render_repair_hints(summary: BuildErrorSummary, context: CMakeContext | None = None) -> str:
    lines = ["Repair hints:"]
    cmake_files = _context_files(context)

    if summary.error_type == "missing_header":
        lines.extend(
            [
                f"- Check target include directories in {cmake_files}.",
                "- Prefer target_include_directories(<target> PRIVATE/PUBLIC include).",
                "- Do not add global include_directories unless the project already uses that style.",
            ]
        )
    elif summary.error_type == "undefined_reference":
        lines.extend(
            [
                f"- Check whether the implementation source is listed in {cmake_files}.",
                "- Check whether the executable or test target links the local library target.",
                "- Prefer target_link_libraries(<target> PRIVATE <library>).",
            ]
        )
    elif summary.error_type == "missing_target":
        lines.extend(
            [
                f"- Check target names declared in {cmake_files}.",
                "- Correct the linked target name or define the missing local target.",
                "- Avoid inventing imported targets that are not declared or found.",
            ]
        )
    elif summary.error_type == "missing_package":
        lines.extend(
            [
                f"- Check find_package usage in {cmake_files}.",
                "- If the fixture provides a local/vendored dependency, prefer wiring that local target.",
                "- Do not install packages or fetch from the network in MVP eval tasks.",
            ]
        )
    elif summary.error_type == "test_failure":
        lines.extend(
            [
                "- Inspect the failing test and the smallest related implementation file.",
                "- Prefer fixing local logic over weakening tests unless the task clearly asks for tolerance.",
            ]
        )
    else:
        lines.extend(
            [
                f"- Inspect {cmake_files} and the source file named in the build output.",
                "- Make the smallest target-local CMake or C++ change that addresses the evidence.",
            ]
        )

    if context and context.targets:
        lines.append(f"- Known targets: {', '.join(context.targets)}.")
    return "\n".join(lines)
