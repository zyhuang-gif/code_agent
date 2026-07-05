# CMake Build-Fix MVP Design

- **Date**: 2026-07-05
- **Status**: Design approved for implementation planning
- **Project**: `code-agent`
- **Primary implementer**: Claude Code
- **Reviewer / acceptance owner**: Codex

## 1. Goal

Build the first C++/CMake-focused Build-Fix Agent layer on top of the existing
`code-agent` project. The MVP should read a real repository, understand CMake
build context, classify common configure/compile/link errors, guide the
existing agent loop toward targeted fixes, rerun the configured build/test
commands, and emit a concise fix report.

The point is not "multi-agent for its own sake." The differentiator is the
closed loop:

```text
error log / task
  -> repo context
  -> error classification
  -> repair hints
  -> edit C++ / CMake
  -> rebuild
  -> retry on failure
  -> final report
```

## 2. Current Baseline

The repository already has the important generic agent infrastructure:

- `agent/loop.py`: ReAct loop with stable prompt prefix and finish gating.
- `agent/tools.py`: `list_dir`, `read_file`, `grep`, `edit`, `run_command`,
  `write_file`, and `finish`.
- `agent/multi_agent.py`: Planner -> Coder -> Reviewer orchestration.
- `agent/profile.py`: language-agnostic project profile.
- `agent/tester.py`: configured test command runner.
- `agent/trace.py`: JSONL trace.
- `eval/run_eval.py`: benchmark runner with `--repeat` and multi-agent mode.

This MVP should reuse those pieces. It should not rewrite the loop, tools, or
eval harness except for narrow extension points needed by the CMake domain.

## 3. Product Scope

### 3.1 Must Support

The MVP supports three task families:

1. **C++ compile errors**
   - Missing project header.
   - Missing include directory.
   - Source file not attached to the right target.
   - Simple namespace/signature mismatch where tests or compiler output make
     the fix local and obvious.

2. **CMake target/link errors**
   - `undefined reference` caused by missing source file or missing local
     library target link.
   - `target_link_libraries` references a non-existent local target.
   - Executable/test target is missing required project library.

3. **Simple dependency configuration errors**
   - Missing `find_package(...)`.
   - Imported target name is wrong.
   - Header-only dependency is declared but target/include usage is incomplete.
   - Real-world dependency cases are represented as offline simplified
     fixtures first, not by installing external packages.

### 3.2 Explicitly Out Of Scope

The first version does not do these:

- Docker or container sandboxing.
- Vector database / embedding RAG.
- tree-sitter, LSP, or symbol graph.
- Automatic dependency installation.
- Network access during eval.
- Arbitrary package-manager remediation.
- Full vcpkg/Conan integration beyond static context extraction.
- Web UI.

The MVP should be boring in the right way: deterministic context, small error
taxonomy, real local builds, repeatable eval, and useful reports.

## 4. Architecture

Add a C++/CMake domain layer around the existing generic agent:

```text
main.py / eval.run_eval
  -> ProjectProfile(language="cmake", build/test commands)
  -> CMakeContextBuilder
  -> BuildErrorClassifier
  -> RepairHints
  -> AgentLoop or MultiAgentOrchestrator
  -> Build/Test Runner
  -> FixReport
```

### 4.1 New Modules

`agent/cmake_context.py`

- Scans repository structure for CMake and C++ facts.
- Produces a compact `CMakeContext` object and prompt block.
- Reads only static files and directory names; no command execution.

`agent/build_errors.py`

- Parses configure/build/test output.
- Produces a `BuildErrorSummary` with an `error_type`, key evidence lines, and
  likely files/targets/headers.
- Keeps the taxonomy intentionally small.

`agent/build_runner.py`

- Selects configured CMake commands from `ProjectProfile`.
- Builds default command sequences for CMake fixtures.
- Runs configure/build/test through the existing runner contract.

`agent/repair_hints.py`

- Converts `CMakeContext + BuildErrorSummary` into a short prompt block.
- Gives the Planner/Coder likely places to inspect and common fixes.
- Hints are advisory; the LLM must still inspect files before editing.

`agent/fix_report.py`

- Produces the final report from task, diff, command attempts, error summary,
  edited files, and final verification status.
- Writes a stable markdown report for eval/manual runs.

### 4.2 Minimal Integration Points

The existing loop should receive extra context through prompt text, not a
large rewrite. Preferred integration:

- Add a small helper that builds a task prefix for CMake tasks:
  `build_cmake_task_prompt(task, workspace, profile, initial_log=None)`.
- `real_agent_factory()` and `multi_agent_factory()` use it when
  `profile.language == "cmake"`.
- `main.py` does the same for manual runs.
- The final report can be produced after `AgentLoop.run()` returns.

This keeps `AgentLoop` generic. CMake behavior lives outside the loop unless a
small hook is clearly simpler and well tested.

## 5. Data Model

### 5.1 CMakeContext

`CMakeContext` should include:

- `root`: repository root.
- `cmake_files`: relative paths to `CMakeLists.txt` and `*.cmake`.
- `presets`: names from `CMakePresets.json` if present.
- `manifest_files`: `vcpkg.json`, `conanfile.txt`, `conanfile.py` if present.
- `source_dirs`: existing `src`, `source`, `lib`, `app` directories.
- `include_dirs`: existing `include`, `inc` directories.
- `test_dirs`: existing `test`, `tests` directories.
- `targets`: best-effort list of targets found in CMake text.
- `packages`: best-effort list from `find_package(...)`.
- `build_dirs`: ignored/generated build dirs such as `build`, `cmake-build-*`.

The scanner can use regular expressions for MVP. It does not need a full CMake
parser.

### 5.2 BuildErrorType

Use a fixed enum-like set:

- `missing_header`
- `missing_source`
- `undefined_reference`
- `missing_package`
- `missing_target`
- `cmake_config_error`
- `test_failure`
- `unknown`

### 5.3 BuildErrorSummary

Fields:

- `error_type`
- `message`
- `evidence_lines`
- `missing_header`
- `missing_symbol`
- `missing_package`
- `missing_target`
- `source_file`
- `target`
- `suggested_files`

Only fill fields supported by parsed evidence. Do not invent package names or
targets.

### 5.4 BuildAttempt

Fields:

- `command`
- `phase`: `configure`, `build`, or `test`
- `exit_code`
- `output_preview`

These attempts should also be emitted into trace events.

## 6. Profiles And Commands

Add `profiles/cmake.yaml`:

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

The local development machine currently has:

- `cmake` available.
- MinGW `g++` available.
- `mingw32-make` available.
- No `ninja`, `cl`, or `clang++` detected.

Therefore toy eval fixtures should default to `MinGW Makefiles` on Windows.
The implementation should allow task-specific `profile.yaml` files to override
the generator or command.

## 7. Eval Design

### 7.1 Toy Benchmark: `eval/tasks_cmake/`

Start with 5 deterministic tasks:

1. `c01_missing_project_header`
   - Failure: `fatal error: mathx/add.hpp: No such file or directory`.
   - Expected fix: add project `include/` to target include dirs.

2. `c02_missing_source_in_target`
   - Failure: undefined reference to a function implemented in an unlisted
     `.cpp`.
   - Expected fix: add the missing source file to the target.

3. `c03_missing_local_library_link`
   - Failure: executable calls a function from local library but is not linked
     to that target.
   - Expected fix: `target_link_libraries(app PRIVATE mathx)`.

4. `c04_wrong_target_name`
   - Failure: `target_link_libraries` references a target that does not exist.
   - Expected fix: correct the local target name.

5. `c05_test_failure_tolerance`
   - Failure: CTest runs but one simple numeric test fails due to too-strict or
     wrong local logic.
   - Expected fix: local C++ code or test tolerance, depending on fixture.

Each task has:

```text
eval/tasks_cmake/<task_id>/
  repo/
  prompt.md
  profile.yaml
  verify.py
```

`verify.py` should run the same build/test sequence and require exit code 0.

### 7.2 Real-Inspired Stretch: `eval/tasks_cmake_real/`

Add 2-3 offline simplified tasks after toy tasks pass:

1. `r01_poco_postgresql_imported_target`
   - Inspired by `PocoDataPostgreSQL requires PostgreSQL::client`.
   - Use local fake imported/interface target or a small CMake package fixture.

2. `r02_nlohmann_json_config_missing`
   - Inspired by `nlohmann_jsonConfig.cmake not found`.
   - Represent as a local vendored header-only target where the intended fix is
     to use `add_subdirectory(third_party/json)` or correct `CMAKE_PREFIX_PATH`.

3. `r03_boost_graph_header_missing`
   - Inspired by Boost Graph header missing.
   - Represent as a local include path / target usage mistake, not a network
     install task.

Real-inspired fixtures should teach the agent realistic CMake thinking while
staying deterministic and offline.

## 8. Prompting Behavior

For CMake tasks, prepend a compact context block:

```text
CMake project context:
- CMake files: CMakeLists.txt, src/CMakeLists.txt
- targets: app, mathx
- packages: none
- source dirs: src
- include dirs: include
- tests: tests

Build error summary:
- type: undefined_reference
- evidence: undefined reference to `mathx::add(int, int)`
- likely files: CMakeLists.txt, src/add.cpp

Repair hints:
- Check whether the implementation source is attached to the target.
- Check whether the executable links the local library target.
- Prefer target-based CMake commands over global include/link commands.
```

The prompt should explicitly tell the agent:

- Inspect relevant files before editing.
- Prefer narrow CMake target fixes.
- Re-run the configured CMake command before finish.
- Do not install packages or fetch from network.

## 9. Trace And Reporting

Add structured trace events:

- `cmake_context`
- `build_error_summary`
- `build_attempt`
- `fix_report`

Final report should contain:

- Task summary.
- Error type.
- Root cause in plain language.
- Files edited.
- Commands run.
- Verification result.
- Risks / follow-up.

The report can be saved as `fix_report.md` in the workspace and returned in
manual CLI output. Eval can ignore the report for pass/fail but should preserve
it for inspection.

## 10. Acceptance Criteria

MVP acceptance requires:

- Existing Python test suite still passes.
- `profiles/cmake.yaml` loads through current profile code.
- Unit tests cover CMake context scanning and build error classification.
- `eval/tasks_cmake/` contains at least 5 toy tasks.
- `python eval/run_eval.py eval/tasks_cmake --fake` still works for harness
  compatibility, even if fake agent only solves tasks after it is updated.
- Non-fake runs can execute the CMake profile command on local fixtures.
- `--multi` mode still works with the CMake prompt enrichment.
- At least one generated trace contains `cmake_context`,
  `build_error_summary`, `build_attempt`, and `fix_report`.
- Final report explains what changed and how it was verified.

Stretch acceptance:

- `eval/tasks_cmake_real/` contains at least 2 real-inspired offline tasks.
- Repeat runs with `--repeat K` report mean/std solution rates as existing eval
  already does.

## 11. Risks

- CMake generator portability: Windows currently has MinGW but not Ninja. Keep
  generator configurable per task.
- LLM may over-edit CMake. Repair hints should bias toward target-local changes.
- Build output can be long. Classifier and runner must truncate but keep the
  most useful head/tail evidence.
- Fake eval may need explicit support for CMake tasks; keep that small and
  clearly separate from real solving.
- Real dependency errors should not become network install tasks in MVP.

## 12. Implementation Strategy

Implement in small vertical slices:

1. Add profile + scanner + classifier tests.
2. Add prompt enrichment without changing generic loop semantics.
3. Add CMake toy tasks and verify scripts.
4. Add report generation and trace events.
5. Add real-inspired offline tasks.

Each slice should be testable on its own. The implementation should avoid broad
refactors and preserve existing APIs wherever possible.
