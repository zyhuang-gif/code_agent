# AgentSpec A/B Evaluation Report

LLM evals are noisy: never draw conclusions from a single solution_rate. Use mean±std and inspect traces.

## Group Summary

| Group | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped | Trace Sample |
|---|---:|---:|---:|---:|---|
| baseline | 1.000±0.000 | 7.000±0.000 | 0.001±0.000 | 0 | workspace\spec-ab\baseline\click_t2_option_prefix_parsing\run-1.trace.jsonl |
| agentspec-minimal | 1.000±0.000 | 7.000±0.000 | 0.001±0.000 | 0 | workspace\spec-ab\agentspec-minimal\click_t2_option_prefix_parsing\run-1.trace.jsonl |
| agentspec-full | 1.000±0.000 | 8.000±0.000 | 0.001±0.000 | 0 | workspace\spec-ab\agentspec-full\click_t2_option_prefix_parsing\run-1.trace.jsonl |

## Per Task

### baseline

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t2_option_prefix_parsing | 1 | 1.000±0.000 | 7.000±0.000 | 0.001±0.000 | 0 |

### agentspec-minimal

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t2_option_prefix_parsing | 1 | 1.000±0.000 | 7.000±0.000 | 0.001±0.000 | 0 |

### agentspec-full

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t2_option_prefix_parsing | 1 | 1.000±0.000 | 8.000±0.000 | 0.001±0.000 | 0 |

## Skipped Runs

- none
