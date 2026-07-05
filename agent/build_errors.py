"""Classify common CMake/C++ build failures."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


MISSING_HEADER_RE = re.compile(r"fatal error:\s*([^:\n]+):\s*No such file or directory", re.IGNORECASE)
UNDEFINED_REFERENCE_RE = re.compile(r"undefined reference to [`']([^`'\n]+)[`']", re.IGNORECASE)
MISSING_PACKAGE_RE = re.compile(r'provided by "([A-Za-z0-9_.:+-]+)"', re.IGNORECASE)
MISSING_TARGET_RE = re.compile(r'Target "([^"]+)" links to:\s*([A-Za-z0-9_.:+-]+)\s*but the target was not found', re.IGNORECASE)

MSVC_MISSING_HEADER_RE = re.compile(
    r"(?P<source>[A-Za-z0-9_./\\:-]+\.(?:cpp|cc|cxx|c|hpp|h))\(\d+\):\s*fatal error C1083:\s*Cannot open include file:\s*'(?P<header>[^']+)'",
    re.IGNORECASE,
)
CMAKE_COULD_NOT_FIND_RE = re.compile(r"Could NOT find\s+([A-Za-z0-9_.:+-]+)", re.IGNORECASE)
GNU_LINK_LIBRARY_RE = re.compile(r"cannot find -l([A-Za-z0-9_.+-]+?):", re.IGNORECASE)
MSVC_LINK_LIBRARY_RE = re.compile(r"LNK1104:\s*cannot open file '([^']+)'", re.IGNORECASE)
MSVC_UNRESOLVED_RE = re.compile(r"LNK(?:2019|2001):\s*unresolved external symbol\s+\"?([^\"\n]+)\"?", re.IGNORECASE)
MISSING_SOURCE_RE = re.compile(r"['\"]([^'\"]+\.(?:cpp|cc|cxx|c|h|hpp))['\"].*missing and no known rule to make it", re.IGNORECASE)
CTEST_FAILED_RE = re.compile(r"\d+\s+-\s+([A-Za-z0-9_.:+-]+)\s+\(Failed\)", re.IGNORECASE)


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
    phase: str | None = None
    tool: str | None = None
    missing_library: str | None = None
    missing_source: str | None = None
    test_name: str | None = None
    failing_command: str | None = None


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


def _base_kwargs(phase: str | None, command: str | None) -> dict[str, str | None]:
    return {"phase": phase, "failing_command": command}


def classify_build_output(output: str, phase: str | None = None, command: str | None = None) -> BuildErrorSummary:
    text = output or ""
    base = _base_kwargs(phase, command)

    # --- new patterns first, check before broad branches ---

    msvc_header = MSVC_MISSING_HEADER_RE.search(text)
    if msvc_header:
        missing_header = msvc_header.group("header").strip()
        source_file = msvc_header.group("source").strip().replace("\\", "/")
        return BuildErrorSummary(
            error_type="missing_header",
            message=msvc_header.group(0).strip(),
            evidence_lines=_evidence(text, "fatal error"),
            missing_header=missing_header,
            source_file=source_file,
            suggested_files=["CMakeLists.txt"],
            **base,
        )

    gnu_link = GNU_LINK_LIBRARY_RE.search(text)
    if gnu_link:
        lib = gnu_link.group(1).strip()
        return BuildErrorSummary(
            error_type="link_library_missing",
            message=gnu_link.group(0).strip(),
            evidence_lines=_evidence(text, "cannot find"),
            missing_library=lib,
            suggested_files=["CMakeLists.txt"],
            **base,
        )

    msvc_link = MSVC_LINK_LIBRARY_RE.search(text)
    if msvc_link:
        lib = msvc_link.group(1).strip()
        return BuildErrorSummary(
            error_type="link_library_missing",
            message=msvc_link.group(0).strip(),
            evidence_lines=_evidence(text, "cannot open file"),
            missing_library=lib,
            suggested_files=["CMakeLists.txt"],
            **base,
        )

    unresolved = MSVC_UNRESOLVED_RE.search(text)
    if unresolved:
        symbol = unresolved.group(1).strip().strip('"')
        return BuildErrorSummary(
            error_type="unresolved_external",
            message=unresolved.group(0).strip(),
            evidence_lines=_evidence(text, "unresolved external symbol"),
            missing_symbol=symbol,
            source_file=_source_file_from_output(text),
            suggested_files=["CMakeLists.txt"],
            **base,
        )

    missing_source = MISSING_SOURCE_RE.search(text)
    if missing_source:
        source = missing_source.group(1).strip()
        return BuildErrorSummary(
            error_type="missing_source",
            message=missing_source.group(0).strip(),
            evidence_lines=_evidence(text, "missing"),
            missing_source=source,
            suggested_files=["CMakeLists.txt"],
            **base,
        )

    # --- existing MVP patterns ---

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
            **base,
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
            **base,
        )

    # Check for cmake "Cannot find package name" — use Could NOT find before
    # generic "provided by" package regex

    package = MISSING_PACKAGE_RE.search(text)
    if package:
        name = package.group(1).strip()
        return BuildErrorSummary(
            error_type="missing_package",
            message=package.group(0).strip(),
            evidence_lines=_evidence(text, "Could not find"),
            missing_package=name,
            suggested_files=["CMakeLists.txt", "vcpkg.json", "CMakePresets.json"],
            **base,
        )

    cmake_pkg = CMAKE_COULD_NOT_FIND_RE.search(text)
    if cmake_pkg:
        name = cmake_pkg.group(1).strip()
        return BuildErrorSummary(
            error_type="missing_package",
            message=f"CMake could not find package: {name}",
            evidence_lines=_evidence(text, "Could not find"),
            missing_package=name,
            suggested_files=["CMakeLists.txt", "vcpkg.json", "CMakePresets.json"],
            **base,
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
            **base,
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
            **base,
        )

    # CTest named failure — check before "CMake Error" / generic "failed"
    ctest_fail = CTEST_FAILED_RE.search(text)
    if ctest_fail:
        return BuildErrorSummary(
            error_type="test_failure",
            message="Configured test command failed.",
            evidence_lines=_evidence(text, "fail"),
            test_name=ctest_fail.group(1).strip(),
            **base,
        )

    if "CMake Error" in text:
        return BuildErrorSummary(
            error_type="cmake_config_error",
            message="CMake configure failed.",
            evidence_lines=_evidence(text, "CMake Error"),
            suggested_files=["CMakeLists.txt", "CMakePresets.json"],
            **base,
        )

    if "FAILED" in text or "failed" in text:
        return BuildErrorSummary(
            error_type="test_failure",
            message="Configured test command failed.",
            evidence_lines=_evidence(text, "fail"),
            **base,
        )

    return BuildErrorSummary(
        error_type="unknown",
        message="Build output did not match a known CMake Build-Fix pattern.",
        evidence_lines=_evidence(text),
        **base,
    )
