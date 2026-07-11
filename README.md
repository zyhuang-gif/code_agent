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

`npm run start:ts -- --fake --json --task "smoke" --repo <source-repo> --run-root <external-run-root> --extensions extensions`

See `docs/architecture/ts-runtime-foundation.md` for layer boundaries and migration status.

Host shell execution is disabled by default. Use `--allow-host-shell` only when you explicitly accept unsandboxed shell access; it still passes through permission governance.

## TypeScript migration roadmap

The prioritized migration backlog is stored in docs/roadmap/2026-07-11-typescript-runtime-roadmap.md. The next implementation specification is docs/tasks/TS-01-workspace-checkpoint.md.
