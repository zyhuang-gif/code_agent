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
