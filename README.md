# code_agent
## Eval

Real eval tasks that declare `test_cmd` assume the project virtualenv is active and pytest is installed. On Windows, run from the repository root, for example:

```powershell
.\.venv\Scripts\Activate.ps1
python eval\run_eval.py
```

## TypeScript runtime

A new four-layer TypeScript runtime now lives under `src/`. The Python runtime remains available during the incremental migration.

`npm install`

`npm run check:ts`

`npm run start:ts -- --fake --json --task "smoke" --repo <source-repo> --run-root <external-run-root> --profile profiles/node.yaml --extensions extensions`

See `docs/architecture/ts-runtime-foundation.md` for layer boundaries and migration status.

Host shell execution is disabled by default. Use `--allow-host-shell` only when you explicitly accept unsandboxed shell access; it still passes through permission governance.

`--profile <yaml>` loads the existing snake_case Project Profile format once at startup. Its ignore patterns, maximum readable file size, and default command timeout configure the built-in tools; setup and verification commands are reserved for the verification gate.

Managed runs persist `final.diff`, `result.json`, and an ordered `trace.jsonl` under the external run artifact directory. `verification.json` has a stable reserved path for the verification gate.

## TypeScript migration roadmap

The prioritized migration backlog is stored in docs/roadmap/2026-07-11-typescript-runtime-roadmap.md. Completed task specifications are indexed in docs/tasks/README.md.
