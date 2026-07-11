# TS-05：Python Eval 调用 TypeScript CLI

- 状态：DONE
- 优先级：P0
- 所属里程碑：M1 安全执行与基础 Eval 闭环
- 依赖：TS-01、TS-02、TS-03、TS-04
- 阻塞任务：TS-06
- 目标提交：独立 feat 提交

## 1. 用户故事

作为 Eval 使用者，我希望保留现有 Python 任务发现、准备、验证和汇总能力，同时把 Agent 执行切换为 TypeScript CLI，并在同一份 EvalResult 中读取 steps、cost、reason、trace、diff 和最终 Workspace。

## 2. 当前问题

Python Eval 的 AgentCallable 直接修改传入 Workspace，并假定 Trace 和 Diff 位于 Python Runtime 的旧路径。TypeScript managed CLI 会再创建隔离 Workspace，Artifact 位于独立 Run Directory，stdout 还混合了 Agent 事件和最终结果。两边目前没有稳定桥接契约。

TS-05 需要解决：

1. Python Eval 可以显式选择 Python 或 TypeScript Runtime，默认行为保持 Python 兼容。
2. Python Eval 能以参数数组启动 TypeScript CLI，不使用 shell 拼接。
3. TypeScript CLI 提供只输出一个 ManagedRunResult 的机器接口。
4. Eval 在 TypeScript 最终 Workspace 中执行 verify.py，而不是验证调用前的中间副本。
5. Eval 从 v1 Result/Artifact 读取 steps、usage、reason、trace 和 diff，并形成现有 EvalResult。
6. CLI 异常、超时、错误 schema、越界路径和缺失 Artifact 必须显式失败。

## 3. 边界与所有权

### 3.1 Python Eval

Python Eval 保留：

- 任务发现与 Profile 加载。
- 从 fixture 复制或从 task.json 获取任务仓库。
- setup_cmd 执行和网络策略传递。
- verify.py 执行、solved/failed 判定、重复运行与汇总。
- TypeScript 子进程生命周期和桥接错误分类。

### 3.2 TypeScript CLI

TypeScript CLI 保留：

- managed Workspace 创建与 immutable checkpoint。
- Runtime、Tool、Service 和 Governance 组合。
- Verification/Finish Gate。
- trace.jsonl、final.diff、verification.json 和 result.json 持久化。

Engine 不感知 Eval、Profile 路径或 Python。

### 3.3 双层 Workspace

Eval 首先创建任务级中间副本并执行 setup_cmd，随后 TS CLI 以该目录为 sourceRepository 创建 managed Workspace。verify.py 必须在 ManagedRunResult.workspace 中运行。

任务 fixture 和 Eval 中间副本不是最终结果来源。EvalResult.workspace_path、trace_path 和 diff_path 均指向 TypeScript managed run。

setup_cmd 产生的全局依赖可直接复用；被 Workspace 核心忽略的本地依赖目录不会复制。需要依赖本地 node_modules、.venv 或 editable-install 路径的任务属于后续 Setup Workspace 生命周期扩展，TS-05 不伪装已支持。

## 4. TypeScript 机器输出

CLI 新增：

~~~text
--result-json
~~~

约束：

- 与 --json 互斥。
- 不向 stdout 写 Agent 事件或人类文本。
- managed run 成功 finalize 后只写一行 ManagedRunResult v1 JSON。
- stderr 保留诊断。
- preisolated 模式拒绝该参数，因为该模式没有 managed Artifact 契约。
- Runtime 非 completed 时 CLI 可返回 1，但只要 ManagedRunResult 完整，桥接仍消费结果；返回 2 或没有结果视为基础设施错误。

## 5. Python Bridge 接口

新增 `eval/ts_bridge.py`：

~~~python
def typescript_agent_factory(
    *,
    budget_steps: int | None = None,
    fake: bool = False,
    allow_unsafe_host_shell: bool = False,
    cli_root: Path | None = None,
    run_root_parent: Path | None = None,
    timeout_seconds: int = 3600,
    command_runner: TsCommandRunner = default_ts_command_runner,
) -> AgentCallable: ...
~~~

返回的 AgentCallable 在独立短路径的临时根下创建 managed run root，序列化 ProjectProfile，并调用：

~~~text
node <repo>/node_modules/tsx/dist/cli.mjs <repo>/src/cli.ts
  --task-file <generated-prompt.txt>
  --repo <eval-workspace>
  --run-root <short-disjoint-run-root>
  --profile <generated-profile.json>
  --extensions <repo>/extensions
  --permission-mode accept_edits
  --max-steps <budget>
  --result-json
~~~

fake=True 时追加 --fake。只有调用方显式设置 allow_unsafe_host_shell=True 时，Bridge 才把权限模式改为 bypass 并追加 --allow-host-shell。

Bridge 必须：

1. 使用 argv 和 shell=False。
2. 通过临时 UTF-8 文件传递 prompt，避免平台 argv 长度限制。
3. UTF-8 解码并以 replacement 处理平台脏字节。
4. 限制整体超时，并在超时时终止独立进程组/进程树。
5. 只接受 type=run_result、mode=managed、schemaVersion=1。
6. 校验 sourceRepository 等于输入 Workspace。
7. 强制 runDirectory=<runRoot>/<sessionId>、workspace=<runDirectory>/repository 和固定 artifacts 布局。
8. 读取 result.json 并确认 sessionId/schema 与 stdout 一致。
9. 要求 trace.jsonl、final.diff 和 verification.json 存在。
10. 返回现有 Agent metadata，并把最终路径交给 run_task。

## 6. Cost 兼容

ManagedRunResult v1 提供 usage，不提供模型价格。Bridge 使用当前 Python DeepSeek Runtime 的兼容费率估算 cost_usd：

- cache read input：0.0028 USD / 1M tokens
- non-cached input：0.14 USD / 1M tokens
- output：0.28 USD / 1M tokens

non-cached input 为 max(promptTokens - cacheReadTokens, 0)。该值是 Eval 兼容指标，不是通用 Model Billing；模型路由与准确成本归 MODEL-02。

## 7. CLI 与 Eval 参数

`eval/run_eval.py` 新增：

~~~text
--runtime python|typescript   # 默认 python
--ts-cli-timeout <seconds>   # 默认 3600
--allow-unsafe-host-shell    # TS 专用，显式开启 bypass + host shell
~~~

兼容规则：

- python + --fake 继续使用现有 fake_agent。
- python 默认继续使用 real_agent_factory/multi_agent_factory。
- typescript + --fake 启动真实 TS CLI 的 ScriptedModelService。
- typescript real 接受 CODE_AGENT_API_KEY 或 DEEPSEEK_API_KEY。
- typescript 与 --multi 互斥，直到 MA 系列任务完成。
- 测试注入的 agent_factory 保持现有无参工厂契约。
- TypeScript Eval 默认使用 accept_edits 且不注册 Bash；只有显式 unsafe opt-in 才使用 bypass 和 host shell。当前 Bash 没有 OS 沙箱，只能用于受控 Eval Workspace。收紧该边界属于 GOV-05。

## 8. run_task metadata

run_task 继续兼容旧 AgentCallable。Bridge 可返回以下可选字段：

~~~python
{
    "steps": int,
    "cost_usd": float,
    "reason": str,
    "workspace_path": str,
    "trace_path": str,
    "diff_path": str,
    "result_path": str,
    "verification_path": str,
}
~~~

存在 workspace_path 时，verify.py、默认 report 探测和 EvalResult.workspace_path 使用该目录。显式 Artifact 路径优先于 Python Runtime 旧默认路径。

## 9. 非目标

- 不让 TypeScript Engine 感知 Eval。
- 不迁移 Python verify.py、task discovery、report renderer 或统计逻辑。
- 不实现 TypeScript 多 Agent。
- 不实现通用模型计费或 Provider 路由。
- 不执行 setup_cmd 两次，不把依赖安装隐式塞入 Engine。
- 不解决本地依赖目录复制和 editable install 重定位。
- 不要求 TS fake Agent 修复 t01 到 t05；该门禁属于 TS-06。
- 不修改 spec_ab 的默认 Runtime。

## 10. 风险与失败策略

- stdout 污染：使用 --result-json，解析失败即报错。
- prompt 长度：通过 --task-file 传递，不占用平台命令行预算。
- 路径欺骗：所有 TS 输出路径必须 resolve 后位于预期 run root。
- stale artifact：每次调用使用独立 run root，并绑定 sessionId。
- Windows 长路径：run root 默认位于短系统临时目录，不嵌套在深层 Eval workspace 下。
- 子进程挂起：Python 层设置整体 timeout，超时终止进程组/进程树并抛 TsBridgeError。
- CLI 返回 1：若存在合法 ManagedRunResult 则保留 reason 并继续 Eval verify。
- setup 隔离差异：文档明确限制，不以错误 Workspace 做通过判定。

## 11. 测试计划

- CLI --result-json 只输出 ManagedRunResult，不输出 Agent events。
- --json/--result-json 互斥，preisolated 模式拒绝 --result-json。
- Bridge argv、task-file、cwd、shell=False、profile、fake、budget、unsafe opt-in 和 timeout 正确。
- Bridge 读取 v1 Result，映射 steps/cost/reason/trace/diff/workspace。
- CLI 返回 1 但 Result 合法时仍可消费。
- schema 错误、session 不一致、Artifact 缺失、路径越界、timeout 均失败。
- run_task 在 TypeScript 最终 Workspace 执行 verify.py。
- `run_eval --runtime typescript --fake` 对一个已满足任务完成真实端到端 smoke。
- TypeScript、Python 全量回归和 build 通过。

## 12. Definition of Done

- [x] 独立规格在实现前落盘。
- [x] CLI result-only JSON 契约完成并测试。
- [x] Python TS bridge 完成严格 schema/path 校验。
- [x] run_task 能消费 managed workspace 与 artifacts。
- [x] Python Runtime 默认行为无变化。
- [x] 真实 TS fake Eval smoke 可读取 steps、cost、reason、trace 和 diff。
- [x] Engine 无 Eval/Python 业务改动，架构测试通过。
- [x] TS/Python 全量回归和 build 通过。
- [x] 路线图更新为 TS-05 DONE、TS-06 NEXT。
- [x] 独立提交后按 fast-forward 流程合并、推送并清理 worktree。

## 13. 完成记录

- TypeScript：93 passed，0 failed。
- Python：210 passed，2 个既有 Windows GBK 解码 warning。
- Build：`npm run build` 通过。
- 真实 Eval smoke：`--runtime typescript --fake` 完成 managed run，Python verifier 在最终 TS Workspace 通过，并读取 steps、cost、reason、trace 和 diff；任务 fixture 保持不变。
- Engine：无 Eval、Python、Profile 或 Bridge 业务改动。
- 明确保留：TS fake 仍为 finish-only；本地 `.venv`/`node_modules` 与 editable install 重定位、通用模型计费、TypeScript 多 Agent 和 OS 沙箱属于后续任务。
