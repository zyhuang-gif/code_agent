# TS-03：Verification Hook 与 Finish Gate

- 状态：DONE
- 优先级：P0
- 依赖：TS-01 Workspace/Checkpoint、TS-02 Project Profile、TS-04 Trace/Artifact
- 目标：在不修改 Engine 业务逻辑的前提下，用 Governance Hook 阻止引入新失败的 Finish

## 1. 用户故事

作为代码 Agent 的使用者，我希望 managed run 在 Agent 开始前记录测试基线，并在每次调用 `finish` 前重新运行同一测试命令。若改动引入了新的失败，`finish` 必须被拒绝并把可操作摘要回灌给模型；若测试通过或只剩基线已有失败，则允许结束。

## 2. 架构边界

本任务遵守四层边界：

- Engine 继续只协调模型、工具和停止条件，不导入 Profile、Verification 或 Host。
- `governance/verification.ts` 负责受控命令执行、安全评估、输出限制、失败指纹和基线比较。
- `host/verification-gate.ts` 负责一次性验证副本、baseline、Artifact、Host Event 和 Hook 注册。
- CLI 只在 managed 模式组装 Verification Gate。
- Finish Gate 使用现有 `pre_tool_use` Hook 拦截 `finish`，不增加 Engine 分支，也不把验证注册成 Agent Tool。

架构测试必须保证 `src/engine` 不出现 `ProjectProfile`、`VerificationGate` 或 `testCmd` 业务逻辑。

## 3. 本次范围

### 3.1 Profile 字段

本切片执行：

- `test_cmd`
- `test_timeout`
- `pass_when=exit_zero`

无 `test_cmd` 时仍写入 `verification.json`，decision 为 `not_configured`，不启动命令，也不影响 Fake CLI。

### 3.2 Baseline

managed Workspace 和 Git Checkpoint 建立后、Agent Runtime 启动前执行 baseline：

1. 将当前 Agent Workspace 复制到 run directory 下的一次性验证目录；遇到 symlink/junction 时 fail closed。
2. 通过 Governance Verification Runner 在副本中执行 `test_cmd`。
3. 持久化 baseline attempt 和 Host verification events。
4. 删除验证副本，baseline 测试生成物不进入 Agent Workspace。
5. baseline 普通非零退出可参与后续比较；timeout/output-limit 记录但不能作为既有失败放行。
6. 命令配置、治理、workspace copy、spawn 或命令不存在等基础设施错误在 Runtime 启动前中止。

### 3.3 Finish Gate

Host 在 `HookBus` 注册 `pre_tool_use` handler：

- 非 `finish` Tool：直接继续。
- `finish`：复制当前 Agent 状态，在一次性副本中执行 final verification，并与 immutable baseline 比较。
- final 通过：允许 Finish。
- baseline 和 final 都失败，且 final 没有新增 failure key：标记 `pre_existing_failure` 并允许 Finish。
- baseline 通过而 final 失败，或 final 出现 baseline 未包含的 failure key：返回 block。
- block 后 `GovernedToolExecutor` 产生 non-terminal denied Tool Result，Agent Runtime 自然进入下一步。
- 无论 Finish 允许或阻止，批次中 Finish 后面的 Tool invocation 都不再执行，避免出现“验证后再写入”的未验证修改。
- 重复失败不会按次数放行；最终由 Agent 修复、预算耗尽或其他正常停止原因结束。

`pre_tool_use` 被阻止时必须继续发 `post_tool_use_failure` Hook，保证 Trace 生命周期完整。

## 4. 命令执行与安全

Profile 中的测试命令是 shell command string，需要兼容 `&&`。实现使用固定平台 shell argv：

- Windows：`cmd.exe /d /s /c <command>`
- POSIX：`/bin/sh -c <command>`

Node `spawn` 保持 `shell:false`，并复用 `SpawnCommandRunner` 的：

- 固定 cwd；
- stdin 关闭；
- Windows 隐藏窗口；
- 硬超时；
- 总输出字节上限；
- stdout/stderr 分离捕获。
- 清除 API key、token、secret、password、credential 等敏感环境变量后再启动子进程。
- timeout/output-limit 时尝试终止整个进程树；Windows `taskkill` 被权限拒绝时至少强制终止直接子进程。

在执行前复用 Bash Safety 评估：

- 明显破坏性命令拒绝；
- 明显网络、安装或外部系统命令拒绝；
- 未知 `pass_when` 拒绝；
- 平台 shell 无法解析命令时按基础设施错误处理。

当前只是词法风险控制，不声称已实现 OS 级文件系统或网络沙箱；该能力属于 GOV-05。

## 5. Attempt 与失败比较

每次执行生成 `VerificationAttempt`：

~~~typescript
interface VerificationAttempt {
  phase: "baseline" | "finish";
  command: string;
  timeoutMs: number;
  startedAt: string;
  durationMs: number;
  exitCode: number | null;
  passed: boolean;
  timedOut: boolean;
  outputLimitExceeded: boolean;
  stdout: string;
  stderr: string;
  failureKeys: readonly string[];
  failureKeysReliable: boolean;
  fingerprint: string;
}
~~~

输出在持久化前限制为 16,000 字符，命令总捕获上限为 2 MiB。

failure key 生成规则：

1. 统一 CRLF/LF、去 ANSI、将 Workspace 绝对路径替换为 `<workspace>`。
2. 归一化常见耗时文本和空白。
3. 优先选择包含 assert/error/exception/fail/fatal/not found/link error 等标记的行。
4. 没有标记行时使用末尾最多 20 行；无输出时使用 timeout/output-limit/exit fallback。
5. 对退出码、超时、输出限制和排序后的 failure keys 计算 SHA-256 fingerprint。

比较结果：

- `passed`：final 通过，允许。
- `pre_existing_failure`：baseline/final 都有可靠 failure keys、退出码相同，且 final keys 是 baseline keys 的子集，允许。
- `regression`：final 存在 baseline 没有的 failure keys，阻止。

timeout、output-limit、只有通用摘要或无法提取可靠 failure keys 的结果一律 fail closed，不作为既有失败放行。

完整 framework parser 和精确 failure ID 提取属于后续 Extension；当前比较保持保守，无法证明为既有失败时视为新增失败。

## 6. Verification Artifact v1

`artifacts/verification.json` 使用稳定 schemaVersion 1：

~~~typescript
interface VerificationReport {
  schemaVersion: 1;
  sessionId: string;
  command: string | null;
  timeoutMs: number;
  passWhen: string;
  security: {
    shell: "fixed_argv";
    lexicalCommandPolicy: true;
    sensitiveEnvironmentFiltered: true;
    osSandbox: false;
    workspaceIsolation: "copy";
  };
  baseline: VerificationAttempt | null;
  finishAttempts: readonly VerificationAttempt[];
  decision:
    | "pending"
    | "not_configured"
    | "passed"
    | "pre_existing_failure"
    | "blocked"
    | "error";
  blockedAttempts: number;
  newFailures: readonly string[];
  error?: { code: string; message: string };
}
~~~

Artifact 在 baseline 后和每次 finish attempt 后原子覆写。不得写入完整模型 messages、Error stack、环境变量或原始 cause。

## 7. Host 与 Trace 事件

扩展 Host RunEvent v1：

- `verification_start`
- `verification_end`
- `finish_gate_decision`

事件 payload 只记录 phase、attempt、命令 SHA-256、通过状态、退出码、超时、耗时、decision 和 failure keys，不在 Trace 重复写完整命令或 stdout/stderr。

成功 managed run 的 `run_result` 仍必须唯一且为最后一个 Host 事件。

## 8. 非目标

- 不执行 `setup_cmd`。依赖准备继续由现有 Eval/TS-05 调用方负责，避免在 TS-01 强制追踪 Checkpoint 中纳入大型依赖目录。
- 不执行逐文件 `syntax_check`，不实现编辑失败自动回滚。
- 不实现 `parse_test_output` framework parser 或自定义 pass policy 注册表。
- 不实现 CMake 阶段化验证工具；属于 CM-04。
- 不自动接入 `--workspace-is-isolated` 模式；该模式没有 managed Artifact 与可信 baseline 所有权。
- 不实现 OS 级断网、文件系统沙箱、Secret Redaction 或进程树 Job Object。
- 不修改 Python Runtime 或 Python Eval 桥接；后者属于 TS-05。

## 9. 测试计划

- 固定 shell argv、cwd、timeout、输出上限和 `exit_zero`。
- 危险、网络、未知 pass policy、命令不存在均在正确阶段拒绝。
- baseline pass/final pass 允许。
- baseline pass/final fail 阻止。
- baseline fail/final 同 failure keys 允许。
- baseline fail/final 新 failure keys 阻止。
- baseline/final 在一次性副本中运行，副作用不进入 Agent Workspace 或 final diff。
- 无命令写 `not_configured` 且不创建验证副本。
- timeout、output-limit 和无可靠 failure key 的同类失败仍阻止 Finish。
- 基础设施异常产生闭合的 `verification_end(error)`、Artifact error 和 block decision。
- pre-tool block 不执行 Finish，并发 `post_tool_use_failure`。
- managed CLI 持久化 baseline、final、Gate Artifact 和 Trace，stdout 最后仍为 `run_result`。
- Engine 架构测试证明无 Verification 业务逻辑。
- 全部 TypeScript、Python、build 和编译 CLI smoke 通过。

## 10. Definition of Done

- [x] Governance Verification Runner、结构化错误和安全评估完成。
- [x] baseline、一次性验证副本、failure keys 和 fail-closed 比较完成。
- [x] Finish Gate 通过 `pre_tool_use` Hook 阻止新增失败。
- [x] Engine 无 Profile/Verification 业务改动。
- [x] `verification.json` v1 和 Host/Trace 事件完成。
- [x] managed CLI 的 not-configured 与 passed smoke 通过。
- [x] TS/Python 全量回归、build、编译 managed CLI smoke 通过。
- [x] 路线图更新为 TS-03 DONE、TS-05 NEXT。
- [x] 独立提交后按 fast-forward 流程合并、推送并清理 worktree。

## 11. 完成记录

- TypeScript：91 passed，0 failed。
- Python：199 passed，3 个既有 warning。
- Build：`npm run build` 通过。
- 编译 managed CLI：baseline/final 均通过，Artifact decision=`passed`，一次性验证目录清空，源仓库不变，Trace 最后事件=`run_result`。
- Engine：无 Profile、Verification 或 `testCmd` 业务改动；架构测试锁定该约束。
- 明确保留：`setup_cmd`、`syntax_check`、`parse_test_output` parser、OS 级沙箱和 Python Eval bridge。
