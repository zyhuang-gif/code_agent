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

`npm run start:ts -- --fake --json --task "smoke" --workspace . --extensions extensions`

See `docs/architecture/ts-runtime-foundation.md` for layer boundaries and migration status.

## TypeScript migration roadmap

The prioritized migration backlog is stored in docs/roadmap/2026-07-11-typescript-runtime-roadmap.md. The next implementation specification is docs/tasks/TS-01-workspace-checkpoint.md.
