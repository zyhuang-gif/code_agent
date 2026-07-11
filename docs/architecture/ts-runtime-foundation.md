# TypeScript runtime foundation

This repository is migrating incrementally from the Python prototype to a TypeScript runtime. The existing Python implementation and evaluation harness remain the behavioral reference until the TypeScript runtime reaches parity.

## Core layers

`src/engine/`

- Coordinates the model/tool loop, sessions, events, stopping, and dispatch.
- Contains no language or build-system business logic.
- Does not perform direct file, Git, or subprocess operations.

`src/tools/`

- Defines every executable agent capability through one `ToolDefinition` contract.
- Every tool declares access, impact, concurrency, idempotence, and open-world properties.
- Built-in file, search, edit, shell, and finish tools live here.

`src/services/`

- Contains only shared runtime infrastructure: model API access, context management/compaction, and MCP connection/tool discovery.
- MCP providers publish normalized tools into the regular tool registry.

`src/governance/`

- Cross-cutting permission, hook, and execution-safety controls.
- `GovernedToolExecutor` is the only route from the engine to concrete tools.
- Bash commands receive dynamic risk classification before permission evaluation.
- JSONL trace persistence serializes Host, Engine, and Hook events through one ordered sink.
- Verification commands use a governance runner; a `pre_tool_use` Hook blocks `finish` when comparison finds new failures.

`src/host/`

- Owns process-boundary concerns outside the four-layer kernel: managed run layout, isolated workspace preparation, and Project Profile loading.
- Loads snake_case YAML into a typed `ProjectProfile`; the CLI maps only tool-relevant values into `src/tools/` configuration.

## Extensions

`src/extensions/` contains generic extension loading and skill registration. Product features live outside the four-layer kernel under `extensions/`.

The first extension is `extensions/cmake`. It is a skill, not an engine branch. The engine has no CMake imports or routing condition. Models discover it through the generic `invoke_skill` tool.

## Dependency rules

- Engine may depend on layer contracts, but not on extensions or direct filesystem/process APIs.
- Tools do not import engine, services, governance, or extensions.
- Services do not import engine, governance, or extensions.
- Governance wraps tools but does not import engine, services, or extensions.
- Extensions may contribute skills and tools through public contracts.

These rules are enforced by `tests-ts/architecture.test.ts`.

## Commands

`npm install`

`npm run typecheck`

`npm run test:ts`

`npm run build`

Fake CLI smoke test:

`npm run start:ts -- --fake --json --task "smoke" --repo <source-repo> --run-root <external-run-root> --profile profiles/node.yaml --extensions extensions`

Host shell tools are not registered by default. `--allow-host-shell` is an explicit unsandboxed opt-in and shell commands are always governed as write/open-world capabilities.

Real model execution reads:

- `CODE_AGENT_API_KEY` or `DEEPSEEK_API_KEY`
- `CODE_AGENT_BASE_URL` (optional)
- `CODE_AGENT_MODEL` (optional)
- `CODE_AGENT_REASONING_EFFORT` (optional)

## Current migration boundary

Implemented in TypeScript:

- Managed workspace isolation, hardened Git checkpoint/rollback, final diff and result artifacts
- Stable managed result schema, trace.jsonl lifecycle audit, and reserved verification artifact
- Baseline/final test verification, failure fingerprint comparison, and Finish Gate
- Python-compatible Project Profile YAML loading and built-in tool configuration
- Agent runtime and JSON event stream
- Unified tool contracts and registry
- File/search/edit/Bash/finish tools
- Tool input validation
- Tool concurrency scheduling
- Permission decisions and approvals
- Hook lifecycle bus
- Bash risk classification
- Context compaction service
- OpenAI-compatible model service
- MCP provider abstraction
- Generic extension and skill loading
- CMake build-fix skill

Still using the Python implementation as the reference:

- Existing Eval runners and result reports
- CMake structured scanners, classifiers, reports, and repair memory
- Multi-agent planner/coder/reviewer parity
- Strong OS-level sandboxing

## Roadmap and active tasks

- Migration roadmap: ../roadmap/2026-07-11-typescript-runtime-roadmap.md
- Active task index: ../tasks/README.md
- Completed TS-01 specification: ../tasks/TS-01-workspace-checkpoint.md
- Completed TS-02 specification: ../tasks/TS-02-project-profile.md
- Completed TS-03 specification: ../tasks/TS-03-verification-gate.md
- Completed TS-04 specification: ../tasks/TS-04-trace-artifacts.md
- Next task: TS-05 Python Eval bridge
