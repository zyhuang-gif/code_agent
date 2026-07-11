# CM-02：CMake Skill 配对 A/B Eval

- 状态：READY
- 优先级：P0
- 所属里程碑：M2 CMake Skill 与领域能力
- 依赖：CM-01
- 后续决策：CM-03、CM-04
- 执行分工：CC 实现 Eval 基础设施；DS 在独立授权后执行 Real pilot/全量并分析

## 1. 目标

量化 `cmake-build-fix` Skill 对真实 CMake 修复任务的影响，并回答四个问题：

1. 模型看到 Skill 时，实际选择率是多少。
2. 选择 Skill 是否提高 Solve Rate。
3. Skill 对 steps、tokens、latency 和 cost 的影响是什么。
4. 失败主要来自“没有选择 Skill”、Skill 内容无效，还是通用工具能力不足。

CM-02 不以单次成功或失败下结论，使用相同任务、相同模型配置和交替顺序的配对重复运行。

## 2. 架构边界

- Engine：不得修改，不增加 CMake、A/B、task ID 或 Skill 路由分支。
- Extension：继续只通过通用 `invoke_skill` 暴露 `cmake-build-fix`。
- Eval：负责 variant 编排、重复运行、指标聚合和报告。
- Bridge：只允许增加通用 `extensions_root` 配置，不感知 CMake。
- Governance：所有 treatment Tool 调用继续经过 Permission、Hook、并发调度和 Trace。
- Verification：继续由任务 `verify.py` 和现有 Finish Gate 提供事实，不由模型自报 solved。

## 3. 实验变体

### A：control

- `--extensions` 指向本次 run root 下显式创建的空目录。
- Tool catalog 中不存在 `invoke_skill`。
- 其他模型、prompt、profile、预算、权限和 Verification 配置与 treatment 相同。

### B：treatment

- `--extensions` 指向仓库的 `extensions` 目录。
- Tool catalog 中包含通用 `invoke_skill` 和 `cmake-build-fix` 描述。
- 不预注入 Skill instructions，不使用 `profile.language`、文件名或关键词宿主路由。

每个 `(task, repeat)` 是一个 pair。执行顺序按 repeat 交替为 `A -> B`、`B -> A`，降低时间漂移和服务负载变化造成的偏差。

## 4. 执行拓扑

~~~text
CM-02 spec
    |
    v
CC: generic extensions_root bridge + unit tests
    |
    v
CC: paired A/B orchestrator + fake contract smoke
    |
    v
CC: full local regression + review + commit
    |
    v
DS: r08 repeat-3 Real pilot (requires fresh external-data/cost approval)
    |
    +-- selected < 2/3 --> stop, analyze catalog/description/trace; no full suite
    |
    v
DS: 10 tasks x 2 variants x repeat-3 Real suite (requires separate budget approval)
    |
    v
CC: independent artifact audit and CM-03/CM-04 go/no-go report
~~~

代码实现存在依赖拓扑，不建议并行修改重叠文件。可以并行的是：

- CC 实现代码时，DS 只读审查本规格、指标和统计口径。
- Fake 回归完成后，DS 可准备 Real 执行环境与预算清单，但不得提前发送源码/prompt。
- Real artifacts 生成后，DS 做指标分析，CC 独立校验 Trace 和报告一致性。

## 5. CC 实现步骤

1. 从最新 `master` 创建独立 worktree `Codex/cmake-skill-ab-eval`。
2. 为 `eval.ts_bridge.typescript_agent_factory` 增加可选、通用的 `extensions_root: Path | None`；默认行为保持 `<cli_root>/extensions`。
3. 补充 Bridge 单元测试，证明默认值、显式空目录、显式 treatment 目录都进入固定 argv，且不启用 host shell。
4. 新增 `eval/cmake_skill_ab.py`，复用现有 discovery、workspace isolation、`run_task`、TypeScript Bridge 和 verifier，不复制任务执行逻辑。
5. 支持 `--phase pilot|full`、`--repeat`、`--budget-steps`、`--output-dir`、`--fake` 和显式 Real 外发确认参数。
6. pilot 固定选择 `r08_local_library_source_omitted`；full 固定发现 `eval/tasks_cmake_real` 的 10 个任务，并在运行前记录有序 task ID 清单。
7. 每个 pair 使用全新 workspace/session；control 和 treatment 不共享可写目录、模型历史或生成产物。
8. 生成 schema v1 JSON 与 Markdown 报告；报告只保存白名单统计、task ID、session ID 和 artifact 相对引用，不复制源码、prompt、Tool Result content 或 secrets。
9. 新增 Fake contract smoke，验证配对数量、交替顺序、control 无 selection、treatment 有一条合法 selected 事件、零 Bash 和报告聚合。
10. 运行全量 TypeScript/Python 回归、build、架构边界测试和 `git diff --check`，提交前确认 `src/engine` diff 为空。

## 6. 建议输出模型

`cm02-summary.json` 至少包含：

~~~json
{
  "schema_version": 1,
  "phase": "pilot",
  "runtime": "typescript",
  "model": "...",
  "repeat": 3,
  "variants": ["control", "treatment"],
  "task_ids": ["r08_local_library_source_omitted"],
  "runs": [],
  "aggregate": {}
}
~~~

每个 run 至少记录：

- `task_id`、`repeat_index`、`variant`、`order_index`、`session_id`
- `solved`、`reason`、`steps`、`latency_ms`、`cost_usd`
- prompt/completion/cache token usage
- `invoke_skill_count`、`skill_selected_count`、`skill_not_found_count`
- `bash_call_count`、`infrastructure_error`
- `trace_path`、`result_path`、`verification_path`、`final_diff_path`

aggregate 至少记录：

- control/treatment Solve Rate 和配对 solve delta
- treatment Skill selection rate
- selected 与 not-selected 子组 Solve Rate
- steps、latency、tokens、cost 的 median、p25、p75
- infrastructure error count、Bash count、invalid selection audit count
- 每个 task 的 paired outcome：`both_solved`、`control_only`、`treatment_only`、`neither`

## 7. Real 门禁

### Pilot 门禁

只有同时满足以下条件，才允许申请全量费用批准：

- r08 treatment repeat-3 中至少 2 次出现真实 `skill_selection(selected)`。
- control 的 `invoke_skill_count` 与 `skill_selection` 都为 0。
- 所有 selected 事件均为 `selectionSource=model_tool_call`，且来源为 `cmake/skills/build-fix/SKILL.md`。
- Bash 调用总数为 0。
- 无 infrastructure error，源 fixture 不变。

未达到门禁时立即停止。后续只能修改通用 Tool catalog 描述或 Skill 内容，并以新任务/新提交重新验收；不得在 Engine 或 Host 增加 CMake 路由来制造选择率。

### Full 门禁

全量规模为 10 tasks x 2 variants x repeat-3，共 60 次 Real model runs。执行前必须再次获得明确的数据外发和费用批准。

建议通过标准：

- treatment Skill selection rate >= 80%。
- selection audit 有效率 100%，Bash 调用 0，Engine diff 为空。
- treatment Solve Rate 不低于 control；若提高，报告绝对差值和配对计数，不夸大统计显著性。
- 若 Solve Rate 持平，treatment median steps 或 median cost 至少一项下降 10%，否则判定 Skill 暂无可量化收益。
- 任何报告数字都能从 run artifacts 重新计算。

## 8. CM-03/CM-04 决策规则

- 只有 treatment 已高频选择 Skill，但 traces 显示重复读取/grep CMake 结构占主要步骤时，CM-03 `cmake_scan` 才进入 READY。
- 只有 Verification 阶段反复需要 configure/build/ctest 结构化结果，且现有 Gate 证据不足时，CM-04 `cmake_verify` 才进入 READY。
- 若主要问题是模型不选择 Skill，优先改进通用 Tool catalog/Skill 描述，不实现领域工具。
- 若选择率高但 Solve Rate 无收益，先修订 Skill workflow，再考虑新增工具。

## 9. 安全与费用

- `accept_edits`；不得启用 `--allow-host-shell` 或 `--allow-unsafe-host-shell`。
- Real 模式必须在命令行显式确认外部数据与费用；缺失时 fail closed。
- API key 只从环境读取，不写入报告、Trace、命令参数或 commit。
- 本任务文档不等于对未来 60 次调用的费用批准；pilot 与 full 分别确认。
- 当前 Agent 不执行外部 DeepSeek 调用。Real 阶段由用户指定、具备权限的 CC/DS 执行环境完成。

## 10. Definition of Done

- [ ] Bridge 支持通用 `extensions_root`，默认行为兼容。
- [ ] A/B orchestrator、schema v1 JSON 和 Markdown renderer 完成。
- [ ] Fake paired smoke 与错误路径测试通过。
- [ ] Engine diff 为空，host shell 未启用。
- [ ] Pilot 获得单独批准并形成可审计结果。
- [ ] Pilot 通过门禁后，全量运行获得单独预算批准并完成；或明确记录 stop decision。
- [ ] 报告可从 artifacts 重算，路线图据结果更新 CM-03/CM-04。
- [ ] 全量回归、build、独立审查、提交、fast-forward 合并和推送完成。

## 11. CC 实现 Prompt

~~~text
你负责在 code-agent 仓库实现 CM-02 的本地 Eval 基础设施。先阅读项目 AGENTS.md、
docs/tasks/CM-02-cmake-skill-ab-eval.md、CM-01 规格和 TS Runtime 架构文档。

严格使用独立 worktree，从最新 master 创建 Codex/cmake-skill-ab-eval。不要修改 Engine，
不要增加 CMake/关键词/Profile 宿主路由。实现范围仅限通用 TypeScript Eval Bridge 参数、
配对 A/B orchestrator、报告 schema/renderer 和测试。

control 使用显式空 Extension root；treatment 使用仓库 extensions。默认 accept_edits，
禁止 host shell。Real 模式必须显式确认外部数据和费用；本轮只实现并运行 Fake/local tests，
除非用户另行明确批准，不得调用 DeepSeek。

按规格中的步骤、schema、pilot/full 门禁实现。优先复用现有 discovery、run_task、Bridge、
workspace isolation、verifier 和 artifact contracts，不复制执行逻辑。测试必须证明变体隔离、
交替顺序、selection 审计、零 Bash、错误传播和报告可重算。

完成后运行 npm run check:ts、隔离 TMP/TEMP 的 uv run pytest -q、npm run build、
git diff --check，并确认 git diff master -- src/engine 为空。给出阶段实现报告、改动文件、
测试结果、残余风险和 Real pilot 的精确命令，但不要自行执行 Real 调用。
~~~

## 12. DS Pilot/验收 Prompt

~~~text
你负责 CM-02 的 Real pilot 执行与只读验收，不负责改 Engine。开始前核对当前 commit、
CM-02 规格、用户对 r08 源码/prompt 外发及少量费用的明确批准，并确认本次只运行 pilot：
r08_local_library_source_omitted，control/treatment 配对，repeat=3。

使用 accept_edits，禁止 host shell。control 必须使用空 Extension root，treatment 必须使用
仓库 extensions；每次运行使用独立 workspace/session，顺序按 AB/BA 交替。不得修改源 fixture。

执行后逐个校验 result、verification、trace 和 final.diff。重点报告：solved、steps、tokens、
cost、latency、invoke_skill_count、skill_selection(selected/not_found)、Bash count、
infrastructure errors。验证 selected 事件的 selectionSource、extensionName 和
definitionSource，不能只相信汇总 JSON。

若 treatment 3 次中少于 2 次 selected，立即停止，不运行 10 任务全量，并给出基于 Trace 的
原因分析。若 pilot 通过，只输出全量 60 次运行的费用估算与申请，不得把 pilot 授权扩展为
full 授权。最终给出可复算的验收报告，不得把 solved 但未选择 Skill 记为选择通过。
~~~
