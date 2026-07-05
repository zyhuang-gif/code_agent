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
