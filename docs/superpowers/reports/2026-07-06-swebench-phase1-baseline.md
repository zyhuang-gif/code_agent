# Phase 1 Baseline — SWE-bench New Tasks

LLM evals are noisy: never draw conclusions from a single solution_rate. Use mean±std and inspect traces.

Date: 2026-07-06 | Group: `baseline` | Repeat: 3

## Group Summary

| Metric | Value |
|---|---|
| Total runs | 15 |
| Overall pass_rate mean±std | 0.000±0.000 |

## Per Task

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Statuses |
|---|---:|---:|---:|---:|---|
| pallets__flask-5014 | 3 | 0.000±0.000 | 39.3±0.9 | 0.0047±0.0003 | failed, failed, failed |
| psf__requests-5414 | 3 | 0.000±0.000 | 34.3±1.9 | 0.0067±0.0008 | failed, failed, failed |
| psf__requests-6028 | 3 | 0.000±0.000 | 18.0±9.0 | 0.0052±0.0023 | failed, failed, failed |
| sympy__sympy-24539 | 3 | 0.000±0.000 | 0.0±0.0 | 0.0000±0.0000 | killed, killed, killed |
| sympy__sympy-24562 | 3 | 0.000±0.000 | 0.0±0.0 | 0.0000±0.0000 | killed, killed, killed |

## Per-Run Detail

### pallets__flask-5014
- run-1: **failed** | steps=40 | cost=0.00492 | elapsed=0s | reason=budget_exceeded
- run-2: **failed** | steps=38 | cost=0.00491 | elapsed=0s | reason=budget_exceeded
- run-3: **failed** | steps=40 | cost=0.00417 | elapsed=0s | reason=budget_exceeded

### psf__requests-5414
- run-1: **failed** | steps=37 | cost=0.00603 | elapsed=0s | reason=budget_exceeded
- run-2: **failed** | steps=33 | cost=0.00792 | elapsed=0s | reason=budget_exceeded
- run-3: **failed** | steps=33 | cost=0.00630 | elapsed=0s | reason=budget_exceeded

### psf__requests-6028
- run-1: **failed** | steps=27 | cost=0.00751 | elapsed=0s | reason=budget_exceeded
- run-2: **failed** | steps=9 | cost=0.00286 | elapsed=0s | reason=budget_exceeded
- run-3: **failed** | steps=0 | cost=0.00000 | elapsed=0s | reason=setup_failed

### sympy__sympy-24539
- run-1: **killed** | steps=0 | cost=0.00000 | elapsed=0s | reason=process killed during setup; no trace produced
- run-2: **killed** | steps=0 | cost=0.00000 | elapsed=0s | reason=killed before agent started
- run-3: **killed** | steps=0 | cost=0.00000 | elapsed=0s | reason=killed before agent started

### sympy__sympy-24562
- run-1: **killed** | steps=0 | cost=0.00000 | elapsed=0s | reason=killed before agent started
- run-2: **killed** | steps=0 | cost=0.00000 | elapsed=0s | reason=killed before agent started
- run-3: **killed** | steps=0 | cost=0.00000 | elapsed=0s | reason=killed before agent started
