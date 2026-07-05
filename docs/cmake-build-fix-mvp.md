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

## Phase 3 — Repo Context + Repair Memory

Phase 3 adds persistent project-level repair memory: each CMake fix is recorded
and automatically reused in future CMake fix runs.

### repair_memory.jsonl Lifecycle

1. **Before run** (`main.py`): reads `repair_memory.jsonl` from the **source
   repo**, matches historical cases against the current build error, and injects
   matching passed cases into the prompt (section `Relevant repair memory:`).
2. **After run** (`main.py` or `eval/run_eval.py`): reads artifact files
   (`fix_report.md`, trace JSONL, `final.diff`) via
   `extract_repair_case_from_artifacts()` and appends a new case to the JSONL.
3. **main.py** writes the JSONL to the **original source repo** (not the copied
   workspace). **eval/run_eval.py** writes it to the **copied workspace** to
   keep eval fixtures isolated.

### Matching

- Pure local scoring on `error_type` exact match (40 pts) + keyword token
  overlap (up to 30 pts) + edited file overlap (up to 20 pts) + phase match (10
  pts).
- No vector DB, embeddings, database, tree-sitter, LSP, or network.
- Only cases with `verification_status == "passed"` are injected by default.

### AGENTS.generated.md Generator

```powershell
python -m agent.project_agents <repo> --profile profiles/cmake.yaml --output <repo>\AGENTS.generated.md
```

Generates a reviewable project context file with sections: Project Context,
Build And Test, CMake Context, Repair Memory, Agent Instructions. Never
overwrites `AGENTS.md`.

### Memory Eval Benchmark

```powershell
python eval/run_eval.py eval/tasks_cmake_memory --fake
```

Two tasks:
- `m01_without_memory`: no `repair_memory.jsonl` — verifies prompt/trace/report
  do NOT contain repair memory content.
- `m02_with_memory`: pre-seeded `repair_memory.jsonl` — verifies prompt contains
  `Relevant repair memory:` and seed case id, trace contains
  `repair_memory_matches`, and `fix_report.md` contains `## Repair Memory Used`.

### Commands

```powershell
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe -m pytest
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake --fake
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake_real --fake
D:\source\agent\code_agent\code-agent\.venv\Scripts\python.exe eval\run_eval.py eval\tasks_cmake_memory --fake
```

### Boundaries (unchanged from Phase 2)

No Docker, vector DB, embeddings, tree-sitter, LSP, network install, or UI.
Only `profile.language == "cmake"` triggers repair memory behavior.
