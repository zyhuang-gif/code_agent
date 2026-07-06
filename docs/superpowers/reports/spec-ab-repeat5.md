# AgentSpec A/B Evaluation Report

LLM evals are noisy: never draw conclusions from a single solution_rate. Use mean±std and inspect traces.

## Group Summary

| Group | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped | Trace Sample |
|---|---:|---:|---:|---:|---|
| baseline | 0.900±0.300 | 16.850±8.150 | 0.004±0.002 | 0 | workspace\spec-ab\baseline\click_t1_short_help_truncation\run-1.trace.jsonl |
| agentspec-minimal | 1.000±0.000 | 15.600±7.158 | 0.004±0.002 | 0 | workspace\spec-ab\agentspec-minimal\click_t1_short_help_truncation\run-1.trace.jsonl |
| agentspec-full | 1.000±0.000 | 16.900±7.327 | 0.004±0.002 | 0 | workspace\spec-ab\agentspec-full\click_t1_short_help_truncation\run-1.trace.jsonl |

## Per Task

### baseline

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 5 | 1.000±0.000 | 9.600±1.020 | 0.002±0.000 | 0 |
| click_t2_option_prefix_parsing | 5 | 1.000±0.000 | 10.400±4.630 | 0.001±0.001 | 0 |
| click_t3_preserve_paragraph_wrapping | 5 | 1.000±0.000 | 19.600±2.577 | 0.005±0.001 | 0 |
| sympy__sympy-24443 | 5 | 0.600±0.490 | 27.800±3.868 | 0.006±0.001 | 0 |

### agentspec-minimal

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 5 | 1.000±0.000 | 10.200±0.748 | 0.002±0.001 | 0 |
| click_t2_option_prefix_parsing | 5 | 1.000±0.000 | 9.000±1.095 | 0.001±0.000 | 0 |
| click_t3_preserve_paragraph_wrapping | 5 | 1.000±0.000 | 23.000±1.673 | 0.007±0.001 | 0 |
| sympy__sympy-24443 | 5 | 1.000±0.000 | 20.200±7.194 | 0.004±0.001 | 0 |

### agentspec-full

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 5 | 1.000±0.000 | 12.400±2.871 | 0.004±0.001 | 0 |
| click_t2_option_prefix_parsing | 5 | 1.000±0.000 | 9.200±1.327 | 0.001±0.000 | 0 |
| click_t3_preserve_paragraph_wrapping | 5 | 1.000±0.000 | 20.600±5.352 | 0.006±0.001 | 0 |
| sympy__sympy-24443 | 5 | 1.000±0.000 | 25.400±3.262 | 0.006±0.001 | 0 |

## Skipped Runs

- none
