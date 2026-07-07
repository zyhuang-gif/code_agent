# Phase 1 Baseline — SymPy Tasks（80-step budget, repeat 3）

## 已完成任务的机器结果

| Task ID | Run 1 | Run 2 | Run 3 | Pass Rate mean±std | Steps mean±std | 判定 |
|---|---|---|---|---|---|---|
| sympy-21847 | finished 16s | finished 16s | finished 19s | **1.000±0.000** | 17.0±1.4 | 饱和 |
| sympy-22080 | budget_exceeded 30s | budget_exceeded 28s | budget_exceeded 32s | **0.000±0.000** | 30.0±1.6 | 过难 |
| sympy-23262 | budget_exceeded 32s | budget_exceeded 29s | budget_exceeded 33s | **0.000±0.000** | 31.3±1.7 | 过难 |
| sympy-23413 | running | — | — | — | — | 未完成 |

其余 8 个 sympy 任务（22714/22914/23534/23824/23950/24066/24213/24661）尚未开始。

## 筛出任务

**0 个。不执行 Phase 2 A/B/C。**

## 结论

本轮实验（扩大 sympy 候选到 12 个 + 提高 budget 到 80 steps）未产生 pass_rate∈(0,1) 的可区分任务：

- 21847 baseline 100% solved，无法在 A/B/C 中衡量 AGENTS.md 处理组效应
- 已完成其他三个任务全部 budget_exceeded
- 未完成任务无数据，不计入统计

**AGENTS.md 正向效应在 sympy-24443 一个任务上有已知信号（历史 repeat-5），但本轮未能扩展为多个独立任务的规律验证。**

审计 JSON: [`2026-07-07-sympy12-phase1-baseline.json`](./2026-07-07-sympy12-phase1-baseline.json)

## 改动清单

- `agent/budget.py`: max_steps 40→80
- `agent/checkpoint.py`: GitCheckpoint.init() 增加 detached HEAD 修复
- `eval/tasks_swebench/`: 新增 17 个任务目录
- `docs/superpowers/reports/2026-07-07-sympy12-phase1-baseline.{json,md}`

**spec_ab.py 未改。不 merge，不 push。**
