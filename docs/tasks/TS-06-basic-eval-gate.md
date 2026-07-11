# TS-06：基础五任务 Fake/Real Eval 验收

- 状态：DONE
- 优先级：P0
- 所属里程碑：M1 安全执行与基础 Eval 闭环
- 依赖：TS-05
- 阻塞任务：CM-01、MODEL-01、MCP-01、GOV-01、MA-01
- 目标提交：独立 feat 提交

## 1. 用户故事

作为 Runtime 维护者，我希望用同一套 Python Eval 和报告契约验证 TypeScript Runtime：确定性 Fake 模式必须稳定解决 t01 到 t05；Real 模式必须能够完整运行五任务并形成可追溯基线，不论模型最终解决率是多少。

## 2. 核心判定

- Fake gate：五任务全部执行、全部被外部 `verify.py` 判定为 solved，退出码 0。
- Real baseline：五任务全部形成结果和 Artifact；全部 solved 时退出 0，存在未解决任务时退出 1，基础设施错误时退出 2。
- Finish Gate 不是最终 solve oracle。t04/t05 的 baseline 和 final 若保持同一已有失败，Finish 可以按 `pre_existing_failure` 放行；最终状态始终由 Python Eval 在 managed Workspace 中执行 `verify.py` 决定。

## 3. 架构边界

- Engine：不感知 Fake、Eval、任务 ID、脚本文件或报告。
- Service：`ScriptedModelService` 只消费标准 ModelResponse。
- Host/CLI：加载并验证 versioned model script，再注入 ScriptedModelService。
- Tool/Governance：脚本产生的 ToolCall 仍经过 ToolRegistry、Permission、Hook 和 Finish Gate，不得直接修改 Workspace。
- Python Eval：按任务选择 fixture script、调用 TS CLI、执行最终 verifier 并聚合报告。

## 4. Model Script v1

CLI 新增：

~~~text
--model-script <json>
~~~

它与 `--fake` 互斥。JSON schema：

~~~json
{
  "schemaVersion": 1,
  "responses": [
    {
      "content": null,
      "toolCalls": [
        {"id": "edit-1", "name": "edit_file", "input": {}}
      ],
      "usage": {
        "promptTokens": 0,
        "completionTokens": 0,
        "cacheReadTokens": 0,
        "cacheWriteTokens": 0
      }
    }
  ]
}
~~~

约束：

- 文件最大 1 MiB，response 数 1..100，每个 response 最多 50 个 ToolCall。
- schemaVersion 必须为 1，未知根字段和未知 response 字段拒绝。
- content 必须为 string 或 null；toolCalls 必须为数组。
- id/name 必须为非空字符串，同一 response 内 id 唯一；input 必须是 JSON object。
- usage 可省略并默认全 0；存在时四个字段必须是非负安全整数且不允许未知字段。
- Loader 不验证具体 Tool 名和 Tool input schema；这些仍由标准 ToolRegistry 在执行时验证并产生正常治理事件。

## 5. 五任务 Fake Fixtures

每个 `eval/tasks/<task>/model-script.json` 只描述标准工具调用，不新增任务专用代码路径：

- t01：编辑 `greeting.py`，实现 `Hello, <name>!`。
- t02：编辑 `count.py`，使用 `range(n + 1)`。
- t03：编辑 `first.py`，空输入返回 `None`。
- t04：编辑 `pricing.py`，按百分比计算折扣。
- t05：编辑 `normalizer.py`，trim、lower 并替换空格。

每个脚本至少分为 edit response 和 finish response，保证模型循环、Tool Result 回灌和 Finish Gate 都真实经过 Runtime。

## 6. Python Eval 选择

`--runtime typescript --fake` 的含义调整为：

1. 对每个任务查找 `model-script.json`。
2. 为该任务创建带 `model_script` 的 TypeScript Agent。
3. 缺少 script 时形成结构化基础设施错误，不回退到 finish-only fake。

直接调用 TS CLI 的 `--fake` 仍保留为 finish-only smoke，不改变原有兼容行为。

新增 `--budget-steps`，默认 40，并传入 Python 或 TypeScript Runtime。Fake/Real 比较必须使用相同步骤预算、任务快照、verifier 和权限策略。

## 7. Eval Report v1

在现有 summary 上增加稳定元数据，保持旧统计字段兼容：

- `schema_version: 1`
- `runtime: python | typescript`
- `mode: fake | real`
- `repeat`
- `budget_steps`
- `cli_timeout_seconds`
- `allow_unsafe_host_shell`
- `model`、`reasoning_effort`，不得记录 API key
- `task_ids`

每次 result 增加：

- `session_id`
- `result_path`
- `verification_path`
- `usage` 四项 token 字段
- `infrastructure_error`（可选 `{code, type, message}`）

Infrastructure exception 在 `main` 层转换为 status=`error` 的 EvalResult，继续后续任务并落盘部分报告；`run_task` 直接调用仍保持抛异常兼容。

退出码：

- 0：无 infrastructure error 且全部 solved。
- 1：无 infrastructure error，但至少一个 verifier failed。
- 2：至少一个 infrastructure error，报告仍成功落盘。

## 8. 安全边界

- Fake 和 Real 基线默认 `accept_edits`，不注册 Bash。
- model script 不是直接执行代码；所有调用继续经过工具与治理。
- `--allow-unsafe-host-shell` 只做独立显式测试，不作为 TS-06 基线条件。
- 报告不记录 API key、完整模型消息或 Error stack。
- Real 模型网络调用由 CLI Model Service 发起；验证子进程继续过滤 secret 环境变量。

## 9. 非目标

- 不把五任务逻辑写入 Engine、CLI、Tool 或 Service。
- 不让 Fake 指标代表模型能力或与 Real 成本直接比较。
- 不实现模型请求级 timeout、retry、限流分类或准确 Provider 计费。
- 不要求 Real 五任务全部 solved；只要求完整执行和形成基线。
- 不实现多 Agent、CMake 专项能力或 OS 沙箱。
- 不修复通用 setup/editable-install Workspace 生命周期。

## 10. 测试与验收

- Model Script parser 的正常、边界、未知字段、重复 ID、非法 usage 和文件上限测试。
- CLI `--fake/--model-script` 互斥及 scripted edit→finish smoke。
- Python bridge model_script argv、缺失文件和 fake 冲突测试。
- Eval TypeScript Fake 自动按任务选择 fixture，缺失 fixture 形成 error report。
- Eval report metadata、usage、Artifact 路径、错误继续执行和退出码 0/1/2 测试。
- t01 到 t05 Fake：5/5 solved，每项 trace/diff/result/verification 路径非空。
- Real：五任务均形成结果或结构化 error；无基础设施错误时形成 solve-rate 基线。
- TS/Python 全量回归、build、架构边界通过。

## 11. Definition of Done

- [x] 规格先于实现落盘。
- [x] Model Script v1 loader 和 CLI 注入完成。
- [x] 五个 Fake fixture 完成且无任务硬编码分支。
- [x] Python bridge/Eval 按任务选择脚本。
- [x] Eval Report v1 和退出码 0/1/2 完成。
- [x] Fake 五任务 5/5 solved。
- [x] Real 五任务基线报告完成。
- [x] Engine 无 Fake/Eval/任务 ID 改动。
- [x] TS/Python 全量回归和 build 通过。
- [x] 路线图更新并生成阶段实现报告。
- [x] 独立提交、fast-forward 合并、推送并清理 worktree。

## 12. 上下文交接记录（2026-07-11）

- 当前分支：`Codex/ts-basic-eval-gate`
- Worktree：`D:\source\agent\code_agent\code-agent\.Codex\worktrees\ts-basic-eval-gate`
- 基线提交：`0086e5e`
- 当前状态：未提交；主仓库 4 个用户未跟踪文档已恢复，不得纳入本任务。
- 已完成：Model Script v1 loader、CLI `--model-script`、Bridge script 透传、五个任务 fixture、按任务 Fake 选择、Eval Report v1、基础设施错误继续执行、`--budget-steps`。
- Fake 实际报告：`.tmp/ts06-fake.json`，5/5 solved，平均 2 steps，所有 trace/diff/result/verification 路径非空，未启用 Bash。
- 验证：TypeScript 124 passed；Python 213 passed，2 个既有 GBK warning；`npm run build` 通过；Engine diff 为空。
- 外部阻塞：Real 五任务需要把 fixture 源码和 prompt 发送给 DeepSeek 并产生费用；安全审批要求用户在知情后明确同意。不得绕过该审批。
- 正在进行：subagent `019f5105-3b85-7602-abc9-d116e1150a21` 对当前 diff 做只读缺陷审查。
- 未完成顺序：取得用户明确批准 -> 运行 `.tmp/ts06-real.json` Real 基线 -> 处理审查发现 -> 更新路线图/README/实现报告和本规格 DONE -> 全量复验 -> 明确文件暂存 -> commit -> 保护主仓库 4 文档 -> fast-forward 合并/推送 -> 恢复文档 -> 清理 worktree。
- 必须保留：Fake/Real 默认 `accept_edits` 且不启用 Bash；任务逻辑只能存在于 fixture JSON；Engine 不得出现 Eval/Fake/t01..t05 分支；每阶段结束必须给用户实现报告。

## 13. 完成记录（2026-07-11）

- Fake 基线：5/5 solved，平均 2 steps，费用为 0；每项 trace、diff、result 和 verification artifact 均存在。
- Real 基线：DeepSeek `deepseek-v4-flash` 5/5 solved，平均 8.8 steps，总估算费用 `$0.0024050712`，无基础设施错误。
- Real token usage：prompt 71,469、completion 5,344、cache read 66,304、cache write 0。
- 安全边界：两组基线均使用 `accept_edits`，未注册 Bash；所有 scripted ToolCall 经过 Registry、Permission、Hook 和 Finish Gate。
- 审查修复：任务发现错误可逐项落档并继续；只报告真实存在的 workspace；Python Fake 元数据不再声明 DeepSeek；model-script 仅接受常规文件、有界读取并支持 UTF-8 BOM/CRLF。
- 最终验证：TypeScript 125 passed；Python 216 passed、2 个既有 Windows GBK warning；`npm run build` 通过；Engine diff 为空。
- 实现报告：`../superpowers/reports/2026-07-11-ts-06-basic-eval-gate.md`。
