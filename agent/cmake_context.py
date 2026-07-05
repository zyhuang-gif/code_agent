"""Static CMake/C++ repository context extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent.profile import ProjectProfile


TARGET_RE = re.compile(r"\badd_(?:executable|library)\s*\(\s*([A-Za-z0-9_.:+-]+)", re.IGNORECASE)
PACKAGE_RE = re.compile(r"\bfind_package\s*\(\s*([A-Za-z0-9_.:+-]+)", re.IGNORECASE)

TARGET_SOURCES_RE = re.compile(r"\btarget_sources\s*\(\s*([A-Za-z0-9_.:+-]+)\s+([^)]*)\)", re.IGNORECASE | re.DOTALL)
TARGET_INCLUDE_RE = re.compile(r"\btarget_include_directories\s*\(\s*([A-Za-z0-9_.:+-]+)\s+([^)]*)\)", re.IGNORECASE | re.DOTALL)
TARGET_LINK_RE = re.compile(r"\btarget_link_libraries\s*\(\s*([A-Za-z0-9_.:+-]+)\s+([^)]*)\)", re.IGNORECASE | re.DOTALL)
ADD_SUBDIRECTORY_RE = re.compile(r"\badd_subdirectory\s*\(\s*([^) \n\r\t]+)", re.IGNORECASE)


_CMAKE_SCOPE_TOKENS = {"PRIVATE", "PUBLIC", "INTERFACE"}


@dataclass(frozen=True)
class CMakeContext:
    root: Path
    cmake_files: list[str] = field(default_factory=list)
    presets: list[str] = field(default_factory=list)
    manifest_files: list[str] = field(default_factory=list)
    source_dirs: list[str] = field(default_factory=list)
    include_dirs: list[str] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    build_dirs: list[str] = field(default_factory=list)
    target_sources: dict[str, list[str]] = field(default_factory=dict)
    target_include_dirs: dict[str, list[str]] = field(default_factory=dict)
    target_links: dict[str, list[str]] = field(default_factory=dict)
    subdirectories: list[str] = field(default_factory=list)
    vcpkg_dependencies: list[str] = field(default_factory=list)


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted(dict.fromkeys(values))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _split_cmake_args(body: str) -> list[str]:
    cleaned = re.sub(r"#.*", "", body)
    values = []
    for token in re.split(r"[\s\r\n]+", cleaned.strip()):
        token = token.strip().strip('"')
        if not token or token.upper() in _CMAKE_SCOPE_TOKENS:
            continue
        values.append(token)
    return values


def _add_mapping_value(mapping: dict[str, list[str]], key: str, values: list[str]) -> None:
    if not values:
        return
    mapping[key] = _unique_sorted([*mapping.get(key, []), *values])


def _scan_presets(root: Path) -> list[str]:
    path = root / "CMakePresets.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    names = []
    for key in ("configurePresets", "buildPresets", "testPresets"):
        for item in data.get(key, []) or []:
            name = item.get("name")
            if isinstance(name, str):
                names.append(name)
    return _unique_sorted(names)


def _scan_vcpkg_dependencies(root: Path) -> list[str]:
    path = root / "vcpkg.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    deps = []
    for item in data.get("dependencies", []) or []:
        if isinstance(item, str):
            deps.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            deps.append(item["name"])
    return _unique_sorted(deps)


def scan_cmake_context(root: Path, profile: ProjectProfile | None = None) -> CMakeContext:
    root = Path(root)
    profile = profile or ProjectProfile()
    cmake_files: list[str] = []
    targets: list[str] = []
    packages: list[str] = []
    target_sources: dict[str, list[str]] = {}
    target_include_dirs: dict[str, list[str]] = {}
    target_links: dict[str, list[str]] = {}
    subdirectories: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = _rel(path, root)
        if profile.should_ignore(rel):
            continue
        if path.name == "CMakeLists.txt" or path.suffix == ".cmake":
            cmake_files.append(rel)
            text = _read_text(path)
            targets.extend(match.group(1) for match in TARGET_RE.finditer(text))
            packages.extend(match.group(1) for match in PACKAGE_RE.finditer(text))

            for match in TARGET_SOURCES_RE.finditer(text):
                _add_mapping_value(target_sources, match.group(1), _split_cmake_args(match.group(2)))
            for match in TARGET_INCLUDE_RE.finditer(text):
                _add_mapping_value(target_include_dirs, match.group(1), _split_cmake_args(match.group(2)))
            for match in TARGET_LINK_RE.finditer(text):
                _add_mapping_value(target_links, match.group(1), _split_cmake_args(match.group(2)))
            subdirectories.extend(
                match.group(1).strip().strip('"') for match in ADD_SUBDIRECTORY_RE.finditer(text)
            )

    manifest_files = [
        name for name in ("vcpkg.json", "conanfile.txt", "conanfile.py")
        if (root / name).exists()
    ]
    source_dirs = [name for name in ("src", "source", "lib", "app") if (root / name).is_dir()]
    include_dirs = [name for name in ("include", "inc") if (root / name).is_dir()]
    test_dirs = [name for name in ("test", "tests") if (root / name).is_dir()]
    build_dirs = [
        path.name for path in sorted(root.iterdir())
        if path.is_dir() and (path.name == "build" or path.name.startswith("cmake-build-"))
    ]

    return CMakeContext(
        root=root,
        cmake_files=_unique_sorted(cmake_files),
        presets=_scan_presets(root),
        manifest_files=manifest_files,
        source_dirs=source_dirs,
        include_dirs=include_dirs,
        test_dirs=test_dirs,
        targets=_unique_sorted(targets),
        packages=_unique_sorted(packages),
        build_dirs=_unique_sorted(build_dirs),
        target_sources={key: _unique_sorted(items) for key, items in sorted(target_sources.items())},
        target_include_dirs={key: _unique_sorted(items) for key, items in sorted(target_include_dirs.items())},
        target_links={key: _unique_sorted(items) for key, items in sorted(target_links.items())},
        subdirectories=_unique_sorted(subdirectories),
        vcpkg_dependencies=_scan_vcpkg_dependencies(root),
    )


def _line(label: str, values: list[str]) -> str:
    return f"- {label}: {', '.join(values) if values else 'none'}"


def _mapping_lines(label: str, mapping: dict[str, list[str]], limit: int = 8) -> list[str]:
    if not mapping:
        return [f"- {label}: none"]
    rows = []
    for key in sorted(mapping)[:limit]:
        rows.append(f"  - {key} -> {', '.join(mapping[key])}")
    return [f"- {label}:"] + rows


def render_cmake_context(context: CMakeContext) -> str:
    return "\n".join(
        [
            "CMake project context:",
            _line("CMake files", context.cmake_files),
            _line("presets", context.presets),
            _line("manifests", context.manifest_files),
            _line("targets", context.targets),
            _line("packages", context.packages),
            _line("source dirs", context.source_dirs),
            _line("include dirs", context.include_dirs),
            _line("test dirs", context.test_dirs),
            *_mapping_lines("target sources", context.target_sources),
            *_mapping_lines("target include dirs", context.target_include_dirs),
            *_mapping_lines("target links", context.target_links),
            _line("subdirectories", context.subdirectories),
            _line("vcpkg dependencies", context.vcpkg_dependencies),
        ]
    )
