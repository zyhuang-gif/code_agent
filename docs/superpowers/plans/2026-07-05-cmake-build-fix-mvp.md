# CMake Build-Fix MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a C++/CMake Build-Fix domain layer to `code-agent` that classifies common CMake build failures, enriches the agent prompt with repo/build context, verifies fixes with real local CMake commands, and writes a final fix report.

**Architecture:** Keep `AgentLoop`, generic tools, and eval harness intact. Add a narrow CMake domain layer (`cmake_context`, `build_errors`, `build_runner`, `repair_hints`, `cmake_prompt`, `fix_report`) and route CMake profiles through that layer from `main.py` and `eval/run_eval.py`.

**Tech Stack:** Python 3.13-compatible stdlib dataclasses/regex/pathlib, PyYAML already present, pytest, local CMake + MinGW Makefiles for C++ fixtures.

## Global Constraints

- Work only inside an isolated git worktree, not the main checkout.
- Do not rewrite `AgentLoop`, `ToolRegistry`, or the eval harness architecture.
- Preserve all existing public APIs unless a task explicitly changes one.
- CMake behavior is enabled only when `ProjectProfile.language == "cmake"`.
- First version does not use Docker, embeddings, vector DB, tree-sitter, LSP, network installs, vcpkg installs, or Conan installs.
- Toy CMake tasks must be deterministic and offline.
- Default local generator on this machine is `MinGW Makefiles`; task profiles may override commands.
- Use target-based CMake fixes in prompts and examples.
- Final implementation must pass the existing Python test suite.
- Final implementation must preserve `eval/run_eval.py --repeat` and `--multi` behavior.

---

## File Structure

- Create `profiles/cmake.yaml`: default local CMake profile.
- Create `agent/cmake_context.py`: static CMake/C++ repo scanner and prompt renderer.
- Create `agent/build_errors.py`: build output classifier and summary model.
- Create `agent/repair_hints.py`: maps context + error type to targeted prompt hints.
- Create `agent/build_runner.py`: CMake verification command runner and attempt model.
- Create `agent/cmake_prompt.py`: constructs enriched CMake task prompt.
- Create `agent/fix_report.py`: final markdown report generator and trace event helper.
- Modify `main.py`: use CMake prompt/report when profile language is `cmake`.
- Modify `eval/run_eval.py`: use CMake prompt/report in real and multi-agent factories; update fake agent for toy CMake tasks.
- Create `eval/tasks_cmake/c01_missing_project_header` through `eval/tasks_cmake/c05_test_failure_tolerance`: five deterministic toy CMake benchmark tasks.
- Create `eval/tasks_cmake_real/r01_poco_postgresql_imported_target` and `eval/tasks_cmake_real/r02_nlohmann_json_config_missing`: at least two offline real-inspired fixtures.
- Create tests:
  - `tests/test_cmake_context.py`
  - `tests/test_build_errors.py`
  - `tests/test_build_runner.py`
  - `tests/test_cmake_prompt.py`
  - `tests/test_fix_report.py`
  - updates to `tests/test_profile.py`, `tests/test_eval.py`, and `tests/test_main.py` only where necessary.

### Task 1: CMake Profile And Static Context Builder

**Files:**
- Create: `profiles/cmake.yaml`
- Create: `agent/cmake_context.py`
- Create: `tests/test_cmake_context.py`
- Modify: `tests/test_profile.py`

**Interfaces:**
- Produces `CMakeContext` dataclass.
- Produces `scan_cmake_context(root: Path, profile: ProjectProfile | None = None) -> CMakeContext`.
- Produces `render_cmake_context(context: CMakeContext) -> str`.

- [ ] **Step 1: Write failing tests for CMake profile loading**

Add this test to `tests/test_profile.py`:

```python
def test_builtin_cmake_profile_declares_language_and_build_command():
    cmake_profile = load_profile("profiles/cmake.yaml")

    assert cmake_profile.language == "cmake"
    assert "cmake -S . -B build" in cmake_profile.test_cmd
    assert "ctest --test-dir build" in cmake_profile.test_cmd
    assert cmake_profile.test_timeout == 120
    assert cmake_profile.should_ignore("build/CMakeCache.txt") is True
    assert cmake_profile.should_ignore("cmake-build-debug/CMakeCache.txt") is True
```

- [ ] **Step 2: Create the profile**

Create `profiles/cmake.yaml`:

```yaml
ignore:
  - .git
  - __pycache__
  - build
  - build/*
  - cmake-build-*
  - _deps
  - CMakeFiles
  - CMakeCache.txt
syntax_check: {}
language: cmake
test_cmd: cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure
test_timeout: 120
command_timeout: 120
```

- [ ] **Step 3: Write failing context tests**

Create `tests/test_cmake_context.py`:

```python
from pathlib import Path

from agent.cmake_context import CMakeContext, render_cmake_context, scan_cmake_context
from agent.profile import ProjectProfile


def test_scan_cmake_context_finds_core_project_facts(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "cmake").mkdir()
    (tmp_path / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.16)
project(Demo LANGUAGES CXX)
find_package(Threads REQUIRED)
add_library(mathx src/add.cpp)
add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE mathx Threads::Threads)
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cmake" / "Helpers.cmake").write_text("# helper\n", encoding="utf-8")
    (tmp_path / "vcpkg.json").write_text('{"dependencies":["fmt"]}\n', encoding="utf-8")
    (tmp_path / "CMakePresets.json").write_text(
        '{"version": 3, "configurePresets": [{"name": "mingw"}]}\n',
        encoding="utf-8",
    )

    context = scan_cmake_context(tmp_path, ProjectProfile(language="cmake"))

    assert context.cmake_files == ["CMakeLists.txt", "cmake/Helpers.cmake"]
    assert context.presets == ["mingw"]
    assert context.manifest_files == ["vcpkg.json"]
    assert context.source_dirs == ["src"]
    assert context.include_dirs == ["include"]
    assert context.test_dirs == ["tests"]
    assert context.targets == ["app", "mathx"]
    assert context.packages == ["Threads"]


def test_render_cmake_context_is_compact_and_relative(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("add_executable(app main.cpp)\n", encoding="utf-8")

    context = scan_cmake_context(tmp_path)
    rendered = render_cmake_context(context)

    assert "CMake project context:" in rendered
    assert "CMakeLists.txt" in rendered
    assert "targets: app" in rendered
    assert str(tmp_path) not in rendered
```

- [ ] **Step 4: Run tests and confirm they fail for missing module/profile**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_profile.py tests/test_cmake_context.py -q
```

Expected: fails because `profiles/cmake.yaml` and `agent.cmake_context` do not exist yet.

- [ ] **Step 5: Implement `agent/cmake_context.py`**

Create `agent/cmake_context.py`:

```python
"""Static CMake/C++ repository context extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent.profile import ProjectProfile


TARGET_RE = re.compile(r"\badd_(?:executable|library)\s*\(\s*([A-Za-z0-9_.:+-]+)", re.IGNORECASE)
PACKAGE_RE = re.compile(r"\bfind_package\s*\(\s*([A-Za-z0-9_.:+-]+)", re.IGNORECASE)


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


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted(dict.fromkeys(values))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


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


def scan_cmake_context(root: Path, profile: ProjectProfile | None = None) -> CMakeContext:
    root = Path(root)
    profile = profile or ProjectProfile()
    cmake_files: list[str] = []
    targets: list[str] = []
    packages: list[str] = []

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
    )


def _line(label: str, values: list[str]) -> str:
    return f"- {label}: {', '.join(values) if values else 'none'}"


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
        ]
    )
```

- [ ] **Step 6: Run tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_profile.py tests/test_cmake_context.py -q
```

Expected: tests pass.

- [ ] **Step 7: Commit**

```powershell
git add profiles/cmake.yaml agent/cmake_context.py tests/test_cmake_context.py tests/test_profile.py
git commit -m "feat(cmake): scan static project context"
```

### Task 2: Build Error Classifier And Repair Hints

**Files:**
- Create: `agent/build_errors.py`
- Create: `agent/repair_hints.py`
- Create: `tests/test_build_errors.py`

**Interfaces:**
- Produces `BuildErrorType` string constants or `StrEnum`.
- Produces `BuildErrorSummary`.
- Produces `classify_build_output(output: str) -> BuildErrorSummary`.
- Produces `render_repair_hints(summary: BuildErrorSummary, context: CMakeContext | None = None) -> str`.

- [ ] **Step 1: Write failing classifier tests**

Create `tests/test_build_errors.py`:

```python
from agent.build_errors import classify_build_output
from agent.cmake_context import CMakeContext
from agent.repair_hints import render_repair_hints


def test_classifies_missing_header_from_gcc_output(tmp_path):
    output = "src/main.cpp:1:10: fatal error: mathx/add.hpp: No such file or directory\ncompilation terminated."

    summary = classify_build_output(output)

    assert summary.error_type == "missing_header"
    assert summary.missing_header == "mathx/add.hpp"
    assert "fatal error" in summary.message
    assert summary.evidence_lines


def test_classifies_undefined_reference():
    output = "main.cpp:(.text+0x1a): undefined reference to `mathx::add(int, int)'"

    summary = classify_build_output(output)

    assert summary.error_type == "undefined_reference"
    assert summary.missing_symbol == "mathx::add(int, int)"


def test_classifies_missing_package_from_cmake_output():
    output = "Could not find a package configuration file provided by \"nlohmann_json\" with any of the following names:"

    summary = classify_build_output(output)

    assert summary.error_type == "missing_package"
    assert summary.missing_package == "nlohmann_json"


def test_classifies_missing_target_from_cmake_output():
    output = "Target \"app\" links to: MathX::Core but the target was not found."

    summary = classify_build_output(output)

    assert summary.error_type == "missing_target"
    assert summary.missing_target == "MathX::Core"
    assert summary.target == "app"


def test_render_repair_hints_mentions_target_based_cmake_for_link_errors(tmp_path):
    summary = classify_build_output("undefined reference to `mathx::add(int, int)'")
    context = CMakeContext(root=tmp_path, cmake_files=["CMakeLists.txt"], targets=["app", "mathx"])

    hints = render_repair_hints(summary, context)

    assert "Repair hints:" in hints
    assert "target_link_libraries" in hints
    assert "CMakeLists.txt" in hints
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_build_errors.py -q
```

Expected: fails because modules do not exist.

- [ ] **Step 3: Implement `agent/build_errors.py`**

Create `agent/build_errors.py`:

```python
"""Classify common CMake/C++ build failures."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


MISSING_HEADER_RE = re.compile(r"fatal error:\s*([^:\n]+):\s*No such file or directory", re.IGNORECASE)
UNDEFINED_REFERENCE_RE = re.compile(r"undefined reference to [`']([^`'\n]+)[`']", re.IGNORECASE)
MISSING_PACKAGE_RE = re.compile(r"provided by \"([A-Za-z0-9_.:+-]+)\"", re.IGNORECASE)
MISSING_TARGET_RE = re.compile(r"Target \"([^\"]+)\" links to:\s*([A-Za-z0-9_.:+-]+)\s*but the target was not found", re.IGNORECASE)


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
```

- [ ] **Step 4: Implement `agent/repair_hints.py`**

Create `agent/repair_hints.py`:

```python
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
```

- [ ] **Step 5: Run tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_build_errors.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```powershell
git add agent/build_errors.py agent/repair_hints.py tests/test_build_errors.py
git commit -m "feat(cmake): classify build failures"
```

### Task 3: Build Runner And Trace Events

**Files:**
- Create: `agent/build_runner.py`
- Create: `tests/test_build_runner.py`

**Interfaces:**
- Produces `BuildAttempt`.
- Produces `split_cmake_test_command(profile: ProjectProfile) -> list[tuple[str, str]]`.
- Produces `run_cmake_verification(workspace, profile, runner, trace=None) -> list[BuildAttempt]`.

- [ ] **Step 1: Write failing build runner tests**

Create `tests/test_build_runner.py`:

```python
import json
from pathlib import Path

from agent.build_runner import run_cmake_verification, split_cmake_test_command
from agent.profile import ProjectProfile
from agent.trace import Trace


def test_split_cmake_test_command_labels_phases():
    profile = ProjectProfile(
        language="cmake",
        test_cmd='cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    )

    phases = split_cmake_test_command(profile)

    assert phases == [
        ("configure", 'cmake -S . -B build -G "MinGW Makefiles"'),
        ("build", "cmake --build build"),
        ("test", "ctest --test-dir build --output-on-failure"),
    ]


def test_run_cmake_verification_stops_after_failure_and_records_trace(tmp_path: Path):
    calls = []

    def runner(cmd, cwd=None, timeout=None, allow_network=False):
        calls.append((cmd, cwd, timeout, allow_network))
        return {"exit_code": 1, "stdout": "fatal error: x.hpp: No such file or directory\n", "stderr": ""}

    profile = ProjectProfile(language="cmake", test_cmd="cmake -S . -B build && cmake --build build", test_timeout=12)
    trace = Trace(tmp_path / "trace.jsonl")

    attempts = run_cmake_verification(tmp_path, profile, runner, trace)

    assert len(attempts) == 1
    assert attempts[0].phase == "configure"
    assert attempts[0].exit_code == 1
    assert calls == [("cmake -S . -B build", tmp_path, 12, False)]
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert rows[-1]["t"] == "build_attempt"
    assert rows[-1]["phase"] == "configure"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_build_runner.py -q
```

Expected: fails because `agent.build_runner` does not exist.

- [ ] **Step 3: Implement `agent/build_runner.py`**

Create `agent/build_runner.py`:

```python
"""CMake build/test command runner helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.profile import ProjectProfile
from agent.tools import truncate
from agent.trace import Trace


@dataclass(frozen=True)
class BuildAttempt:
    command: str
    phase: str
    exit_code: int
    output_preview: str


def _phase_for(command: str, index: int) -> str:
    stripped = command.strip()
    if stripped.startswith("ctest"):
        return "test"
    if stripped.startswith("cmake --build"):
        return "build"
    if stripped.startswith("cmake "):
        return "configure"
    return f"step_{index + 1}"


def split_cmake_test_command(profile: ProjectProfile) -> list[tuple[str, str]]:
    if not profile.test_cmd:
        return []
    commands = [part.strip() for part in profile.test_cmd.split("&&") if part.strip()]
    return [(_phase_for(command, index), command) for index, command in enumerate(commands)]


def run_cmake_verification(
    workspace: str | Path,
    profile: ProjectProfile,
    runner: Callable[..., dict[str, Any]],
    trace: Trace | None = None,
) -> list[BuildAttempt]:
    workspace = Path(workspace)
    attempts: list[BuildAttempt] = []
    for phase, command in split_cmake_test_command(profile):
        result = runner(command, cwd=workspace, timeout=profile.test_timeout, allow_network=False)
        exit_code = int(result.get("exit_code", 1))
        output = truncate(f"{result.get('stdout', '')}{result.get('stderr', '')}")
        attempt = BuildAttempt(command=command, phase=phase, exit_code=exit_code, output_preview=output)
        attempts.append(attempt)
        if trace:
            trace.write(
                {
                    "t": "build_attempt",
                    "phase": phase,
                    "command": command,
                    "exit_code": exit_code,
                    "output_preview": output,
                }
            )
        if exit_code != 0:
            break
    return attempts
```

- [ ] **Step 4: Run tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_build_runner.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add agent/build_runner.py tests/test_build_runner.py
git commit -m "feat(cmake): run build verification steps"
```

### Task 4: CMake Prompt Enrichment And Agent Factory Integration

**Files:**
- Create: `agent/cmake_prompt.py`
- Create: `tests/test_cmake_prompt.py`
- Modify: `main.py`
- Modify: `eval/run_eval.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_eval.py`

**Interfaces:**
- Produces `build_cmake_task_prompt(task, workspace, profile, initial_output="") -> str`.
- `main.py`, `real_agent_factory()`, and `multi_agent_factory()` call prompt enrichment only for `language == "cmake"`.

- [ ] **Step 1: Write failing prompt tests**

Create `tests/test_cmake_prompt.py`:

```python
from pathlib import Path

from agent.cmake_prompt import build_cmake_task_prompt
from agent.profile import ProjectProfile


def test_build_cmake_task_prompt_includes_context_error_and_hints(tmp_path: Path):
    (tmp_path / "include").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/main.cpp)\n", encoding="utf-8")

    prompt = build_cmake_task_prompt(
        "Fix the build.",
        tmp_path,
        ProjectProfile(language="cmake"),
        "src/main.cpp:1:10: fatal error: mathx/add.hpp: No such file or directory",
    )

    assert "Task: Fix the build." in prompt
    assert "CMake project context:" in prompt
    assert "Build error summary:" in prompt
    assert "type: missing_header" in prompt
    assert "Repair hints:" in prompt
    assert "Do not install packages" in prompt
```

- [ ] **Step 2: Implement `agent/cmake_prompt.py`**

Create `agent/cmake_prompt.py`:

```python
"""CMake-specific task prompt enrichment."""

from __future__ import annotations

from pathlib import Path

from agent.build_errors import classify_build_output
from agent.cmake_context import render_cmake_context, scan_cmake_context
from agent.profile import ProjectProfile
from agent.repair_hints import render_repair_hints


def _render_error_summary(output: str) -> str:
    summary = classify_build_output(output)
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


def build_cmake_task_prompt(
    task: str,
    workspace: str | Path,
    profile: ProjectProfile,
    initial_output: str = "",
) -> str:
    context = scan_cmake_context(Path(workspace), profile)
    summary = classify_build_output(initial_output)
    return "\n\n".join(
        [
            f"Task: {task}",
            render_cmake_context(context),
            _render_error_summary(initial_output),
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
```

- [ ] **Step 3: Add a helper in `eval/run_eval.py`**

Add near the factory helpers:

```python
def _maybe_enrich_prompt(workspace: Path, prompt: str, profile: ProjectProfile, runner: CommandRunner, trace=None) -> str:
    if profile.language != "cmake":
        return prompt
    from agent.build_runner import run_cmake_verification
    from agent.cmake_prompt import build_cmake_task_prompt

    attempts = run_cmake_verification(workspace, profile, runner, trace)
    initial_output = "\n".join(attempt.output_preview for attempt in attempts)
    return build_cmake_task_prompt(prompt, workspace, profile, initial_output)
```

In `real_agent_factory()`, change:

```python
result = AgentLoop(LLMClient(trace=trace, **_llm_env_kwargs("DEEPSEEK")), build_default_registry()).run(prompt, ctx)
```

to:

```python
task_prompt = _maybe_enrich_prompt(workspace, prompt, profile, ctx.runner or default_command_runner, trace)
result = AgentLoop(LLMClient(trace=trace, **_llm_env_kwargs("DEEPSEEK")), build_default_registry()).run(task_prompt, ctx)
```

In `multi_agent_factory()`, change:

```python
result = MultiAgentOrchestrator(llm, build_default_registry(), **role_llms).run(prompt, ctx)
```

to:

```python
task_prompt = _maybe_enrich_prompt(workspace, prompt, profile, ctx.runner or default_command_runner, trace)
result = MultiAgentOrchestrator(llm, build_default_registry(), **role_llms).run(task_prompt, ctx)
```

- [ ] **Step 4: Add main CLI enrichment**

In `main.py`, after `ctx` is created and before the existing `AgentLoop` run call, add:

```python
task = args.task
if profile.language == "cmake":
    from agent.build_runner import run_cmake_verification
    from agent.cmake_prompt import build_cmake_task_prompt
    from agent.tools import default_runner

    attempts = run_cmake_verification(workspace, profile, ctx.runner or default_runner, trace)
    initial_output = "\n".join(attempt.output_preview for attempt in attempts)
    task = build_cmake_task_prompt(args.task, workspace, profile, initial_output)
```

Then pass `task` to the loop instead of `args.task`.

- [ ] **Step 5: Add tests for eval factory prompt enrichment**

Add a test to `tests/test_eval.py`:

```python
def test_real_agent_factory_enriches_cmake_prompt(tmp_path: Path, monkeypatch):
    import eval.run_eval as run_eval

    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "CMakeLists.txt").write_text("add_executable(app main.cpp)\n", encoding="utf-8")
    captured = {}

    class FakeLLMClient:
        def __init__(self, trace, **kwargs):
            pass

    class FakeLoop:
        def __init__(self, llm, tools):
            pass

        def run(self, prompt, ctx):
            captured["prompt"] = prompt
            return type("Result", (), {"cost_usd": 0.0, "reason": "finished"})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    profile = ProjectProfile(language="cmake", test_cmd="cmake -S . -B build")
    run_eval.real_agent_factory()(workspace, "Fix build", profile)

    assert "CMake project context:" in captured["prompt"]
    assert "Build error summary:" in captured["prompt"]
```

- [ ] **Step 6: Run tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_cmake_prompt.py tests/test_eval.py tests/test_main.py -q
```

Expected: tests pass.

- [ ] **Step 7: Commit**

```powershell
git add agent/cmake_prompt.py main.py eval/run_eval.py tests/test_cmake_prompt.py tests/test_eval.py tests/test_main.py
git commit -m "feat(cmake): enrich build-fix prompts"
```

### Task 5: Toy CMake Benchmark And Fake Agent Support

**Files:**
- Create: `eval/tasks_cmake/c01_missing_project_header/{repo,prompt.md,profile.yaml,verify.py}`
- Create: `eval/tasks_cmake/c02_missing_source_in_target/{repo,prompt.md,profile.yaml,verify.py}`
- Create: `eval/tasks_cmake/c03_missing_local_library_link/{repo,prompt.md,profile.yaml,verify.py}`
- Create: `eval/tasks_cmake/c04_wrong_target_name/{repo,prompt.md,profile.yaml,verify.py}`
- Create: `eval/tasks_cmake/c05_test_failure_tolerance/{repo,prompt.md,profile.yaml,verify.py}`
- Modify: `eval/run_eval.py`
- Create or modify: `tests/test_eval.py`

**Interfaces:**
- Existing `discover()` finds all CMake tasks.
- Existing `run_task()` can verify them.
- `fake_agent()` performs deterministic tiny fixes so `--fake` is useful for harness checks.

- [ ] **Step 1: Add a reusable verify script body to each task**

Each `verify.py` should contain this exact body:

```python
import subprocess
import sys

commands = [
    ['cmake', '-S', '.', '-B', 'build', '-G', 'MinGW Makefiles'],
    ['cmake', '--build', 'build'],
    ['ctest', '--test-dir', 'build', '--output-on-failure'],
]

for command in commands:
    proc = subprocess.run(command, text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        sys.exit(proc.returncode)
```

Each `profile.yaml` should contain:

```yaml
ignore:
  - build
  - build/*
  - CMakeFiles
  - CMakeCache.txt
language: cmake
test_cmd: cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure
test_timeout: 120
command_timeout: 120
```

- [ ] **Step 2: Create task `c01_missing_project_header`**

Create `eval/tasks_cmake/c01_missing_project_header/prompt.md`:

```markdown
Fix the CMake build. The executable should compile and the CTest test should pass.
Prefer a target-based CMake fix.
```

Create `eval/tasks_cmake/c01_missing_project_header/repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(C01MissingHeader LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
```

Create `eval/tasks_cmake/c01_missing_project_header/repo/include/mathx/add.hpp`:

```cpp
#pragma once

namespace mathx {
int add(int a, int b);
}
```

Create `eval/tasks_cmake/c01_missing_project_header/repo/src/main.cpp`:

```cpp
#include "mathx/add.hpp"

#include <stdexcept>

namespace mathx {
int add(int a, int b) {
    return a + b;
}
}

int main() {
    if (mathx::add(2, 3) != 5) {
        throw std::runtime_error("bad add");
    }
    return 0;
}
```

The intended fix is:

```cmake
target_include_directories(app PRIVATE include)
```

- [ ] **Step 3: Create task `c02_missing_source_in_target`**

Create `eval/tasks_cmake/c02_missing_source_in_target/prompt.md`:

```markdown
Fix the CMake build. The implementation exists, but the target is not wired correctly.
Do not move files or inline the implementation into main.cpp.
```

Create `eval/tasks_cmake/c02_missing_source_in_target/repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(C02MissingSource LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
target_include_directories(app PRIVATE include)
add_test(NAME app_runs COMMAND app)
```

Create `eval/tasks_cmake/c02_missing_source_in_target/repo/include/mathx/add.hpp`:

```cpp
#pragma once

namespace mathx {
int add(int a, int b);
}
```

Create `eval/tasks_cmake/c02_missing_source_in_target/repo/src/add.cpp`:

```cpp
#include "mathx/add.hpp"

namespace mathx {
int add(int a, int b) {
    return a + b;
}
}
```

Create `eval/tasks_cmake/c02_missing_source_in_target/repo/src/main.cpp`:

```cpp
#include "mathx/add.hpp"

#include <stdexcept>

int main() {
    if (mathx::add(10, 5) != 15) {
        throw std::runtime_error("bad add");
    }
    return 0;
}
```

The intended fix is to change `add_executable(app src/main.cpp)` to `add_executable(app src/main.cpp src/add.cpp)`.

- [ ] **Step 4: Create task `c03_missing_local_library_link`**

Create `eval/tasks_cmake/c03_missing_local_library_link/prompt.md`:

```markdown
Fix the CMake build. A local library target exists and should be linked into the executable.
Use target_link_libraries rather than copying source files into the executable.
```

Create `eval/tasks_cmake/c03_missing_local_library_link/repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(C03MissingLocalLink LANGUAGES CXX)

enable_testing()

add_library(mathx src/add.cpp)
target_include_directories(mathx PUBLIC include)

add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
```

Create `eval/tasks_cmake/c03_missing_local_library_link/repo/include/mathx/add.hpp`:

```cpp
#pragma once

namespace mathx {
int add(int a, int b);
}
```

Create `eval/tasks_cmake/c03_missing_local_library_link/repo/src/add.cpp`:

```cpp
#include "mathx/add.hpp"

namespace mathx {
int add(int a, int b) {
    return a + b;
}
}
```

Create `eval/tasks_cmake/c03_missing_local_library_link/repo/src/main.cpp`:

```cpp
#include "mathx/add.hpp"

#include <stdexcept>

int main() {
    if (mathx::add(10, 5) != 15) {
        throw std::runtime_error("bad add");
    }
    return 0;
}
```

The intended fix is:

```cmake
target_link_libraries(app PRIVATE mathx)
```

- [ ] **Step 5: Create task `c04_wrong_target_name`**

Create `eval/tasks_cmake/c04_wrong_target_name/prompt.md`:

```markdown
Fix the CMake build. There is a typo in the local target wiring.
Do not add external dependencies.
```

Create `eval/tasks_cmake/c04_wrong_target_name/repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(C04WrongTargetName LANGUAGES CXX)

enable_testing()

add_library(mathx src/add.cpp)
target_include_directories(mathx PUBLIC include)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE MathX::Core)
add_test(NAME app_runs COMMAND app)
```

Create `eval/tasks_cmake/c04_wrong_target_name/repo/include/mathx/add.hpp`:

```cpp
#pragma once

namespace mathx {
int add(int a, int b);
}
```

Create `eval/tasks_cmake/c04_wrong_target_name/repo/src/add.cpp`:

```cpp
#include "mathx/add.hpp"

namespace mathx {
int add(int a, int b) {
    return a + b;
}
}
```

Create `eval/tasks_cmake/c04_wrong_target_name/repo/src/main.cpp`:

```cpp
#include "mathx/add.hpp"

#include <stdexcept>

int main() {
    if (mathx::add(10, 5) != 15) {
        throw std::runtime_error("bad add");
    }
    return 0;
}
```

The intended fix is to replace `MathX::Core` with `mathx`.

- [ ] **Step 6: Create task `c05_test_failure_tolerance`**

Create `eval/tasks_cmake/c05_test_failure_tolerance/prompt.md`:

```markdown
The CMake project builds, but CTest fails. Fix the local C++ logic so the test passes.
Do not delete the test.
```

Create `eval/tasks_cmake/c05_test_failure_tolerance/repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(C05TestFailure LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp src/scale.cpp)
target_include_directories(app PRIVATE include)
add_test(NAME app_runs COMMAND app)
```

Create `eval/tasks_cmake/c05_test_failure_tolerance/repo/include/mathx/scale.hpp`:

```cpp
#pragma once

namespace mathx {
double scale(double value, double factor);
}
```

Create `eval/tasks_cmake/c05_test_failure_tolerance/repo/src/scale.cpp`:

```cpp
#include "mathx/scale.hpp"

namespace mathx {
double scale(double value, double factor) {
    return value + factor;
}
}
```

Create `eval/tasks_cmake/c05_test_failure_tolerance/repo/src/main.cpp`:

```cpp
#include "mathx/scale.hpp"

#include <cmath>
#include <stdexcept>

int main() {
    const double result = mathx::scale(3.0, 2.0);
    if (std::fabs(result - 6.0) > 1e-9) {
        throw std::runtime_error("bad scale");
    }
    return 0;
}
```

The intended fix is `return value * factor;`.

- [ ] **Step 7: Update fake agent for toy CMake tasks**

In `eval/run_eval.py`, extend `fake_agent()`:

```python
    cmake = workspace / "CMakeLists.txt"
    if cmake.exists():
        text = cmake.read_text(encoding="utf-8")
        if "add_executable(app src/main.cpp)" in text and (workspace / "include").exists():
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_include_directories(app PRIVATE include)\n",
                1,
            )
        if "add_executable(app src/main.cpp)" in text and (workspace / "src" / "add.cpp").exists():
            text = text.replace("add_executable(app src/main.cpp)", "add_executable(app src/main.cpp src/add.cpp)", 1)
        if "add_executable(app src/main.cpp)\nadd_test" in text and "add_library(mathx" in text:
            text = text.replace("add_executable(app src/main.cpp)\nadd_test", "add_executable(app src/main.cpp)\ntarget_link_libraries(app PRIVATE mathx)\nadd_test", 1)
        text = text.replace("MathX::Core", "mathx")
        cmake.write_text(text, encoding="utf-8")

    scale_cpp = workspace / "src" / "scale.cpp"
    if scale_cpp.exists():
        scale_cpp.write_text(
            '#include "mathx/scale.hpp"\n\nnamespace mathx {\ndouble scale(double value, double factor) {\n    return value * factor;\n}\n}\n',
            encoding="utf-8",
        )
```

Keep this fake logic intentionally small. It is for harness validation, not a
real solver.

- [ ] **Step 8: Add eval discovery tests**

Add to `tests/test_eval.py`:

```python
def test_discovers_cmake_tasks_with_cmake_profile():
    tasks = discover(Path("eval/tasks_cmake"))

    assert len(tasks) >= 5
    assert all(task.profile.language == "cmake" for task in tasks)
    assert all("cmake -S . -B build" in task.profile.test_cmd for task in tasks)
```

- [ ] **Step 9: Run fake eval**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake --fake
```

Expected: `solution_rate` is `1.0` and command exits 0.

- [ ] **Step 10: Commit**

```powershell
git add eval/run_eval.py tests/test_eval.py eval/tasks_cmake
git commit -m "feat(eval): add cmake toy benchmark"
```

### Task 6: Fix Report Generation And Trace Preservation

**Files:**
- Create: `agent/fix_report.py`
- Create: `tests/test_fix_report.py`
- Modify: `main.py`
- Modify: `eval/run_eval.py`

**Interfaces:**
- Produces `FixReport`.
- Produces `build_fix_report(task, result, attempts, workspace) -> FixReport`.
- Produces `write_fix_report(report, path, trace=None) -> None`.

- [ ] **Step 1: Write failing report tests**

Create `tests/test_fix_report.py`:

```python
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
```

- [ ] **Step 2: Implement `agent/fix_report.py`**

Create `agent/fix_report.py`:

```python
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
```

- [ ] **Step 3: Integrate report writing in `main.py`**

After the existing `AgentLoop` run call assigns `result`, add:

```python
if profile.language == "cmake":
    from agent.build_runner import run_cmake_verification
    from agent.fix_report import build_fix_report, write_fix_report
    from agent.tools import default_runner

    attempts = run_cmake_verification(workspace, profile, ctx.runner or default_runner, trace)
    report = build_fix_report(args.task, result, attempts, workspace)
    write_fix_report(report, workspace / "fix_report.md", trace)
    print(f"fix_report={workspace / 'fix_report.md'}")
```

- [ ] **Step 4: Integrate report writing in eval factories**

In both `real_agent_factory()` and `multi_agent_factory()`, after the agent run:

```python
        if profile.language == "cmake":
            from agent.build_runner import run_cmake_verification
            from agent.fix_report import build_fix_report, write_fix_report

            attempts = run_cmake_verification(workspace, profile, ctx.runner or default_command_runner, trace)
            report = build_fix_report(prompt, result, attempts, workspace)
            write_fix_report(report, workspace / "fix_report.md", trace)
```

Return metadata should continue to include `steps`, `cost_usd`, and `reason`.

- [ ] **Step 5: Run tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests/test_fix_report.py tests/test_main.py tests/test_eval.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```powershell
git add agent/fix_report.py main.py eval/run_eval.py tests/test_fix_report.py tests/test_main.py tests/test_eval.py
git commit -m "feat(cmake): write build-fix reports"
```

### Task 7: Real-Inspired Offline CMake Tasks

**Files:**
- Create: `eval/tasks_cmake_real/r01_poco_postgresql_imported_target/{repo,prompt.md,profile.yaml,verify.py}`
- Create: `eval/tasks_cmake_real/r02_nlohmann_json_config_missing/{repo,prompt.md,profile.yaml,verify.py}`
- Modify: `tests/test_eval.py`

**Interfaces:**
- Existing `discover()` loads real-inspired tasks.
- Real-inspired tasks stay offline and deterministic.

- [ ] **Step 1: Create `r01_poco_postgresql_imported_target`**

Create a fixture where:

- `CMakeLists.txt` defines an interface library `PocoDataPostgreSQL`.
- The interface library links `PostgreSQL::client`.
- A local file `cmake/PostgreSQLClient.cmake` defines
  `add_library(PostgreSQL::client INTERFACE IMPORTED)`.
- The broken repo forgets to include that local `.cmake` file before linking.

Prompt:

```markdown
Fix the CMake configure error. The fixture provides a local PostgreSQL::client imported target.
Do not install PostgreSQL and do not fetch packages.
```

Intended fix:

```cmake
include(cmake/PostgreSQLClient.cmake)
```

Verification should run configure/build/ctest with MinGW Makefiles.

- [ ] **Step 2: Create `r02_nlohmann_json_config_missing`**

Create a fixture where:

- `third_party/json/CMakeLists.txt` defines `add_library(nlohmann_json INTERFACE)`
  and `add_library(nlohmann_json::nlohmann_json ALIAS nlohmann_json)`.
- Root `CMakeLists.txt` incorrectly calls `find_package(nlohmann_json REQUIRED)`.
- The app includes a local header from `third_party/json/include`.

Prompt:

```markdown
Fix the CMake configure error using the vendored JSON fixture already in the repo.
Do not install packages and do not fetch from network.
```

Intended fix:

```cmake
add_subdirectory(third_party/json)
```

and link the existing `nlohmann_json::nlohmann_json` target.

- [ ] **Step 3: Add discovery test**

Add to `tests/test_eval.py`:

```python
def test_discovers_real_inspired_cmake_tasks():
    tasks = discover(Path("eval/tasks_cmake_real"))

    assert len(tasks) >= 2
    assert all(task.profile.language == "cmake" for task in tasks)
```

- [ ] **Step 4: Run real-inspired fake eval smoke**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake_real --fake
```

Expected: command runs to completion. It may fail until `fake_agent()` handles these real-inspired fixtures; if it fails, add tiny deterministic fake fixes for the two fixture patterns and rerun until it exits 0.

- [ ] **Step 5: Commit**

```powershell
git add eval/tasks_cmake_real tests/test_eval.py eval/run_eval.py
git commit -m "feat(eval): add real-inspired cmake tasks"
```

### Task 8: End-To-End Acceptance And Documentation

**Files:**
- Create: `docs/cmake-build-fix-mvp.md`
- Modify: implementation files only if acceptance reveals a bug.

**Interfaces:**
- Produces human-readable acceptance notes.
- No new runtime interfaces unless tests expose a gap.

- [ ] **Step 1: Run full Python suite**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass. A pytest cache warning is acceptable if the sandbox
blocks `.pytest_cache` writes.

- [ ] **Step 2: Run CMake toy fake eval**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake --fake
```

Expected: exits 0 with `solution_rate` 1.0.

- [ ] **Step 3: Run direct CMake verification for one toy fixture**

Run:

```powershell
cd eval\tasks_cmake\c01_missing_project_header\repo
cmake -S . -B build -G "MinGW Makefiles"
```

Expected: configure succeeds.

Then run:

```powershell
cmake --build build
```

Expected: build fails before the agent fixes the task because `include/` is not
attached to the target. This confirms the fixture starts red.

Do not commit generated `build/` directories.

- [ ] **Step 4: Run one manual fake CMake agent smoke**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe main.py "Fix the CMake build" eval\tasks_cmake\c01_missing_project_header\repo --profile profiles\cmake.yaml --fake
```

Expected:

- Command exits 0.
- Output includes `workspace=<path>`, `diff_path=<path>`, and `fix_report=<path>`.
- The workspace contains `fix_report.md`.
- The trace file contains `build_attempt` and `fix_report`.

- [ ] **Step 5: Write acceptance documentation**

Create `docs/cmake-build-fix-mvp.md`:

```markdown
# CMake Build-Fix MVP

This MVP adds a C++/CMake domain layer to the existing code-agent loop. It
extracts static CMake context, classifies common build failures, enriches
prompts with repair hints, verifies fixes with local CMake commands, and writes
a final fix report.

## Supported Error Families

- Missing project headers or include directories.
- Missing source files in targets.
- Missing local library links.
- Wrong local target names.
- Simple CTest failures in local C++ logic.
- Offline real-inspired dependency wiring fixtures.

## Commands

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest -q
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake --fake
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake_real --fake
```

## Boundaries

The MVP does not install packages, fetch from the network, run Docker, use
embeddings, or parse CMake with a full parser. It is intentionally deterministic
and local-first.
```

- [ ] **Step 6: Commit**

```powershell
git add docs/cmake-build-fix-mvp.md
git commit -m "docs: document cmake build-fix mvp"
```

## Self-Review

**Spec coverage:** This plan covers the approved design: CMake profile,
context scanner, error classifier, repair hints, build runner, prompt
enrichment, toy eval, real-inspired eval, trace events, and final reports.

**Placeholder scan:** The plan avoids unresolved placeholder markers. The
real-inspired fixtures are described as exact CMake scenarios with intended
fixes and verification requirements.

**Type consistency:** The plan consistently uses `CMakeContext`,
`BuildErrorSummary`, `BuildAttempt`, `FixReport`,
`scan_cmake_context`, `classify_build_output`, `run_cmake_verification`,
`build_cmake_task_prompt`, and `write_fix_report`.

**Handoff:** Claude Code should implement this plan task-by-task in an isolated
worktree. Codex should review the final branch by running the full test suite,
the fake CMake evals, inspecting at least one generated trace, and checking one
`fix_report.md`.


