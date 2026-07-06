# AgentSpec A/B Evaluation Report

LLM evals are noisy: never draw conclusions from a single solution_rate. Use mean±std and inspect traces.

## Group Summary

| Group | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped | Trace Sample |
|---|---:|---:|---:|---:|---|
| baseline | 1.000±0.000 | 12.000±0.000 | 0.003±0.000 | 0 | workspace\spec-ab-smoke\baseline\click_t1_short_help_truncation\run-1.trace.jsonl |
| agentspec-minimal | 1.000±0.000 | 8.000±0.000 | 0.002±0.000 | 0 | workspace\spec-ab-smoke\agentspec-minimal\click_t1_short_help_truncation\run-1.trace.jsonl |
| agentspec-full | 1.000±0.000 | 8.000±0.000 | 0.002±0.000 | 0 | workspace\spec-ab-smoke\agentspec-full\click_t1_short_help_truncation\run-1.trace.jsonl |

## Per Task

### baseline

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 1 | 1.000±0.000 | 12.000±0.000 | 0.003±0.000 | 0 |

### agentspec-minimal

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 1 | 1.000±0.000 | 8.000±0.000 | 0.002±0.000 | 0 |

### agentspec-full

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 1 | 1.000±0.000 | 8.000±0.000 | 0.002±0.000 | 0 |

## Skipped Runs

- none
