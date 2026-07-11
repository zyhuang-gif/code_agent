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

When the selected Profile declares `test_cmd`, managed runs execute a baseline before the Agent and re-run the command before every `finish`. New failures block Finish through governance hooks; passing tests and baseline-only failures may complete.

The existing Python Eval harness can drive the managed TypeScript CLI while retaining Python task discovery, setup, verification, and reporting:

```powershell
python eval\run_eval.py eval\tasks --runtime typescript --fake
```

In TypeScript Eval, `--fake` selects each task's versioned `model-script.json`. The scripted calls still pass through the normal tool registry, permissions, hooks, and Finish Gate; task behavior is not compiled into the engine. Direct CLI smoke tests can select a script with `--model-script <json>`, which is mutually exclusive with CLI `--fake`.

Remove Eval `--fake` for a real model run and configure `CODE_AGENT_API_KEY` or `DEEPSEEK_API_KEY`. `--budget-steps` applies the same step budget to Python and TypeScript runs. Eval reports include runtime/mode metadata, token usage, managed artifact paths, and structured infrastructure errors; exit codes are 0 for all solved, 1 for verifier failures, and 2 for infrastructure errors.

Host shell is still disabled by default. Real tasks that require it must add `--allow-unsafe-host-shell`, which explicitly enables non-interactive `bypass` permissions. This is not an OS sandbox; use the flag only for controlled Eval repositories until GOV-05 is implemented.

## TypeScript migration roadmap

The prioritized migration backlog is stored in docs/roadmap/2026-07-11-typescript-runtime-roadmap.md. Completed task specifications are indexed in docs/tasks/README.md.
