"""Classify common CMake/C++ build failures."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


MISSING_HEADER_RE = re.compile(r"fatal error:\s*([^:\n]+):\s*No such file or directory", re.IGNORECASE)
UNDEFINED_REFERENCE_RE = re.compile(r"undefined reference to [`']([^`'\n]+)[`']", re.IGNORECASE)
MISSING_PACKAGE_RE = re.compile(r'provided by "([A-Za-z0-9_.:+-]+)"', re.IGNORECASE)
MISSING_TARGET_RE = re.compile(r'Target "([^"]+)" links to:\s*([A-Za-z0-9_.:+-]+)\s*but the target was not found', re.IGNORECASE)


@dataclass(frozen=True)
class BuildErrorSummary:
    error_type: str
    message: str
    evidence_lines: list[str] = field(default_factory=list)
    missing_header: str | None = None
    missing_symbol: str | None = None
    missing_package: str | None = None
    missing_target: str | None = None
    source_file: str | None = None
    target: str | None = None
    suggested_files: list[str] = field(default_factory=list)


def _evidence(output: str, needle: str | None = None, limit: int = 6) -> list[str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if needle:
        matched = [line for line in lines if needle.lower() in line.lower()]
        if matched:
            return matched[:limit]
    return lines[:limit]


def _source_file_from_output(output: str) -> str | None:
    match = re.search(r"([A-Za-z0-9_./\\-]+\.(?:cpp|cc|cxx|c|hpp|h))", output)
    return match.group(1).replace("\\", "/") if match else None


def classify_build_output(output: str) -> BuildErrorSummary:
    text = output or ""

    header = MISSING_HEADER_RE.search(text)
    if header:
        missing_header = header.group(1).strip()
        return BuildErrorSummary(
            error_type="missing_header",
            message=header.group(0).strip(),
            evidence_lines=_evidence(text, "fatal error"),
            missing_header=missing_header,
            source_file=_source_file_from_output(text),
            suggested_files=["CMakeLists.txt"],
        )

    missing_target = MISSING_TARGET_RE.search(text)
    if missing_target:
        target = missing_target.group(1).strip()
        linked = missing_target.group(2).strip()
        return BuildErrorSummary(
            error_type="missing_target",
            message=missing_target.group(0).strip(),
            evidence_lines=_evidence(text, "target was not found"),
            missing_target=linked,
            target=target,
            suggested_files=["CMakeLists.txt"],
        )

    package = MISSING_PACKAGE_RE.search(text)
    if package:
        name = package.group(1).strip()
        return BuildErrorSummary(
            error_type="missing_package",
            message=package.group(0).strip(),
            evidence_lines=_evidence(text, "Could not find"),
            missing_package=name,
            suggested_files=["CMakeLists.txt", "vcpkg.json", "CMakePresets.json"],
        )

    symbol = UNDEFINED_REFERENCE_RE.search(text)
    if symbol:
        missing_symbol = symbol.group(1).strip()
        return BuildErrorSummary(
            error_type="undefined_reference",
            message=symbol.group(0).strip(),
            evidence_lines=_evidence(text, "undefined reference"),
            missing_symbol=missing_symbol,
            source_file=_source_file_from_output(text),
            suggested_files=["CMakeLists.txt"],
        )

    if "CMake Error" in text:
        return BuildErrorSummary(
            error_type="cmake_config_error",
            message="CMake configure failed.",
            evidence_lines=_evidence(text, "CMake Error"),
            suggested_files=["CMakeLists.txt", "CMakePresets.json"],
        )

    if "FAILED" in text or "failed" in text:
        return BuildErrorSummary(
            error_type="test_failure",
            message="Configured test command failed.",
            evidence_lines=_evidence(text, "fail"),
        )

    return BuildErrorSummary(
        error_type="unknown",
        message="Build output did not match a known CMake Build-Fix pattern.",
        evidence_lines=_evidence(text),
    )
