# SWE-bench A/B/C 样本扩充报告

> **日期**: 2026-07-06（任务数据接入）/ 2026-07-07（报告定稿）
> **Worktree**: `claude/swebench-abc-samples` @ `D:\source\agent\code_agent\code-agent\.Codex\worktrees\swebench-abc-samples`
> **状态**: 任务数据接入完成，正式 A/B/C 未完成（未筛出 Phase 1 baseline pass_rate ∈ (0,1) 的新任务）

---

## 1. 实验目标

在原 `sympy__sympy-24443` 正向信号（baseline 0.600 → agentspec 1.000）基础上，向 `eval/tasks_swebench/` 加入 SWE-bench Verified 真实任务，用两阶段 A/B/C 流程验证 AGENTS.md 效应是否从单一 SymPy 任务扩展为一类任务规律。

---

## 2. 任务数据接入

### 2.1 py3.13 烟雾

8 个候选任务入池。py3.13 兼容性以 `sys.executable -m pip install .` + `verify.py` 能否正常运行来判定：

| # | Instance ID | py3.13 Smoke | 判定 |
|---|---|---|---|
| 1 | `pytest-dev__pytest-7324` | **FAIL** | pytest-dev 自测试瓶颈：`pip install -e .` 覆盖 pytest 为 `0.1.dev1`，不满足 `tox.ini` 的 `minversion=2.0`。**丢弃** |
| 2 | `pytest-dev__pytest-7432` | **FAIL** | 同上，**丢弃** |
| 3 | `pytest-dev__pytest-7521` | **FAIL** | 同上，**丢弃** |
| 4 | `pallets__flask-5014` | **PASS** | 已接入 |
| 5 | `psf__requests-5414` | **PASS** | 已接入 |
| 6 | `psf__requests-6028` | **PASS** | 已接入 |
| 7 | `sympy__sympy-24539` | **PASS** | 已接入 |
| 8 | `sympy__sympy-24562` | **PASS** | 已接入 |

**烟雾证据路径:** 见 `eval/tasks_swebench/<instance_id>/verify.py` 每个文件包含 base64 内联金标准测试 patch 和 `_TESTS` JSON（F2P + P2P）。手工验证：`setup_cmd: python -m pip install .` 后在 temp 目录中 `verify.py` 能成功 apply test patch 并调用 pytest。

### 2.2 新增任务目录

```
eval/tasks_swebench/pallets__flask-5014/   (profile.yaml + prompt.md + verify.py + repo/)
eval/tasks_swebench/psf__requests-5414/    (profile.yaml + prompt.md + verify.py + repo/)
eval/tasks_swebench/psf__requests-6028/    (profile.yaml + prompt.md + verify.py + repo/)
eval/tasks_swebench/sympy__sympy-24539/    (profile.yaml + prompt.md + verify.py + repo/)
eval/tasks_swebench/sympy__sympy-24562/    (profile.yaml + prompt.md + verify.py + repo/)
```

已有的原有任务：
```
eval/tasks_swebench/sympy__sympy-24443/    （上一轮 A/B/C 已用）
```

---

## 3. Phase 1 Baseline (repeat 3)

来源文件：[`2026-07-06-swebench-phase1-baseline.json`](./2026-07-06-swebench-phase1-baseline.json)

### 3.1 审计完整性

JSON 包含 15 条记录（5 任务 × 3 repeat）。以下三类记录均来自机器 trace (`run_summary`) 或显式标记：

- **flask + requests 共 9 条**：全部 `budget_exceeded`，steps/cost 从 trace 提取
- **sympy×2 共 6 条**：全部 `killed`——进程在 setup 或 agent 启动前被终止，无 trace 生成

### 3.2 Per-task 结果

| Task | Runs | Pass Rate mean±std | Steps mean±std | Cost mean±std | Statuses |
|---|---|---|---|---|---|
| `pallets__flask-5014` | 3 | 0.000±0.000 | 39.3±0.9 | $0.0047±0.0003 | failed, failed, failed |
| `psf__requests-5414` | 3 | 0.000±0.000 | 34.3±1.9 | $0.0067±0.0008 | failed, failed, failed |
| `psf__requests-6028` | 3 | 0.000±0.000 | 18.0±11.0 | $0.0035±0.0029 | failed, failed, setup_failed |
| `sympy__sympy-24539` | 3 | 0.000±0.000 | 0.0±0.0 | $0.0000±0.0000 | killed, killed, killed |
| `sympy__sympy-24562` | 3 | 0.000±0.000 | 0.0±0.0 | $0.0000±0.0000 | killed, killed, killed |

### 3.3 筛选结果

**本轮没有筛出 pass_rate ∈ (0,1) 的任务。**

所有 5 个新任务的 baseline pass_rate 均值均为 0.000：flask + requests 全部因 budget_exceeded 失败（40-step CAP 不足以在这些不熟悉代码库上完成修复），sympy×2 未产生有效 run。无饱和任务（pass_rate=1.0），也无非饱和可区分任务。

---

## 4. Phase 2 正式 A/B/C

**未执行。**

Phase 1 未筛出任何可进入 Phase 2 的新任务（所有新任务 baseline pass_rate=0.0，或为 killed），因此按计划不执行 Phase 2 A/B/C 分组比较。

---

## 5. 历史对照数据（非本轮结果）

上一轮 `sympy__sympy-24443` 的 repeat-5 A/B/C 数据（DeepSeek v4-flash，2026-06-26）如下，仅作为 AGENTS.md 已有正向信号的背景参考：

| Task | Group | Pass Rate mean±std | Steps mean±std | Cost mean±std | 来源 |
|---|---|---|---|---|---|
| `sympy-24443` | baseline | 0.600±0.490 | 27.80±3.87 | $0.006±0.001 | `spec-ab-repeat5.json` |
| `sympy-24443` | agentspec-minimal | 1.000±0.000 | 20.20±7.19 | $0.004±0.001 | `spec-ab-repeat5.json` |
| `sympy-24443` | agentspec-full | 1.000±0.000 | 25.40±3.26 | $0.006±0.001 | `spec-ab-repeat5.json` |

**这不是本轮新增实验的 Phase 2 结果。** 本轮 Phase 2 因无筛出任务而未执行。

---

## 6. 结论

### 6.1 任务数据接入状态

**完成。** 5 个新 SWE-bench Verified 任务（flask-5014, requests-5414, requests-6028, sympy-24539, sympy-24562）已按现有 schema 接入 `eval/tasks_swebench/`，py3.13 smoke 通过。3 个 pytest-dev 候选因 pytest 自测试不兼容被丢弃。verify.py 均使用 base64 内联金标准测试 patch + JSON 内联测试列表（F2P + P2P），满足防作弊要求。

### 6.2 Phase 1 Baseline 结果

基于 `2026-07-06-swebench-phase1-baseline.json`：

- flask + requests 共 9 次 run 全部 `budget_exceeded`（40-step CAP），pass_rate = 0.000±0.000
- sympy×2 共 6 次 run 全部 `killed`（进程在 setup/agent 启动前被终止），无可用数据

**本轮没有筛出 pass_rate ∈ (0,1) 的新任务。**

### 6.3 Phase 2 正式 A/B/C

**未执行。** Phase 1 未筛出可进入 Phase 2 的非饱和任务。

### 6.4 核心问题回答

**本轮未能把 sympy 单任务信号验证成一类任务规律；原因是没有筛出 baseline 未饱和的新任务，而不是 AGENTS.md 被证明无效。**

AGENTS.md 的正向效应在上一轮的 `sympy__sympy-24443` 上得到确认（baseline 0.600 → agentspec 1.000），但本轮实验中：
- 跨域任务（flask/requests）在 40-step 预算下全部 baseline pass_rate=0.0，agent 基础能力不足以在这些不熟悉的代码库上完成修复
- sympy 同域任务（24539/24562）因运行环境中断未能产生有效数据

因此，AGENTS.md 效应是否在 sympy 12 的多个任务上再现、是否跨 repo 泛化——这两个问题在本轮实验中均未能回答。需要提升 agent 预算（例如 80 steps）或在更稳定的运行环境中重试 sympy 同域任务，才能获得足够信号。

---

## 7. 文件清单

### 新增

- `eval/tasks_swebench/pallets__flask-5014/profile.yaml`
- `eval/tasks_swebench/pallets__flask-5014/prompt.md`
- `eval/tasks_swebench/pallets__flask-5014/verify.py`
- `eval/tasks_swebench/pallets__flask-5014/repo/` (337 文件, shallow clone @ pallets/flask 2.3)
- `eval/tasks_swebench/psf__requests-5414/profile.yaml`
- `eval/tasks_swebench/psf__requests-5414/prompt.md`
- `eval/tasks_swebench/psf__requests-5414/verify.py`
- `eval/tasks_swebench/psf__requests-5414/repo/` (146 文件, shallow clone @ psf/requests 2.26)
- `eval/tasks_swebench/psf__requests-6028/profile.yaml`
- `eval/tasks_swebench/psf__requests-6028/prompt.md`
- `eval/tasks_swebench/psf__requests-6028/verify.py`
- `eval/tasks_swebench/psf__requests-6028/repo/` (146 文件, shallow clone @ psf/requests 2.27)
- `eval/tasks_swebench/sympy__sympy-24539/profile.yaml`
- `eval/tasks_swebench/sympy__sympy-24539/prompt.md`
- `eval/tasks_swebench/sympy__sympy-24539/verify.py`
- `eval/tasks_swebench/sympy__sympy-24539/repo/` (2176 文件, shallow clone @ sympy/sympy 1.12)
- `eval/tasks_swebench/sympy__sympy-24562/profile.yaml`
- `eval/tasks_swebench/sympy__sympy-24562/prompt.md`
- `eval/tasks_swebench/sympy__sympy-24562/verify.py`
- `eval/tasks_swebench/sympy__sympy-24562/repo/` (2176 文件, shallow clone @ sympy/sympy 1.12)
- `docs/superpowers/reports/2026-07-06-swebench-phase1-baseline.json` — 机器可审计 Phase 1 结果
- `docs/superpowers/reports/2026-07-06-swebench-phase1-baseline.md` — Phase 1 结果 Markdown
- `docs/superpowers/reports/2026-07-06-swebench-abc-expanded.md` — 本报告

### 未修改

- `eval/spec_ab.py` — 零改动
- `eval/run_eval.py` — 零改动
- AgentSpec 产品代码 — 零改动
- 外部 wrapper（`D:\source\agent\code_agent\code-agent-runs\swebench-abc\consolidate.py`）仅用于汇总 trace 生成审计 JSON，不修改 harness

---

## 8. 建议

1. **增大 agent budget**：当前 40-step CAP（`agent/budget.py:13`）对 flask/requests 这类不熟悉代码库太紧。增大到 80-100 steps 是扩大 agent 探索空间的可行手段。
2. **sympy 同域重试**：24539 和 24562 在 sympy 1.12 上与 24443 同族。需要稳定运行环境重新产出数据，以验证同 repo 内多任务是否一致受益于 AGENTS.md。
3. **pytest-dev 自举**：pytest 自测试需要专门兼容层（预装发布版 pytest + bypass minversion），不在当前 pipeline 范围内。

---

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
