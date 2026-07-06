# AgentSpec A/B Evaluation Report

LLM evals are noisy: never draw conclusions from a single solution_rate. Use mean±std and inspect traces.

## Group Summary

| Group | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped | Trace Sample |
|---|---:|---:|---:|---:|---|
| baseline | 0.917±0.276 | 14.750±8.094 | 0.004±0.002 | 0 | workspace\spec-ab-runs\baseline\click_t1_short_help_truncation\run-1.trace.jsonl |
| agentspec-minimal | 1.000±0.000 | 14.833±7.104 | 0.004±0.002 | 0 | workspace\spec-ab-runs\agentspec-minimal\click_t1_short_help_truncation\run-1.trace.jsonl |
| agentspec-full | 1.000±0.000 | 15.083±7.205 | 0.004±0.002 | 0 | workspace\spec-ab-runs\agentspec-full\click_t1_short_help_truncation\run-1.trace.jsonl |

## Per Task

### baseline

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 3 | 1.000±0.000 | 8.000±2.160 | 0.002±0.000 | 0 |
| click_t2_option_prefix_parsing | 3 | 1.000±0.000 | 8.333±0.943 | 0.001±0.000 | 0 |
| click_t3_preserve_paragraph_wrapping | 3 | 0.667±0.471 | 25.000±1.633 | 0.006±0.000 | 0 |
| sympy__sympy-24443 | 3 | 1.000±0.000 | 17.667±7.318 | 0.005±0.002 | 0 |

### agentspec-minimal

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 3 | 1.000±0.000 | 9.000±0.816 | 0.002±0.000 | 0 |
| click_t2_option_prefix_parsing | 3 | 1.000±0.000 | 7.667±0.943 | 0.001±0.000 | 0 |
| click_t3_preserve_paragraph_wrapping | 3 | 1.000±0.000 | 23.000±1.414 | 0.006±0.001 | 0 |
| sympy__sympy-24443 | 3 | 1.000±0.000 | 19.667±4.784 | 0.006±0.001 | 0 |

### agentspec-full

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| click_t1_short_help_truncation | 3 | 1.000±0.000 | 8.667±1.700 | 0.002±0.000 | 0 |
| click_t2_option_prefix_parsing | 3 | 1.000±0.000 | 9.000±1.414 | 0.001±0.000 | 0 |
| click_t3_preserve_paragraph_wrapping | 3 | 1.000±0.000 | 22.667±4.714 | 0.006±0.001 | 0 |
| sympy__sympy-24443 | 3 | 1.000±0.000 | 20.000±4.546 | 0.005±0.002 | 0 |

## Skipped Runs

- none
