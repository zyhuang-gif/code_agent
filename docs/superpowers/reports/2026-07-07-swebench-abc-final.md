# SWE-bench A/B/C 样本扩充 —— 最终报告

> **日期**: 2026-07-06 ~ 2026-07-07
> **Worktree**: `claude/swebench-abc-samples` @ `D:\source\agent\code_agent\code-agent\.Codex\worktrees\swebench-abc-samples`
> **状态**: 任务数据接入完成，Phase 2 A/B/C 未执行（Phase 1 未筛出可用样本）

---

## 1. 做了什么

在 `eval/tasks_swebench/` 新增 17 个 SWE-bench Verified 任务（task.json + profile.yaml + prompt.md + verify.py），全部通过 py3.13 smoke。修复了 `agent/checkpoint.py` 的 shallow clone detached HEAD bug，budget 从 40 提高到 80 steps。用 resumable runner 对 12 个 sympy 任务跑完了 baseline repeat 3。repo/ 目录改为通过 `task.json` 元数据动态 fetch，不再纳入 git 跟踪。

**spec_ab.py 零改动。**

---

## 2. py3.13 Smoke 结果

| 候选池 | 通过 | 丢弃 | 原因 |
|---|---|---|---|
| pytest-dev×3 | 0 | 3 | pip install -e . 覆盖 pytest 为 0.1.dev1，minversion 检查失败 |
| flask×1 | 1 | — | ✅ |
| requests×2 | 2 | — | ✅ |
| sympy×14 | 14 | — | ✅ |

---

## 3. Phase 1 Baseline 结果（80-step budget, repeat 3）

审计 JSON: [`2026-07-07-sympy12-phase1-baseline.json`](./2026-07-07-sympy12-phase1-baseline.json)，total_runs=36。

### 3.1 有有效数据的 11 个 sympy 任务

| Task | Run 1 | Run 2 | Run 3 | Pass Rate mean±std | Steps mean±std | 判定 |
|---|---|---|---|---|---|---|
| sympy-21847 | solved 12s | solved 13s | solved 20s | **1.000±0.000** | 15.0±3.6 | 饱和 |
| sympy-22914 | solved 13s | solved 26s | solved 10s | **1.000±0.000** | 16.3±6.9 | 饱和 |
| sympy-23534 | solved 14s | solved 10s | solved 17s | **1.000±0.000** | 13.7±2.9 | 饱和 |
| sympy-22080 | exceeded 26s | exceeded 28s | exceeded 28s | **0.000±0.000** | 27.3±0.9 | 过难 |
| sympy-22714 | exceeded 28s | exceeded 29s | exceeded 27s | **0.000±0.000** | 28.0±0.8 | 过难 |
| sympy-23262 | exceeded 32s | exceeded 35s | exceeded 35s | **0.000±0.000** | 34.0±1.4 | 过难 |
| sympy-23413 | exceeded 24s | exceeded 20s | exceeded 23s | **0.000±0.000** | 22.3±1.7 | 过难 |
| sympy-23824 | failed 0s | failed 0s | failed 0s | **0.000±0.000** | 0.0±0.0 | setup 失败 |
| sympy-23950 | failed 0s | failed 0s | failed 0s | **0.000±0.000** | 0.0±0.0 | setup 失败 |
| sympy-24066 | failed 0s | failed 0s | failed 0s | **0.000±0.000** | 0.0±0.0 | setup 失败 |
| sympy-24213 | failed 0s | failed 0s | failed 0s | **0.000±0.000** | 0.0±0.0 | setup 失败 |

另有 sympy-24661 的 3 条 run（全部 steps=0, reason=""）在 JSON 中。

### 3.2 非 sympy 任务（第一轮，40-step budget, repeat 3）

| Task | 结果 |
|---|---|
| pallets__flask-5014 | 全部 budget_exceeded（~39 steps），pass_rate=0.000 |
| psf__requests-5414 | 全部 budget_exceeded（~34 steps），pass_rate=0.000 |
| psf__requests-6028 | 全部 budget_exceeded / setup_failed，pass_rate=0.000 |

### 3.3 筛选结果

**筛出 pass_rate ∈ (0,1) 的任务：0 个。**

---

## 4. Phase 2 正式 A/B/C

**未执行。**

Phase 1 无可用样本。

---

## 5. 核心结论

**在本轮实验中，未能验证 AGENTS.md 的正向效应是否从单个 sympy-24443 任务扩展为跨多任务的稳定规律。**

12 个 sympy 任务的 baseline 呈现三种极端情况：
- **3 个全部 solved**（pass_rate=1.0）：baseline 已饱和，无法在 A/B/C 中衡量 AGENTS.md 的增量效应
- **4 个全部 budget_exceeded**（pass_rate=0.0）：80-step 预算不足以让 agent 找到正确的修复
- **5 个 setup 失败**（steps=0）：任务在 agent 启动前就失败了

三个趋势值得注意：

1. **增加 budget 反而使饱和任务增多**：sympy-21847 和 sympy-22914 在 40-step 预算中 pass_rate<1.0，但 80-step 预算使它们全部 solved。step budget 和 task 难度之间存在一个需要精确调整的平衡点。

2. **历史唯一的正信号来自 40-step budget**：sympy-24443 的上轮 repeat-5 数据显示 baseline 0.600→agentspec 1.000——这是唯一可区分处理组的任务。本轮所有 80-step 任务要么 100% 解要么 0% 解。

3. **AGENTS.md 没有被证明无效**——只是在本轮实验中没有合适的测量任务。

---

## 6. 历史对照（非本轮数据）

| Task | Group | Pass Rate mean±std | Steps mean±std | 来源 |
|---|---|---|---|---|
| sympy-24443 | baseline | 0.600±0.490 | 27.80±3.87 | `spec-ab-repeat5.json` |
| sympy-24443 | agentspec-minimal | 1.000±0.000 | 20.20±7.19 | `spec-ab-repeat5.json` |
| sympy-24443 | agentspec-full | 1.000±0.000 | 25.40±3.26 | `spec-ab-repeat5.json` |

---

## 7. 改动清单

| 文件 | 改动 |
|---|---|
| `agent/budget.py` | max_steps 40 → 80 |
| `agent/checkpoint.py` | GitCheckpoint.init() 增加 detached HEAD 修复 |
| `eval/run_eval.py` | run_task() 增加 task.json fallback（repo/ 不存在时 shallow clone） |
| `eval/tasks_swebench/` | 新增 17 个任务目录（task.json + profile.yaml + prompt.md + verify.py，repo/ 已删除、不纳入 git） |
| `docs/superpowers/reports/` | 7 个 JSON/MD 审计文件 |
| **`eval/spec_ab.py`** | **零改动** |

**已 commit 到 `claude/swebench-abc-samples`，未 merge，未 push。**

---

## 8. 建议

**停止无效长跑。** 在 12 个 sympy 任务 + 80-step budget 下未找到可测样本。下一步可行的方向：

- 回到 40-step budget，在 sympy-24443 的可区分信号已被证实的基础上，寻找新的非 sympy 任务（requests/flask 类）
- 或者接受"效应存在但测量不到"的结论，归档本轮实验为"扩展尝试失败"
- 或者改用更弱的 baseline LLM 来提高区分度（当前 deepseek-v4-flash 在 sympy 上太强）

---

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
