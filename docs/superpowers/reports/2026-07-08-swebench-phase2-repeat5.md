# AgentSpec A/B Evaluation Report

LLM evals are noisy: never draw conclusions from a single solution_rate. Use mean±std and inspect traces.

## Group Summary

| Group | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped | Trace Sample |
|---|---:|---:|---:|---:|---|
| baseline | 0.333±0.471 | 27.133±8.913 | 0.004±0.002 | 0 | workspace\spec-ab\baseline\sympy__sympy-22914\run-1.trace.jsonl |
| agentspec-minimal | 0.333±0.471 | 28.600±7.181 | 0.005±0.001 | 0 | workspace\spec-ab\agentspec-minimal\sympy__sympy-22914\run-1.trace.jsonl |
| agentspec-full | 0.400±0.490 | 29.133±7.580 | 0.005±0.001 | 0 | workspace\spec-ab\agentspec-full\sympy__sympy-22914\run-1.trace.jsonl |

## Per Task

### baseline

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| sympy__sympy-22914 | 5 | 1.000±0.000 | 15.600±5.535 | 0.002±0.001 | 0 |
| sympy__sympy-23262 | 5 | 0.000±0.000 | 32.800±2.482 | 0.006±0.001 | 0 |
| sympy__sympy-23950 | 5 | 0.000±0.000 | 33.000±1.414 | 0.005±0.001 | 0 |

### agentspec-minimal

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| sympy__sympy-22914 | 5 | 1.000±0.000 | 23.400±9.728 | 0.004±0.002 | 0 |
| sympy__sympy-23262 | 5 | 0.000±0.000 | 30.000±2.828 | 0.005±0.000 | 0 |
| sympy__sympy-23950 | 5 | 0.000±0.000 | 32.400±2.939 | 0.005±0.000 | 0 |

### agentspec-full

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Skipped |
|---|---:|---:|---:|---:|---:|
| sympy__sympy-22914 | 5 | 1.000±0.000 | 22.400±9.178 | 0.003±0.002 | 0 |
| sympy__sympy-23262 | 5 | 0.000±0.000 | 31.600±2.871 | 0.005±0.000 | 0 |
| sympy__sympy-23950 | 5 | 0.200±0.400 | 33.400±3.200 | 0.005±0.001 | 0 |

## Skipped Runs

- none

---

## 分析与结论

**数据口径**：本报告基于 `2026-07-07-sympy12-phase1-baseline.json`（唯一 Phase 1 source of truth）中 pass_rate ∈ (0,1) 的 3 个任务，各跑 3 groups × 5 repeat = 45 runs。agent: DeepSeek v4-flash, budget: 80 steps。所有 run 的 `verify_output` 均来自 `verify.py`（pytest returncode），不含 runner 报告污染。

**主指标选择**：本轮 pass_rate 比 steps 更有区分度。22914 和 23262 的 steps 存在组间差异，但未转化为解决率差异（22914 全解、23262 全败），因此 steps 的组间差异无法解释为 AGENTS.md 效应。

### 按任务拆解

#### sympy__sympy-22914（printing/pycode — Min/Max 导入缺失）

| Group | Pass Rate | Steps | 结论 |
|---|---|---|---|
| baseline | 1.000±0.000 | 15.6±5.5 | 已饱和 |
| agentspec-minimal | 1.000±0.000 | 23.4±9.7 | 无增益 |
| agentspec-full | 1.000±0.000 | 22.4±9.2 | 无增益 |

**结论：baseline 已饱和（5/5），无区分度；AGENTS.md 没有可测增益。**minimal/full 的 steps 反高于 baseline（+50%），说明 AgentSpec 注入未缩短修复路径，反而增加额外上下文消耗。

#### sympy__sympy-23262（utilities/lambdify — 空参数列表 crash）

| Group | Pass Rate | Steps | 结论 |
|---|---|---|---|
| baseline | 0.000±0.000 | 32.8±2.5 | 地板效应 |
| agentspec-minimal | 0.000±0.000 | 30.0±2.8 | 无增益 |
| agentspec-full | 0.000±0.000 | 31.6±2.9 | 无增益 |

**结论：三组全失败（0/5），过难/地板效应；AGENTS.md 没有可测增益。** 该任务在 budget=80 下依然全部耗尽预算未解决，说明问题难度已超出当前 agent 能力上限。

#### sympy__sympy-23950（sets/contains — as_set NotImplementedError）

| Group | Pass Rate | Steps | 结论 |
|---|---|---|---|
| baseline | 0.000±0.000 | 33.0±1.4 | 接近地板 |
| agentspec-minimal | 0.000±0.000 | 32.4±2.9 | 无增益 |
| agentspec-full | 0.200±0.400 | 33.4±3.2 | 弱信号 |

**结论：只有 agentspec-full 出现 1/5 solve，属于弱信号，不能称为稳定复现。** 唯一的 solve 出现在 run-5（最后一个 run），无法排除随机波动。

### 回答核心问题

**1. AGENTS.md 正向效应在几个真实任务上复现？**

仅 1/3 任务（23950）出现极弱信号（1/5 solve，仅 agentspec-full），未稳定复现。另外 2 个任务（22914 天花板、23262 地板）均无区分度。

**2. minimal vs full 谁更稳定、更值？**

full 略好于 minimal：只有 full 在 23950 解决 1 次，minimal 为 0。但该差异不达统计显著（1/5 vs 0/5，Fisher exact p ≈ 1.0），不能得出"full 稳定更值"的结论。minimal 在 steps 和 cost 上与 full 接近，也无明显成本优势。

**3. 效应是否普遍成立？**

**否。效应高度任务依赖，未普遍成立。** 在 3 个 selected SWE-bench sympy 任务中，仅 full 组在 1 个任务上出现 1 次 solve，无法支持普遍性主张。更大样本和更多任务类型（非 sympy 领域）的实验才能判断 AGENTS.md 的适用范围。

### Budget 漂移说明（Phase 1 baseline b=40 → Phase 2 baseline b=80）

| 任务 | P1 baseline (b=40, n=3) | P2 baseline (b=80, n=5) | 漂移 |
|---|---|---|---|
| sympy__sympy-22914 | 0.667±0.471 | 1.000±0.000 | ↑ +0.333 |
| sympy__sympy-23262 | 0.667±0.471 | 0.000±0.000 | ↓ −0.667 |
| sympy__sympy-23950 | 0.333±0.471 | 0.000±0.000 | ↓ −0.333 |

**budget 变化造成的 pass_rate 漂移远大于 AGENTS.md 效应，且方向不一致。** 三个任务中有两个在 budget 增大后反而变差，一个变好。这表明 DeepSeek v4-flash 在这些 sympy 任务上对 budget 高度敏感且不单调——更多步数不完全等于更高解决率。如需做 A/B 对比实验，必须固定 budget 并避免跨 budget 比较。

### 方法学注意事项

- **LLM evals 是噪声数据**：5 repeat 的 pass_rate 标准差可达 ±0.4–0.5，单个任务上的组间差异不应被解释为效应。
- **status/pass_rate 严格来自 verify.py returncode**（pytest 全量测试通过=0），不来自 trace `run_summary.result`。
- **`verify_output` 字段不含 runner 报告污染**：全部 45 个 run 的 verify_output 均为 pytest stdout/stderr。
- **Phase 1 source of truth**：`2026-07-07-sympy12-phase1-baseline.json`（38 runs, 13 tasks），supersedes `2026-07-07-sympy-resumable-phase1.json` 和 `2026-07-06-swebench-phase1-baseline.json`。
- **旧 Phase 2 数据（`2026-07-08-swebench-phase2-abc.json`，69 runs，含重复/缺跑/incomplete）已废弃**，不应作为结论引用。
