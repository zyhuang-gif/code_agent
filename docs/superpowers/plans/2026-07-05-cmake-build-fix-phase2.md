# CMake Build-Fix Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the CMake Build-Fix MVP for more credible real C++/CMake repair runs with richer classification, context, reports, eval artifacts, and a 10-case real-inspired benchmark.

**Architecture:** Extend the current CMake-only path behind `profile.language == "cmake"`. Keep ownership in the existing modules: `build_errors`, `cmake_context`, `build_runner`, `cmake_prompt`, `repair_hints`, `fix_report`, and `eval/run_eval.py`. Do not rewrite `AgentLoop`, `ToolRegistry`, or the eval harness.

**Tech Stack:** Python 3, pytest, existing local CMake profile, deterministic fake eval, no new runtime dependencies.

## Global Constraints

- Work only in the phase branch/worktree, not directly in the main checkout.
- Do not introduce Docker, vector DB, tree-sitter, LSP, dependency installation, or network access.
- Keep CMake behavior gated by `profile.language == "cmake"`.
- Preserve existing CLI behavior for `main.py`, `eval/run_eval.py --fake`, `--multi`, and `--repeat`.
- Add tests before implementation for each behavior change.
- Commit after each task with only the files touched by that task.
- Generated CMake build artifacts must not appear in `final.diff`, reports, or committed files.

---

## File Structure

- Modify `agent/build_errors.py`: richer regex classification and backward-compatible `BuildErrorSummary` fields.
- Modify `tests/test_build_errors.py`: new classification coverage.
- Modify `agent/cmake_context.py`: target links, sources, include dirs, subdirectories, and vcpkg dependency extraction.
- Modify `tests/test_cmake_context.py`: context v2 coverage.
- Modify `agent/build_runner.py`: attempt summary helper for prompt, trace, and report.
- Modify `tests/test_build_runner.py`: attempt summary coverage.
- Modify `agent/cmake_prompt.py`: initial attempt rendering and `cmake_attempt_summary` trace event.
- Modify `tests/test_cmake_prompt.py`: prompt and trace coverage.
- Modify `agent/repair_hints.py`: hints for new error families.
- Modify `agent/fix_report.py`: initial/final failure sections and richer trace payload.
- Modify `tests/test_fix_report.py`: markdown and trace coverage.
- Modify `eval/run_eval.py`: artifact metadata, `final.diff` for eval real-agent runs, `--json-summary`.
- Modify `tests/test_eval.py`: eval artifact and JSON summary coverage.
- Add tasks under `eval/tasks_cmake_real/r03_*` through `r10_*`.
- Modify `docs/cmake-build-fix-mvp.md`: document Phase 2 commands and boundaries.

---

### Task 1: Expand Build Failure Classification

**Files:**
- Modify: `agent/build_errors.py`
- Modify: `tests/test_build_errors.py`

**Interfaces:**
- Consumes: Existing callers of `classify_build_output(output)`.
- Produces: `classify_build_output(output: str, phase: str | None = None, command: str | None = None) -> BuildErrorSummary`.
- Produces: `BuildErrorSummary` remains backward compatible and adds defaulted fields: `phase`, `tool`, `missing_library`, `missing_source`, `test_name`, `failing_command`.

- [ ] **Step 1: Write failing tests for new patterns**

Append these tests to `tests/test_build_errors.py`:

```python
def test_classifies_msvc_missing_header():
    output = "src\\main.cpp(3): fatal error C1083: Cannot open include file: 'mathx/add.hpp': No such file or directory"

    summary = classify_build_output(output, phase="build", command="cmake --build build")

    assert summary.error_type == "missing_header"
    assert summary.missing_header == "mathx/add.hpp"
    assert summary.phase == "build"
    assert summary.failing_command == "cmake --build build"
    assert summary.source_file == "src/main.cpp"


def test_classifies_cmake_could_not_find_package():
    output = "CMake Error at CMakeLists.txt:7 (find_package):\n  Could NOT find Gperftools (missing: GPERFTOOLS_LIBRARIES)"

    summary = classify_build_output(output, phase="configure")

    assert summary.error_type == "missing_package"
    assert summary.missing_package == "Gperftools"
    assert summary.phase == "configure"


def test_classifies_missing_link_library_from_gnu_linker():
    output = "C:/mingw/bin/ld.exe: cannot find -lprofiler: No such file or directory\ncollect2.exe: error: ld returned 1 exit status"

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "link_library_missing"
    assert summary.missing_library == "profiler"
    assert summary.phase == "build"


def test_classifies_missing_link_library_from_msvc_linker():
    output = "LINK : fatal error LNK1104: cannot open file 'profiler.lib'"

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "link_library_missing"
    assert summary.missing_library == "profiler.lib"


def test_classifies_msvc_unresolved_external():
    output = "main.obj : error LNK2019: unresolved external symbol \"int __cdecl mathx::add(int,int)\" referenced in function main"

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "unresolved_external"
    assert "mathx::add" in summary.missing_symbol


def test_classifies_missing_source_from_ninja_output():
    output = "ninja: error: 'src/generated.cpp', needed by 'CMakeFiles/app.dir/src/generated.cpp.obj', missing and no known rule to make it"

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "missing_source"
    assert summary.missing_source == "src/generated.cpp"


def test_classifies_ctest_named_failure():
    output = "The following tests FAILED:\n\t  1 - scale_test (Failed)\nErrors while running CTest"

    summary = classify_build_output(output, phase="test")

    assert summary.error_type == "test_failure"
    assert summary.test_name == "scale_test"
    assert summary.phase == "test"
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_build_errors.py -q
```

Expected: the new tests fail because the fields and patterns do not exist yet.

- [ ] **Step 3: Add defaulted fields to `BuildErrorSummary`**

In `agent/build_errors.py`, extend the dataclass without removing existing
fields:

```python
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
```

- [ ] **Step 4: Add regexes and helper functions**

Add regex constants near the existing ones:

```python
MSVC_MISSING_HEADER_RE = re.compile(
    r"(?P<source>[A-Za-z0-9_./\\:-]+\.(?:cpp|cc|cxx|c|hpp|h))\(\d+\):\s*fatal error C1083:\s*Cannot open include file:\s*'(?P<header>[^']+)'",
    re.IGNORECASE,
)
CMAKE_COULD_NOT_FIND_RE = re.compile(r"Could NOT find\s+([A-Za-z0-9_.:+-]+)", re.IGNORECASE)
GNU_LINK_LIBRARY_RE = re.compile(r"cannot find -l([A-Za-z0-9_.:+-]+)", re.IGNORECASE)
MSVC_LINK_LIBRARY_RE = re.compile(r"LNK1104:\s*cannot open file '([^']+)'", re.IGNORECASE)
MSVC_UNRESOLVED_RE = re.compile(r"LNK(?:2019|2001):\s*unresolved external symbol\s+\"?([^\"\n]+)\"?", re.IGNORECASE)
MISSING_SOURCE_RE = re.compile(r"['\"]([^'\"]+\.(?:cpp|cc|cxx|c|h|hpp))['\"].*missing and no known rule to make it", re.IGNORECASE)
CTEST_FAILED_RE = re.compile(r"\d+\s+-\s+([A-Za-z0-9_.:+-]+)\s+\(Failed\)", re.IGNORECASE)
```

Add a helper:

```python
def _base_kwargs(phase: str | None, command: str | None) -> dict[str, str | None]:
    return {"phase": phase, "failing_command": command}
```

- [ ] **Step 5: Update `classify_build_output` signature and branches**

Change the signature:

```python
def classify_build_output(output: str, phase: str | None = None, command: str | None = None) -> BuildErrorSummary:
```

Use `_base_kwargs(phase, command)` in every returned `BuildErrorSummary`.
Add new branches before the broad `CMake Error` branch. Keep the existing MVP
branches intact.

For MSVC missing header, return `error_type="missing_header"`, normalize
backslashes in `source_file`, and set `missing_header`.

For GNU/MSVC link library missing, return `error_type="link_library_missing"` and
set `missing_library`.

For MSVC unresolved external, return `error_type="unresolved_external"` and set
`missing_symbol`.

For missing source, return `error_type="missing_source"` and set
`missing_source`.

For CTest named failure, return `error_type="test_failure"` and set `test_name`.

- [ ] **Step 6: Add repair hints for new error types**

In `agent/repair_hints.py`, add branches:

```python
    elif summary.error_type == "unresolved_external":
        lines.extend(
            [
                f"- Check whether the symbol implementation is compiled or linked through {cmake_files}.",
                "- Prefer adding the missing source to the producing target or linking the local library target.",
            ]
        )
    elif summary.error_type == "link_library_missing":
        lines.extend(
            [
                f"- Check target_link_libraries entries in {cmake_files}.",
                "- Prefer a local imported target or vendored target already present in the repository.",
                "- Do not install system libraries or fetch packages from the network.",
            ]
        )
    elif summary.error_type == "missing_source":
        lines.extend(
            [
                f"- Check target source lists in {cmake_files}.",
                "- Remove stale generated source references or add the existing source file to the correct target.",
            ]
        )
```

- [ ] **Step 7: Run focused tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_build_errors.py -q
```

Expected: all `tests/test_build_errors.py` tests pass.

- [ ] **Step 8: Commit Task 1**

Run:

```powershell
git add agent/build_errors.py agent/repair_hints.py tests/test_build_errors.py
git commit -m "feat(cmake): expand build error classification

Co-Authored-By: Codex <noreply@anthropic.com>"
```

---

### Task 2: Add CMake Context V2

**Files:**
- Modify: `agent/cmake_context.py`
- Modify: `tests/test_cmake_context.py`

**Interfaces:**
- Consumes: Existing `scan_cmake_context(root, profile)` and `render_cmake_context(context)`.
- Produces: `CMakeContext` new defaulted fields: `target_sources`, `target_include_dirs`, `target_links`, `subdirectories`, `vcpkg_dependencies`.

- [ ] **Step 1: Write failing context tests**

Append to `tests/test_cmake_context.py`:

```python
def test_scan_cmake_context_extracts_target_local_relationships(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "third_party" / "json").mkdir(parents=True)
    (tmp_path / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.16)
project(Demo LANGUAGES CXX)
add_subdirectory(third_party/json)
add_library(mathx)
target_sources(mathx PRIVATE src/add.cpp src/scale.cpp)
target_include_directories(mathx PUBLIC include)
add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE mathx nlohmann_json::nlohmann_json)
""".strip(),
        encoding="utf-8",
    )

    context = scan_cmake_context(tmp_path, ProjectProfile(language="cmake"))

    assert context.subdirectories == ["third_party/json"]
    assert context.target_sources["mathx"] == ["src/add.cpp", "src/scale.cpp"]
    assert context.target_include_dirs["mathx"] == ["include"]
    assert context.target_links["app"] == ["mathx", "nlohmann_json::nlohmann_json"]


def test_scan_cmake_context_extracts_vcpkg_dependencies(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("project(Demo)\n", encoding="utf-8")
    (tmp_path / "vcpkg.json").write_text(
        '{"dependencies": ["fmt", {"name": "boost-graph"}, {"name": "poco", "features": ["postgresql"]}]}',
        encoding="utf-8",
    )

    context = scan_cmake_context(tmp_path, ProjectProfile(language="cmake"))

    assert context.vcpkg_dependencies == ["boost-graph", "fmt", "poco"]


def test_render_cmake_context_includes_relationships_compactly(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text(
        "add_library(mathx src/add.cpp)\n"
        "target_include_directories(mathx PUBLIC include)\n"
        "target_link_libraries(mathx PUBLIC Threads::Threads)\n",
        encoding="utf-8",
    )

    rendered = render_cmake_context(scan_cmake_context(tmp_path))

    assert "target links:" in rendered
    assert "mathx -> Threads::Threads" in rendered
    assert "target include dirs:" in rendered
    assert "mathx -> include" in rendered
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_cmake_context.py -q
```

Expected: the new tests fail because fields and parsing do not exist.

- [ ] **Step 3: Extend `CMakeContext`**

Add defaulted fields:

```python
    target_sources: dict[str, list[str]] = field(default_factory=dict)
    target_include_dirs: dict[str, list[str]] = field(default_factory=dict)
    target_links: dict[str, list[str]] = field(default_factory=dict)
    subdirectories: list[str] = field(default_factory=list)
    vcpkg_dependencies: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Add regexes and token cleaning helpers**

Add regexes:

```python
TARGET_SOURCES_RE = re.compile(r"\btarget_sources\s*\(\s*([A-Za-z0-9_.:+-]+)\s+([^)]*)\)", re.IGNORECASE | re.DOTALL)
TARGET_INCLUDE_RE = re.compile(r"\btarget_include_directories\s*\(\s*([A-Za-z0-9_.:+-]+)\s+([^)]*)\)", re.IGNORECASE | re.DOTALL)
TARGET_LINK_RE = re.compile(r"\btarget_link_libraries\s*\(\s*([A-Za-z0-9_.:+-]+)\s+([^)]*)\)", re.IGNORECASE | re.DOTALL)
ADD_SUBDIRECTORY_RE = re.compile(r"\badd_subdirectory\s*\(\s*([^) \n\r\t]+)", re.IGNORECASE)
```

Add helper functions:

```python
_CMAKE_SCOPE_TOKENS = {"PRIVATE", "PUBLIC", "INTERFACE"}


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
```

- [ ] **Step 5: Parse target-local context in `scan_cmake_context`**

Inside the CMake file scanning block, after reading `text`, add extraction:

```python
for match in TARGET_SOURCES_RE.finditer(text):
    _add_mapping_value(target_sources, match.group(1), _split_cmake_args(match.group(2)))
for match in TARGET_INCLUDE_RE.finditer(text):
    _add_mapping_value(target_include_dirs, match.group(1), _split_cmake_args(match.group(2)))
for match in TARGET_LINK_RE.finditer(text):
    _add_mapping_value(target_links, match.group(1), _split_cmake_args(match.group(2)))
subdirectories.extend(match.group(1).strip().strip('"') for match in ADD_SUBDIRECTORY_RE.finditer(text))
```

Initialize `target_sources`, `target_include_dirs`, `target_links`, and
`subdirectories` before the `rglob` loop. Pass sorted mappings into
`CMakeContext`.

- [ ] **Step 6: Parse vcpkg dependencies**

Add a helper:

```python
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
```

Use it when creating the context.

- [ ] **Step 7: Render new context compactly**

Add:

```python
def _mapping_lines(label: str, mapping: dict[str, list[str]], limit: int = 8) -> list[str]:
    if not mapping:
        return [f"- {label}: none"]
    rows = []
    for key in sorted(mapping)[:limit]:
        rows.append(f"  - {key} -> {', '.join(mapping[key])}")
    return [f"- {label}:"] + rows
```

Include these lines in `render_cmake_context`:

```python
*_mapping_lines("target sources", context.target_sources),
*_mapping_lines("target include dirs", context.target_include_dirs),
*_mapping_lines("target links", context.target_links),
_line("subdirectories", context.subdirectories),
_line("vcpkg dependencies", context.vcpkg_dependencies),
```

- [ ] **Step 8: Run focused tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_cmake_context.py -q
```

Expected: all `tests/test_cmake_context.py` tests pass.

- [ ] **Step 9: Commit Task 2**

Run:

```powershell
git add agent/cmake_context.py tests/test_cmake_context.py
git commit -m "feat(cmake): enrich static project context

Co-Authored-By: Codex <noreply@anthropic.com>"
```

---

### Task 3: Add Attempt Summaries To Prompt And Trace

**Files:**
- Modify: `agent/build_runner.py`
- Modify: `agent/cmake_prompt.py`
- Modify: `main.py`
- Modify: `eval/run_eval.py`
- Modify: `tests/test_build_runner.py`
- Modify: `tests/test_cmake_prompt.py`

**Interfaces:**
- Consumes: `BuildAttempt` from the MVP.
- Produces: `summarize_cmake_attempts(attempts: list[BuildAttempt]) -> dict`.
- Produces: `build_cmake_task_prompt(..., initial_attempts: list[BuildAttempt] | None = None, ...)` while preserving the existing `initial_output` argument.

- [ ] **Step 1: Write failing tests for attempt summary**

Append to `tests/test_build_runner.py`:

```python
def test_summarize_cmake_attempts_reports_first_failure():
    from agent.build_runner import BuildAttempt, summarize_cmake_attempts

    attempts = [
        BuildAttempt("cmake -S . -B build", "configure", 0, "configured"),
        BuildAttempt("cmake --build build", "build", 1, "fatal error: x.hpp: No such file or directory"),
    ]

    summary = summarize_cmake_attempts(attempts)

    assert summary["status"] == "failed"
    assert summary["first_failure"]["phase"] == "build"
    assert summary["first_failure"]["exit_code"] == 1
    assert summary["combined_output"] == "configured\nfatal error: x.hpp: No such file or directory"
```

Append to `tests/test_cmake_prompt.py`:

```python
def test_cmake_prompt_renders_attempt_summary_and_trace(tmp_path: Path):
    import json
    from agent.build_runner import BuildAttempt
    from agent.cmake_prompt import build_cmake_task_prompt
    from agent.profile import ProjectProfile
    from agent.trace import Trace

    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/main.cpp)\n", encoding="utf-8")
    trace = Trace(tmp_path / "trace.jsonl")
    attempts = [
        BuildAttempt("cmake -S . -B build", "configure", 0, "configured"),
        BuildAttempt("cmake --build build", "build", 1, "fatal error: mathx/add.hpp: No such file or directory"),
    ]

    prompt = build_cmake_task_prompt(
        "Fix build",
        tmp_path,
        ProjectProfile(language="cmake"),
        initial_attempts=attempts,
        trace=trace,
    )

    assert "Initial verification attempts:" in prompt
    assert "- build: exit_code=1 command=cmake --build build" in prompt
    assert "missing header: mathx/add.hpp" in prompt
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert "cmake_attempt_summary" in [row["t"] for row in rows]
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_build_runner.py tests\test_cmake_prompt.py -q
```

Expected: new tests fail.

- [ ] **Step 3: Implement `summarize_cmake_attempts`**

In `agent/build_runner.py`, add:

```python
def summarize_cmake_attempts(attempts: list[BuildAttempt]) -> dict[str, Any]:
    first_failure = next((attempt for attempt in attempts if attempt.exit_code != 0), None)
    return {
        "status": "passed" if attempts and attempts[-1].exit_code == 0 else "failed" if attempts else "not_run",
        "attempts": [
            {
                "phase": attempt.phase,
                "command": attempt.command,
                "exit_code": attempt.exit_code,
                "output_preview": attempt.output_preview,
            }
            for attempt in attempts
        ],
        "first_failure": None
        if first_failure is None
        else {
            "phase": first_failure.phase,
            "command": first_failure.command,
            "exit_code": first_failure.exit_code,
            "output_preview": first_failure.output_preview,
        },
        "combined_output": "\n".join(attempt.output_preview for attempt in attempts if attempt.output_preview),
    }
```

- [ ] **Step 4: Render attempts in `cmake_prompt.py`**

Import `BuildAttempt` and `summarize_cmake_attempts`. Add:

```python
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
```

Change `build_cmake_task_prompt` signature to include:

```python
    initial_attempts: list[BuildAttempt] | None = None,
```

Inside the function:

```python
attempts = initial_attempts or []
if attempts and not initial_output:
    initial_output = summarize_cmake_attempts(attempts)["combined_output"]
first_failure = next((attempt for attempt in attempts if attempt.exit_code != 0), None)
summary = classify_build_output(
    initial_output,
    phase=first_failure.phase if first_failure else None,
    command=first_failure.command if first_failure else None,
)
_write_attempt_trace(attempts, trace)
```

Include `_render_attempts(attempts)` in the returned prompt before the build
error summary.

- [ ] **Step 5: Pass attempts from main and eval**

In `main.py`, replace:

```python
task = build_cmake_task_prompt(args.task, workspace, profile, initial_output, trace)
```

with:

```python
task = build_cmake_task_prompt(args.task, workspace, profile, initial_output, trace, initial_attempts=attempts)
```

In `eval/run_eval.py`, update `_maybe_enrich_prompt` the same way:

```python
return build_cmake_task_prompt(prompt, workspace, profile, initial_output, trace, initial_attempts=attempts), initial_output
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_build_runner.py tests\test_cmake_prompt.py -q
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit Task 3**

Run:

```powershell
git add agent/build_runner.py agent/cmake_prompt.py main.py eval/run_eval.py tests/test_build_runner.py tests/test_cmake_prompt.py
git commit -m "feat(cmake): trace initial verification attempts

Co-Authored-By: Codex <noreply@anthropic.com>"
```

---

### Task 4: Upgrade Fix Reports For Initial And Final Failures

**Files:**
- Modify: `agent/fix_report.py`
- Modify: `main.py`
- Modify: `eval/run_eval.py`
- Modify: `tests/test_fix_report.py`

**Interfaces:**
- Consumes: `RunResult`, `BuildAttempt`, and initial output from existing callers.
- Produces: richer `FixReport` with initial/final error fields and evidence lists.
- Produces: `build_fix_report(..., final_output: str = "")` remains backward compatible.

- [ ] **Step 1: Write failing report tests**

Append to `tests/test_fix_report.py`:

```python
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
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_fix_report.py -q
```

Expected: new tests fail.

- [ ] **Step 3: Add fields to `FixReport`**

Add defaulted fields:

```python
    initial_error_type: str = "unknown"
    initial_phase: str | None = None
    initial_evidence: list[str] = field(default_factory=list)
    final_error_type: str = "unknown"
    final_phase: str | None = None
    final_evidence: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Add `final_output` to `build_fix_report`**

Change the signature:

```python
def build_fix_report(
    task: str,
    result: RunResult,
    attempts: list[BuildAttempt],
    workspace: Path,
    initial_output: str = "",
    final_output: str = "",
) -> FixReport:
```

Classify initial and final failures:

```python
initial_attempt = attempts[0] if attempts else None
final_attempt = attempts[-1] if attempts else None
initial_summary = classify_build_output(initial_output)
final_summary = classify_build_output(
    final_output,
    phase=final_attempt.phase if final_attempt else None,
    command=final_attempt.command if final_attempt else None,
) if final_output else classify_build_output("")
```

Keep `error_type` and `root_cause` based on the initial summary for backward
compatibility.

- [ ] **Step 5: Render new markdown sections**

In `_markdown`, insert after root cause:

```python
        "## Initial Failure",
        "",
        f"Type: {report.initial_error_type}",
        f"Phase: {report.initial_phase or 'unknown'}",
        "",
```

Then append initial evidence lines:

```python
lines.extend(f"- {line}" for line in report.initial_evidence or ["none"])
```

Before risks, add:

```python
lines.extend(["", "## Final Failure", "", f"Type: {report.final_error_type}", f"Phase: {report.final_phase or 'unknown'}", ""])
lines.extend(f"- {line}" for line in report.final_evidence or ["none"])
```

- [ ] **Step 6: Pass final output from callers**

In `main.py` and `eval/run_eval.py`, after final verification:

```python
final_output = "\n".join(attempt.output_preview for attempt in attempts)
report = build_fix_report(args.task, result, attempts, workspace, initial_output, final_output)
```

Use the correct task variable in `eval/run_eval.py`:

```python
report = build_fix_report(prompt, result, attempts, workspace, initial_output, final_output)
```

- [ ] **Step 7: Run focused tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_fix_report.py tests\test_eval.py::test_real_agent_factory_enriches_cmake_prompt -q
```

Expected: focused tests pass.

- [ ] **Step 8: Commit Task 4**

Run:

```powershell
git add agent/fix_report.py main.py eval/run_eval.py tests/test_fix_report.py
git commit -m "feat(cmake): enrich build fix reports

Co-Authored-By: Codex <noreply@anthropic.com>"
```

---

### Task 5: Add Eval Artifact Metadata And JSON Summary

**Files:**
- Modify: `eval/run_eval.py`
- Modify: `tests/test_eval.py`

**Interfaces:**
- Consumes: Existing `run_task`, `summarize`, `real_agent_factory`, and `main`.
- Produces: `EvalResult` fields `reason`, `trace_path`, `report_path`, `diff_path`, `workspace_path`, `verify_output`.
- Produces: `--json-summary <path>` CLI option.

- [ ] **Step 1: Write failing eval tests**

Append to `tests/test_eval.py`:

```python
def test_run_task_records_artifact_metadata_and_verify_output(tmp_path: Path):
    task_dir = make_task(tmp_path / "task")

    def fake_agent(workspace, prompt, profile):
        (workspace / "answer.txt").write_text("bad", encoding="utf-8")
        (workspace / "fix_report.md").write_text("# Fix Report\n", encoding="utf-8")
        (workspace / "final.diff").write_text("diff --git a/a b/a\n", encoding="utf-8")
        (workspace.parent / f"{workspace.name}.trace.jsonl").write_text('{"t":"x"}\n', encoding="utf-8")
        return {"steps": 2, "cost_usd": 0.1, "reason": "finished_with_failing_tests"}

    result = run_task(discover(tmp_path)[0], fake_agent, tmp_path / "work")

    assert result.status == "failed"
    assert result.reason == "finished_with_failing_tests"
    assert result.report_path.endswith("fix_report.md")
    assert result.diff_path.endswith("final.diff")
    assert result.trace_path.endswith("work.trace.jsonl")
    assert result.workspace_path.endswith("work")
    assert result.verify_output


def test_eval_main_writes_json_summary(tmp_path: Path):
    task_dir = make_task(tmp_path / "tasks" / "t")
    summary_path = tmp_path / "summary.json"

    def factory():
        def agent(workspace, prompt, profile):
            (workspace / "answer.txt").write_text("ok", encoding="utf-8")
            return {"steps": 1, "cost_usd": 0.0, "reason": "finished"}
        return agent

    from eval.run_eval import main

    code = main([str(task_dir.parent), "--json-summary", str(summary_path)], agent_factory=factory, work_root=tmp_path / "work")

    assert code == 0
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["solution_rate"] == 1.0
    assert data["tasks"]["t"]["runs"] == 1
```

Add `import json` near the top of `tests/test_eval.py` if it is not already
present.

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_eval.py -q
```

Expected: new tests fail.

- [ ] **Step 3: Extend `EvalResult`**

In `eval/run_eval.py`, update:

```python
@dataclass
class EvalResult:
    task_id: str
    status: str
    steps: int
    cost_usd: float
    reason: str = ""
    trace_path: str = ""
    report_path: str = ""
    diff_path: str = ""
    workspace_path: str = ""
    verify_output: str = ""
```

- [ ] **Step 4: Populate artifact metadata in `run_task`**

After `meta = agent(...)`, keep the verify subprocess and build:

```python
verify_output = f"{proc.stdout}{proc.stderr}"
trace_path = work_root.parent / f"{work_root.name}.trace.jsonl"
report_path = work_root / "fix_report.md"
diff_path = work_root / "final.diff"
return EvalResult(
    task.id,
    "solved" if proc.returncode == 0 else "failed",
    int(meta.get("steps", 0)),
    float(meta.get("cost_usd", 0.0)),
    str(meta.get("reason", "")),
    str(trace_path) if trace_path.exists() else "",
    str(report_path) if report_path.exists() else "",
    str(diff_path) if diff_path.exists() else "",
    str(work_root),
    verify_output[:4000],
)
```

- [ ] **Step 5: Include metadata in `summarize`**

For each task summary, include:

```python
"results": [
    {
        "status": result.status,
        "steps": result.steps,
        "cost_usd": result.cost_usd,
        "reason": result.reason,
        "trace_path": result.trace_path,
        "report_path": result.report_path,
        "diff_path": result.diff_path,
        "workspace_path": result.workspace_path,
        "verify_output": result.verify_output,
    }
    for result in task_results
],
```

Keep existing top-level keys unchanged.

- [ ] **Step 6: Write `final.diff` in eval real-agent paths**

In `real_agent_factory` and `multi_agent_factory`, after `result` is available:

```python
(workspace / "final.diff").write_text(result.diff, encoding="utf-8")
```

Guard with `getattr(result, "diff", "")` for compatibility:

```python
(workspace / "final.diff").write_text(getattr(result, "diff", ""), encoding="utf-8")
```

- [ ] **Step 7: Add `--json-summary` CLI option**

In `main`, add:

```python
parser.add_argument("--json-summary", type=Path)
```

After `summary = summarize(results)`:

```python
if args.json_summary:
    args.json_summary.parent.mkdir(parents=True, exist_ok=True)
    args.json_summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
```

Import `json` at the top of `eval/run_eval.py`.

- [ ] **Step 8: Run focused tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_eval.py -q
```

Expected: all eval tests pass.

- [ ] **Step 9: Commit Task 5**

Run:

```powershell
git add eval/run_eval.py tests/test_eval.py
git commit -m "feat(eval): record build-fix artifacts

Co-Authored-By: Codex <noreply@anthropic.com>"
```

---

### Task 6: Expand Real-Inspired CMake Benchmark To 10 Tasks

**Files:**
- Add: `eval/tasks_cmake_real/r03_boost_graph_include_missing/*`
- Add: `eval/tasks_cmake_real/r04_gperftools_imported_target_missing/*`
- Add: `eval/tasks_cmake_real/r05_petsc_offline_target_missing/*`
- Add: `eval/tasks_cmake_real/r06_generated_config_include_missing/*`
- Add: `eval/tasks_cmake_real/r07_ctest_working_directory/*`
- Add: `eval/tasks_cmake_real/r08_local_library_source_omitted/*`
- Add: `eval/tasks_cmake_real/r09_transitive_local_link_missing/*`
- Add: `eval/tasks_cmake_real/r10_compile_definition_missing/*`
- Modify: `eval/run_eval.py`
- Modify: `tests/test_eval.py`

**Interfaces:**
- Consumes: Existing task discovery and fake agent behavior.
- Produces: `eval/tasks_cmake_real --fake` solves 10/10.

- [ ] **Step 1: Update benchmark discovery test**

Modify `test_discovers_real_inspired_cmake_tasks` in `tests/test_eval.py`:

```python
def test_discovers_real_inspired_cmake_tasks():
    tasks = discover(Path("eval/tasks_cmake_real"))

    assert {task.id for task in tasks} == {
        "r01_poco_postgresql_imported_target",
        "r02_nlohmann_json_config_missing",
        "r03_boost_graph_include_missing",
        "r04_gperftools_imported_target_missing",
        "r05_petsc_offline_target_missing",
        "r06_generated_config_include_missing",
        "r07_ctest_working_directory",
        "r08_local_library_source_omitted",
        "r09_transitive_local_link_missing",
        "r10_compile_definition_missing",
    }
    assert all(task.profile.language == "cmake" for task in tasks)
```

- [ ] **Step 2: Run discovery test and confirm failure**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_eval.py::test_discovers_real_inspired_cmake_tasks -q
```

Expected: it fails because new tasks do not exist.

- [ ] **Step 3: Use this exact `profile.yaml` for each new task**

Create `profile.yaml` in each `r03` through `r10` directory with:

```yaml
language: cmake
test_cmd: cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure
test_timeout: 120
command_timeout: 120
ignore:
  - .git
  - build
  - build/*
  - cmake-build-*
  - _deps
  - CMakeFiles
  - CMakeCache.txt
```

- [ ] **Step 4: Create r03 vendored Boost Graph include task**

Create `prompt.md`:

```markdown
Fix the CMake build. The project uses a vendored Boost Graph header already present in the repository.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R03BoostGraph LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
```

Create `repo/src/main.cpp`:

```cpp
#include <boost/graph/adjacency_list.hpp>

int main() {
    boost::adjacency_list graph;
    return boost::num_vertices(graph) == 0 ? 0 : 1;
}
```

Create `repo/third_party/boost_graph/include/boost/graph/adjacency_list.hpp`:

```cpp
#pragma once

namespace boost {
class adjacency_list {};
inline int num_vertices(const adjacency_list&) { return 0; }
}
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: add `target_include_directories(app PRIVATE third_party/boost_graph/include)`.

- [ ] **Step 5: Create r04 Gperftools local imported target task**

Create `prompt.md`:

```markdown
Fix the CMake build. The repository includes an offline helper that defines the profiler target.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R04Gperftools LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE gperftools::profiler)
add_test(NAME app_runs COMMAND app)
```

Create `repo/cmake/GperftoolsProfiler.cmake`:

```cmake
add_library(gperftools_profiler INTERFACE)
add_library(gperftools::profiler ALIAS gperftools_profiler)
```

Create `repo/src/main.cpp`:

```cpp
int main() {
    return 0;
}
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: include `cmake/GperftoolsProfiler.cmake` before linking.

- [ ] **Step 6: Create r05 PETSc offline target task**

Create `prompt.md`:

```markdown
Fix the CMake build without using pkg-config or installing PETSc. The repository includes an offline PETSc target helper.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R05PetscOffline LANGUAGES CXX)

enable_testing()

find_package(PkgConfig REQUIRED)
pkg_check_modules(PETSC REQUIRED IMPORTED_TARGET PETSc)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE PkgConfig::PETSC)
add_test(NAME app_runs COMMAND app)
```

Create `repo/cmake/PETScOffline.cmake`:

```cmake
add_library(PETSc_petsc INTERFACE)
add_library(PETSc::petsc ALIAS PETSc_petsc)
```

Create `repo/src/main.cpp`:

```cpp
int main() {
    return 0;
}
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: replace the pkg-config block with `include(cmake/PETScOffline.cmake)` and link `PETSc::petsc`.

- [ ] **Step 7: Create r06 generated config include task**

Create `prompt.md`:

```markdown
Fix the CMake build. The configured header is generated into the build tree and should be available to the target.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R06GeneratedConfig LANGUAGES CXX)

enable_testing()

configure_file(config/app_config.hpp.in generated/app_config.hpp @ONLY)
add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
```

Create `repo/config/app_config.hpp.in`:

```cpp
#pragma once

#define APP_CONFIG_VALUE 42
```

Create `repo/src/main.cpp`:

```cpp
#include "generated/app_config.hpp"

int main() {
    return APP_CONFIG_VALUE == 42 ? 0 : 1;
}
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: add `target_include_directories(app PRIVATE ${CMAKE_CURRENT_BINARY_DIR})`.

- [ ] **Step 8: Create r07 CTest working directory task**

Create `prompt.md`:

```markdown
Fix the failing CTest. The executable expects to run from the source directory so it can read its fixture file.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R07CTestWorkingDirectory LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME reads_fixture COMMAND app)
```

Create `repo/src/main.cpp`:

```cpp
#include <fstream>
#include <string>

int main() {
    std::ifstream input("data/value.txt");
    std::string value;
    input >> value;
    return value == "ok" ? 0 : 1;
}
```

Create `repo/data/value.txt`:

```text
ok
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: set `WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}` on the `reads_fixture` test.

- [ ] **Step 9: Create r08 local library source omitted task**

Create `prompt.md`:

```markdown
Fix the undefined reference. The implementation source already exists in the repository.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R08LocalSourceOmitted LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
target_include_directories(app PRIVATE include)
add_test(NAME app_runs COMMAND app)
```

Create `repo/include/mathx/add.hpp`:

```cpp
#pragma once

namespace mathx {
int add(int left, int right);
}
```

Create `repo/src/add.cpp`:

```cpp
#include "mathx/add.hpp"

namespace mathx {
int add(int left, int right) {
    return left + right;
}
}
```

Create `repo/src/main.cpp`:

```cpp
#include "mathx/add.hpp"

int main() {
    return mathx::add(2, 3) == 5 ? 0 : 1;
}
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: add `src/add.cpp` to the `app` target.

- [ ] **Step 10: Create r09 transitive local link task**

Create `prompt.md`:

```markdown
Fix the link failure. The app links mathapp, and mathapp depends on mathcore.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R09TransitiveLocalLink LANGUAGES CXX)

enable_testing()

add_library(mathcore src/core.cpp)
target_include_directories(mathcore PUBLIC include)

add_library(mathapp src/app_math.cpp)
target_include_directories(mathapp PUBLIC include)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE mathapp)
add_test(NAME app_runs COMMAND app)
```

Create `repo/include/mathx/core.hpp`:

```cpp
#pragma once

namespace mathx {
int core_value();
int app_value();
}
```

Create `repo/src/core.cpp`:

```cpp
#include "mathx/core.hpp"

namespace mathx {
int core_value() {
    return 7;
}
}
```

Create `repo/src/app_math.cpp`:

```cpp
#include "mathx/core.hpp"

namespace mathx {
int app_value() {
    return core_value();
}
}
```

Create `repo/src/main.cpp`:

```cpp
#include "mathx/core.hpp"

int main() {
    return mathx::app_value() == 7 ? 0 : 1;
}
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: add `target_link_libraries(mathapp PUBLIC mathcore)`.

- [ ] **Step 11: Create r10 compile definition task**

Create `prompt.md`:

```markdown
Fix the failing test. The intended feature path is guarded by a compile definition.
```

Create `repo/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.16)
project(R10CompileDefinition LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME feature_enabled COMMAND app)
```

Create `repo/src/main.cpp`:

```cpp
int main() {
#ifdef ENABLE_FAST_PATH
    return 0;
#else
    return 1;
#endif
}
```

Create `verify.py`:

```python
import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
```

Expected fix: add `target_compile_definitions(app PRIVATE ENABLE_FAST_PATH)`.

- [ ] **Step 12: Extend fake agent for new fixtures**

In `eval/run_eval.py`, inside `fake_agent`, add deterministic edits:

```python
    if (workspace / "third_party" / "boost_graph" / "include").exists():
        text = cmake.read_text(encoding="utf-8")
        if "third_party/boost_graph/include" not in text:
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_include_directories(app PRIVATE third_party/boost_graph/include)\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    if (workspace / "cmake" / "GperftoolsProfiler.cmake").exists():
        text = cmake.read_text(encoding="utf-8")
        if "include(cmake/GperftoolsProfiler.cmake)" not in text:
            text = text.replace(
                "project(R04Gperftools LANGUAGES CXX)\n\n",
                "project(R04Gperftools LANGUAGES CXX)\n\ninclude(cmake/GperftoolsProfiler.cmake)\n\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    if (workspace / "cmake" / "PETScOffline.cmake").exists():
        text = cmake.read_text(encoding="utf-8")
        text = text.replace(
            "find_package(PkgConfig REQUIRED)\npkg_check_modules(PETSC REQUIRED IMPORTED_TARGET PETSc)\n\n",
            "include(cmake/PETScOffline.cmake)\n\n",
        )
        text = text.replace("PkgConfig::PETSC", "PETSc::petsc")
        cmake.write_text(text, encoding="utf-8")

    if (workspace / "config" / "app_config.hpp.in").exists():
        text = cmake.read_text(encoding="utf-8")
        if "${CMAKE_CURRENT_BINARY_DIR}" not in text:
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_include_directories(app PRIVATE ${CMAKE_CURRENT_BINARY_DIR})\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    if (workspace / "data" / "value.txt").exists():
        text = cmake.read_text(encoding="utf-8")
        text = text.replace(
            "add_test(NAME reads_fixture COMMAND app)",
            "add_test(NAME reads_fixture COMMAND app)\nset_tests_properties(reads_fixture PROPERTIES WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})",
        )
        cmake.write_text(text, encoding="utf-8")

    if (workspace / "src" / "add.cpp").exists() and "R08LocalSourceOmitted" in cmake.read_text(encoding="utf-8"):
        text = cmake.read_text(encoding="utf-8")
        text = text.replace("add_executable(app src/main.cpp)", "add_executable(app src/main.cpp src/add.cpp)", 1)
        cmake.write_text(text, encoding="utf-8")

    if (workspace / "src" / "core.cpp").exists() and (workspace / "src" / "app_math.cpp").exists():
        text = cmake.read_text(encoding="utf-8")
        if "target_link_libraries(mathapp PUBLIC mathcore)" not in text:
            text = text.replace(
                "target_include_directories(mathapp PUBLIC include)\n",
                "target_include_directories(mathapp PUBLIC include)\ntarget_link_libraries(mathapp PUBLIC mathcore)\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")

    if "R10CompileDefinition" in cmake.read_text(encoding="utf-8"):
        text = cmake.read_text(encoding="utf-8")
        if "ENABLE_FAST_PATH" not in text:
            text = text.replace(
                "add_executable(app src/main.cpp)\n",
                "add_executable(app src/main.cpp)\ntarget_compile_definitions(app PRIVATE ENABLE_FAST_PATH)\n",
                1,
            )
            cmake.write_text(text, encoding="utf-8")
```

- [ ] **Step 13: Run real-inspired fake eval**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake_real --fake
```

Expected: `total` is 10, `solved` is 10, `solution_rate` is 1.0.

- [ ] **Step 14: Run discovery test**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest tests\test_eval.py::test_discovers_real_inspired_cmake_tasks -q
```

Expected: test passes.

- [ ] **Step 15: Commit Task 6**

Run:

```powershell
git add eval/run_eval.py tests/test_eval.py eval/tasks_cmake_real/r03_boost_graph_include_missing eval/tasks_cmake_real/r04_gperftools_imported_target_missing eval/tasks_cmake_real/r05_petsc_offline_target_missing eval/tasks_cmake_real/r06_generated_config_include_missing eval/tasks_cmake_real/r07_ctest_working_directory eval/tasks_cmake_real/r08_local_library_source_omitted eval/tasks_cmake_real/r09_transitive_local_link_missing eval/tasks_cmake_real/r10_compile_definition_missing
git commit -m "feat(eval): expand real-inspired cmake benchmark

Co-Authored-By: Codex <noreply@anthropic.com>"
```

---

### Task 7: Documentation And Final Acceptance

**Files:**
- Modify: `docs/cmake-build-fix-mvp.md`

**Interfaces:**
- Consumes: all completed Phase 2 behavior.
- Produces: documented commands and boundaries for the new hardening phase.

- [ ] **Step 1: Update docs**

Append to `docs/cmake-build-fix-mvp.md`:

````markdown
## Phase 2 Hardening

Phase 2 expands the CMake Build-Fix path with richer C++/CMake failure
classification, target-local CMake context, initial/final verification evidence
in reports, eval artifact metadata, JSON eval summaries, and a 10-case
real-inspired offline benchmark.

Additional supported error families:

- MSVC C1083 missing headers.
- MSVC unresolved externals.
- Missing link libraries such as `-lprofiler` or `profiler.lib`.
- Missing source/generated files reported by build tools.
- Named CTest failures.

Additional commands:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake_real --fake --json-summary .tmp\cmake-real-summary.json
```

Acceptance remains local-first. The hardening phase still does not install
packages, fetch from the network, run Docker, use embeddings, parse CMake with a
full parser, or add UI.
````

- [ ] **Step 2: Run complete acceptance tests**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\source\agent\code_agent\code-agent\.tmp\phase2-acceptance-pytest
```

Expected: all tests pass.

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake --fake
```

Expected: `solved` is 5 and `solution_rate` is 1.0.

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake_real --fake --json-summary D:\source\agent\code_agent\code-agent\.tmp\cmake-phase2-real-summary.json
```

Expected: `solved` is 10 and `solution_rate` is 1.0. The JSON summary file exists.

- [ ] **Step 3: Run manual smoke**

Run:

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe main.py "Fix the CMake build" eval\tasks_cmake\c01_missing_project_header\repo --profile profiles\cmake.yaml --workspace D:\source\agent\code_agent\code-agent\.tmp\phase2-smoke --fake
```

Expected:

- Command exits 0.
- Output contains `fix_report=...`.
- `fix_report.md` exists.
- `final.diff` exists.
- The trace JSONL contains `cmake_context`, `build_error_summary`, `cmake_attempt_summary`, `build_attempt`, `run_summary`, and `fix_report`.
- `final.diff` does not contain CMake generated build artifacts.

- [ ] **Step 4: Check diff for accidental generated files**

Run:

```powershell
git status --short
git diff --stat
git diff --name-only
```

Expected: only intended source, tests, eval fixtures, and docs are modified.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git add docs/cmake-build-fix-mvp.md
git commit -m "docs: document cmake build-fix phase2

Co-Authored-By: Codex <noreply@anthropic.com>"
```

---

## Final Handoff Checklist

- [ ] Branch contains one commit per task.
- [ ] No generated CMake build artifacts are tracked.
- [ ] `pytest -q` passes.
- [ ] `eval/tasks_cmake --fake` solves 5/5.
- [ ] `eval/tasks_cmake_real --fake` solves 10/10.
- [ ] Manual smoke writes report, diff, and trace.
- [ ] `--json-summary` writes a valid JSON summary.
- [ ] No Docker, vector DB, tree-sitter, LSP, network install, or UI code was added.

## Notes For Claude Code

Implement this plan exactly in order. If a step exposes a real incompatibility,
stop after the smallest failing evidence and explain the blocker instead of
rewriting the architecture. Keep all changes scoped to the files named in each
task. Do not merge or push the branch.
