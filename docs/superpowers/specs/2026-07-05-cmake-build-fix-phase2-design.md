# CMake Build-Fix Phase 2 Design

## Summary

Phase 2 turns the CMake Build-Fix MVP from a deterministic toy/fake loop into a
more credible real-run hardening layer. The work stays local-first and scoped to
C++/CMake build repair: richer failure classification, richer static CMake
context, better prompt evidence, stronger fix reports, observable eval runs, and
a larger real-inspired benchmark.

The implementation must not rewrite the agent loop, replace the eval harness, or
introduce Docker, vector databases, tree-sitter, LSP, dependency installation, or
network access. The existing MVP module boundaries remain the architecture.

## Goals

- Classify common real CMake/C++ failures beyond the MVP patterns.
- Capture enough CMake context for the agent to reason about targets, links,
  include paths, source lists, subdirectories, presets, and manifest hints.
- Preserve initial and final verification evidence in prompt, trace, report, and
  eval output.
- Add a real-inspired benchmark set large enough to show progress after the
  first MVP.
- Keep fake eval deterministic so CI-style local validation remains fast.

## Non-Goals

- No package install, package manager invocation, or network fetch.
- No Docker sandbox or remote runner.
- No embedding/RAG stack.
- No UI in this phase.
- No broad refactor of AgentLoop, ToolRegistry, editor, or multi-agent code.
- No destructive filesystem operations during agent runs.

## Architecture

Phase 2 extends the current CMake profile path only. The feature remains gated by
`profile.language == "cmake"` in `main.py` and `eval/run_eval.py`.

The current MVP modules remain the ownership boundaries:

- `agent/build_errors.py` owns parsing and structured failure summaries.
- `agent/cmake_context.py` owns static repository context extraction.
- `agent/build_runner.py` owns command splitting, phase labeling, and build
  attempt records.
- `agent/cmake_prompt.py` owns prompt rendering and trace events derived from
  CMake context and initial verification.
- `agent/repair_hints.py` owns short targeted repair guidance.
- `agent/fix_report.py` owns final markdown and trace report data.
- `eval/run_eval.py` owns benchmark execution and eval summaries.

The data flow stays:

1. Run configured CMake verification before the agent edits.
2. Classify the first failing attempt and preserve all attempt summaries.
3. Scan static CMake context.
4. Build a CMake-specific prompt containing repository context, failure summary,
   repair hints, and verification rules.
5. Let the existing agent loop edit and call tools.
6. Run CMake verification again.
7. Write `fix_report.md`, `final.diff`, trace events, and eval summary metadata.

## Failure Classification

The parser should recognize at least these families:

- `missing_header`: GCC/Clang fatal include errors and MSVC C1083 include errors.
- `undefined_reference`: GNU/Clang undefined reference messages.
- `unresolved_external`: MSVC LNK2019/LNK2001 style unresolved external errors.
- `link_library_missing`: linker cannot find `-lfoo` or `foo.lib`.
- `missing_target`: CMake target link references a target that was not found.
- `missing_package`: CMake package config or module package was not found.
- `missing_source`: build tool cannot make a listed source/generated file target.
- `cmake_config_error`: CMake configure step failed without a narrower match.
- `test_failure`: CTest or verification failure.
- `unknown`: no known pattern.

`BuildErrorSummary` should remain backward compatible. New fields must have
defaults so existing tests and callers keep working. Good candidates are
`phase`, `tool`, `missing_library`, `missing_source`, `test_name`, and
`failing_command`.

## CMake Context

The static context should remain regex-based and deterministic. It should add
useful target-local context without trying to parse full CMake syntax.

The scanner should collect:

- CMake files and preset names, as in the MVP.
- Manifest files and dependency names from `vcpkg.json` when present.
- Declared targets from `add_executable` and `add_library`.
- `target_sources(<target> ...)` entries.
- `target_include_directories(<target> ...)` entries.
- `target_link_libraries(<target> ...)` entries.
- `add_subdirectory(...)` entries.
- Build directories that already exist, without including their generated files.

Rendering must stay compact. The prompt should include only high-signal context,
with sorted relative paths and short lists.

## Prompt And Trace

The prompt should show:

- Initial verification attempts with phase, command, exit code, and short output.
- The first failing phase and structured error summary.
- Relevant CMake context.
- Repair hints tied to the error type and known targets.
- Rules against installing packages or fetching from the network.

Trace events should remain JSONL and append-only. CMake runs should include:

- `build_attempt`
- `cmake_context`
- `build_error_summary`
- `cmake_attempt_summary`
- `fix_report`

The trace payloads should avoid large raw logs and use output previews.

## Fix Report

`fix_report.md` should become the primary human artifact for reviewing a run.
It should include:

- Task.
- Initial failure type, phase, root cause, and evidence.
- Edited files.
- Verification commands.
- Final verification status.
- Final failure type and evidence when verification still fails.
- Risks.
- Agent finish summary.

The report must be useful when the agent fails. A failed report should explain
what was attempted and what still fails, rather than only saying verification
failed.

## Eval Observability

The eval harness should keep deterministic fake runs while adding better
metadata for real runs:

- Per-run reason, step count, and cost.
- Optional artifact paths for trace, report, final diff, and workspace.
- Failure output from the verification script, truncated to a reasonable size.
- JSON summary output option for later benchmark comparison.

Existing `--fake`, `--multi`, and `--repeat` behavior must keep working.

## Benchmark

Add eight new real-inspired CMake tasks under `eval/tasks_cmake_real`, bringing
the real-inspired set from 2 to 10 tasks. Each task must be offline and
self-contained. The fake agent must solve all new fixtures deterministically so
`eval/tasks_cmake_real --fake` remains a stable acceptance test.

Suggested new cases:

- Vendored Boost Graph include directory missing.
- Gperftools imported target provided by local CMake helper but not included.
- PETSc pkg-config style dependency replaced by local offline target.
- Generated config header include directory missing.
- CTest working directory wrong for a data-file test.
- Local library source file omitted from target.
- Transitive local library link missing.
- Compile definition missing for a feature-gated code path.

## Error Handling

- Regex parsing must degrade to `unknown` instead of raising.
- Invalid JSON manifests or presets must be ignored, not fatal.
- Eval artifact writing must not make a solved task fail.
- Build artifact ignore rules must continue to keep generated CMake files out of
  baseline commits and final diffs.
- Long logs must be truncated before entering prompt, trace, or eval summary.

## Acceptance Criteria

- `pytest -q` passes.
- `eval/tasks_cmake --fake` solves 5/5.
- `eval/tasks_cmake_real --fake` solves 10/10.
- A manual CMake fake smoke run writes `fix_report.md`, `final.diff`, and trace
  without crashing.
- Trace for the smoke run contains `cmake_context`, `build_error_summary`,
  `cmake_attempt_summary`, `build_attempt`, `run_summary`, and `fix_report`.
- Generated CMake build artifacts do not appear in `final.diff` or edited files.
- No Docker, vector DB, tree-sitter, LSP, dependency installation, or network
  access is introduced.

## Risks

- Regex-based CMake parsing can miss complex multi-line or generator-expression
  cases. Phase 2 accepts this and aims for high-signal common cases only.
- More eval fixtures can make the fake agent look stronger than the real agent.
  Reports and trace metadata are included so real-run failures remain actionable.
- Windows command quoting can be fragile. Existing CMake profile commands remain
  unchanged unless a task requires a local fixture-specific profile.
