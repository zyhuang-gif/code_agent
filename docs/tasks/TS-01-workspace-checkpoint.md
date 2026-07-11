# TS-01：Workspace 隔离、Git Checkpoint、Rollback 和 Final Diff

- 状态：DONE
- 优先级：P0
- 所属里程碑：M1 安全执行与基础 Eval 闭环
- 依赖：TS-00
- 阻塞任务：TS-03、TS-04、TS-05
- 目标提交：独立 feat 提交

## 1. 用户故事

作为代码 Agent 的使用者，我希望 Agent 永远在独立运行 Workspace 中修改代码，而不是直接修改源仓库；运行结束后能够获得完整 Diff，运行失败或取消时能够安全回滚。

## 2. 当前问题

现有 TypeScript CLI 的 workspace 参数直接指向被操作目录，缺少：

- 源仓库和运行目录分离。
- 可验证的运行目录边界。
- Git 基线和完整 Diff。
- 新增文件进入 Diff 的可靠机制。
- Rollback。
- 统一 Artifact 路径。
- Workspace 生命周期事件。

因此当前 TS Runtime 只适合在调用方已经提供隔离目录时运行，不能作为面向用户的默认安全执行路径。

## 3. 目标

实现一条安全 Workspace 生命周期：

~~~text
Source Repository
  ↓ create isolated copy
Run Directory / repository
  ↓ initialize ephemeral Git baseline
Agent Runtime
  ↓ tools modify isolated repository
Checkpoint.diff
  ↓ write artifacts/final.diff
RunResult
  ↓ preserve run directory for inspection
~~~

## 4. 范围

### 4.1 Workspace 创建

- 接收源仓库路径和 Run Root。
- 在 Run Root 下创建唯一 Session/Run 目录。
- 将源仓库复制到 Run Directory 的 repository 子目录。
- 默认排除源仓库的 .git 元数据和运行时缓存。
- 不修改源仓库。
- 返回经过解析和验证的绝对路径。

### 4.2 Git Checkpoint

- 在隔离 Repository 内初始化临时 Git 仓库。
- 设置仅限当前仓库的 Git Identity。
- 将初始文件加入基线提交。
- 生成包括新增、修改、删除和二进制文件的最终 Diff。
- 支持显式 Rollback。

### 4.3 Artifact 布局

每次运行使用：

~~~text
<run-root>/<session-id>/
  run.json
  repository/
    ... isolated project files ...
    .git/
  artifacts/
    final.diff
    result.json          # TS-04 完善，本任务只预留/写最小内容
~~~

Artifact 必须位于 repository 之外，避免进入代码 Diff。

### 4.4 CLI 集成

新增安全入口参数，建议：

~~~text
--repo <source-repository>
--run-root <runs-directory>
~~~

保留现有 workspace 参数作为内部/Eval 已隔离模式，但必须明确模式：

~~~text
--workspace <already-isolated-directory>
--workspace-is-isolated
~~~

禁止在没有显式 already-isolated 声明时把 workspace 直接当作用户源仓库。

## 5. 非目标

TS-01 不负责：

- 测试命令或 Finish Gate（TS-03）。
- 完整 Trace/Result Schema（TS-04）。
- Python Eval 桥接（TS-05）。
- Git Worktree Backend。
- 远程 Git Clone。
- 依赖安装。
- OS 级沙箱。
- 自动清理所有历史 Run。
- CMake 专项行为。

## 6. 架构归属

Workspace 是 Host/Composition 基础设施，不是第四个核心业务层。Checkpoint 和 Rollback 属于安全治理。

建议文件：

~~~text
src/host/workspace.ts
src/host/run-layout.ts
src/governance/checkpoint.ts
src/governance/artifacts.ts
~~~

依赖规则：

- engine 不得导入上述具体实现。
- CLI/Host 创建 Workspace 后，将隔离路径传给 AgentRuntime。
- AgentRuntime 只看到 ToolContext.workspace。
- Tool 层不得自行创建、删除或切换 Workspace。
- Rollback 只能由可信 Host/Governance 调用，不能暴露成默认模型工具。

## 7. 建议接口

### 7.1 Workspace Provider

~~~typescript
interface WorkspaceRequest {
  sourceRepository: string;
  runRoot: string;
  sessionId: string;
  ignorePatterns?: readonly string[];
}

interface WorkspaceSession {
  sessionId: string;
  runDirectory: string;
  repository: string;
  artifactsDirectory: string;
  sourceRepository: string;
}

interface WorkspaceProvider {
  create(request: WorkspaceRequest): Promise<WorkspaceSession>;
}
~~~

### 7.2 Checkpoint

~~~typescript
interface Checkpoint {
  initialize(): Promise<void>;
  diff(): Promise<string>;
  rollback(): Promise<void>;
}

interface CheckpointFactory {
  create(workspace: WorkspaceSession): Checkpoint;
}
~~~

具体实现可命名为 GitCheckpoint，但引擎和 Host 依赖接口。

### 7.3 最小 Result

~~~typescript
interface WorkspaceRunResult {
  sessionId: string;
  sourceRepository: string;
  workspace: string;
  runDirectory: string;
  artifactsDirectory: string;
  diffPath: string;
  reason: string;
}
~~~

## 8. Workspace 安全不变量

实现必须保证：

1. Run Directory 的解析绝对路径位于配置的 Run Root 内。
2. Repository 路径固定为 Run Directory 的子目录。
3. Artifact Directory 不位于 Repository 内。
4. Source Repository 和 Repository 不能解析为同一路径。
5. 复制过程不能跟随逃逸到源仓库外部的 Symlink/Junction。
6. Rollback 前必须验证 Run Marker 和 Run Root 边界。
7. 任何递归清理只能作用于验证过的 Run Directory。
8. Agent Tool 无法写入 Artifact Directory 或源仓库。
9. 源仓库的 .git 不被复制到隔离 Repository。
10. Git 命令使用参数数组，不通过 shell 拼接路径。

## 9. 默认忽略项

第一版至少排除：

~~~text
.git/
.Codex/worktrees/
node_modules/
.venv/
__pycache__/
.pytest_cache/
dist/
coverage/
workspace/
trace/
.tmp/
~~~

Project Profile 的 ignorePatterns 可以追加，但不能取消核心安全忽略项。

是否复制 node_modules/.venv 属于性能与兼容权衡。本任务默认不复制，并在文档中明确需要由后续 Setup 阶段重新准备依赖。

## 10. Git 基线和 Diff 语义

### 10.1 初始化

建议使用参数数组调用：

~~~text
git init
git config user.name Code Agent
git config user.email code-agent@localhost
git add -A
git commit -m baseline
~~~

必须检查每条命令的 Exit Code，不能忽略初始化失败。

### 10.2 Artifact 排除

Artifact 位于 Repository 外，因此不应依赖 .gitignore 排除。针对构建产生物，Checkpoint 可以写入 Repository 私有的 .git/info/exclude，但不能修改项目受版本控制的 .gitignore。

### 10.3 新文件 Diff

普通 git diff HEAD 不包含未跟踪新文件。实现必须明确处理新文件，例如：

- 对未跟踪文件使用 intent-to-add 后生成 Diff；或
- 枚举未跟踪文件并生成 no-index Diff。

不得通过正式 git add/commit 用户改动来掩盖最终状态。

### 10.4 二进制

使用二进制安全 Diff 参数，并对输出设置大小上限。超过限制时：

- Artifact 保存完整允许范围内的文件；
- 模型上下文只获得截断摘要；
- Result 标记 truncated。

## 11. Rollback 语义

Rollback 必须恢复：

- 被修改的基线文件。
- 被删除的基线文件。
- Agent 新增的未跟踪文件。

允许在已验证的隔离 Repository 内使用 Git Reset/Clean，但必须同时满足：

- 存在本系统创建的 Run Marker。
- Repository 位于 Run Root 内。
- Repository 不等于 Source Repository。
- 调用来自可信 Host，而不是模型 Tool Call。

Rollback 完成后 diff 必须为空。

## 12. 错误模型

至少区分：

| 错误 | 行为 |
|---|---|
| source_not_found | 创建前失败，不产生 Repository |
| run_root_invalid | 拒绝创建 |
| path_escape | 拒绝创建或清理 |
| unsupported_link | 拒绝复制逃逸链接 |
| workspace_copy_failed | 保留错误信息，可清理未完成 Run |
| git_not_available | 明确返回环境错误 |
| checkpoint_init_failed | 不启动 Agent Runtime |
| diff_failed | RunResult 标记失败，保留 Workspace |
| rollback_failed | 保留 Workspace，禁止静默宣称已恢复 |

## 13. Hook 和事件

TS-01 应预留或发送：

~~~text
workspace_create_start
workspace_create_end
checkpoint_start
checkpoint_ready
diff_generated
rollback_start
rollback_end
~~~

完整持久化由 TS-04 实现，但事件结构应在本任务中确定。

## 14. 测试计划

### 14.1 Workspace 单元测试

- 创建隔离副本，源仓库内容不变。
- 路径含空格和中文时可工作。
- Run Root 逃逸被拒绝。
- .git 和默认缓存不被复制。
- Artifact Directory 位于 Repository 外。
- 两次运行生成不同 Session Directory。

### 14.2 Checkpoint 单元测试

- 修改已有文件进入 Diff。
- 新增文件进入 Diff。
- 删除文件进入 Diff。
- 二进制文件变化不导致崩溃。
- 无变化时 Diff 为空。
- Git 命令失败返回结构化错误。

### 14.3 Rollback 单元测试

- 恢复修改文件。
- 恢复删除文件。
- 删除新增文件。
- Rollback 后 Diff 为空。
- Source Repository 不受影响。
- 缺少 Run Marker 时拒绝 destructive rollback。

### 14.4 CLI 冒烟

~~~powershell
npm run start:ts -- --fake --repo <fixture> --run-root <temp-runs> --task "smoke"
~~~

验证输出包含：

~~~text
source_repository=
workspace=
run_directory=
diff_path=
reason=completed
~~~

## 15. 验收标准

TS-01 完成必须满足：

- [x] 默认 CLI 路径不直接修改源仓库。
- [x] Workspace 和 Artifact 布局符合规格。
- [x] Checkpoint 初始化失败会阻止 Agent 启动。
- [x] 新增、修改、删除均进入 final.diff。
- [x] Rollback 可恢复全部工作区变化。
- [x] 路径逃逸和错误清理目标被拒绝。
- [x] engine 无 Git、复制、Artifact 具体实现依赖。
- [x] TypeScript 严格类型检查通过。
- [x] TypeScript 全部测试通过。
- [x] Python 199 个现有测试无回归。
- [x] 源码和编译后 CLI 冒烟通过。
- [x] 路线图状态从 NEXT 更新为 DONE；TS-02 和 TS-04 标记为可并行 NEXT；TS-03 继续等待 TS-02。

## 16. 实现顺序

1. 定义 Workspace/Checkpoint 合约和错误类型。
2. 实现安全 Run Layout 和路径验证。
3. 实现过滤复制。
4. 实现 GitCheckpoint 初始化与 Diff。
5. 实现带 Marker 校验的 Rollback。
6. 接入 CLI 的 repo/run-root 安全模式。
7. 写 Artifact final.diff 和最小 result.json。
8. 添加单元测试、架构测试和 CLI 冒烟。
9. 跑 TS/Python 全量验证。
10. 更新路线图状态、独立提交、fast-forward 合并并推送。

## 17. 完成记录

实现完成记录：

- 提交：本任务实现提交（见 Git history）
- TypeScript 测试：严格类型检查通过；51 passed，0 failed
- Python 测试：199 passed，保持 3 个既存 Windows/pytest 警告
- CLI/Eval 证据：源码测试和编译后 CLI 均完成 managed workspace 冒烟；输出 session 事件、run_result、final.diff 和 result.json；源仓库保持不变
- 遗留问题：
  - preisolated CLI 模式仅用于调用方明确声明已隔离的过渡兼容路径，不创建第二层 managed checkpoint/artifact
  - Host shell 默认不注册；显式 --allow-host-shell 仍是未沙箱化高风险能力，等待 GOV-05
  - Diff 超限当前返回结构化失败，流式 Artifact 和 truncated 元数据留给 TS-04/CTX-01
  - 第一版拒绝所有 symlink/junction，后续如需支持必须新增安全复制策略和平台测试


## 18. 安全收敛记录

实现阶段通过并行安全审查额外修复：

- Checkpoint 使用初始化时保存的不可变 baseline OID，Agent 自行 commit 不能绕过 Diff 或 Rollback。
- 基线强制跟踪复制后的 ignored 文件；新增 ignored 文件进入 Diff；Rollback 恢复已有 ignored 文件并删除新增项。
- Run Marker 所有字段强制校验并与实际路径精确匹配。
- Git 使用空 template、禁用 commit hook、禁用 external diff/textconv、屏蔽 system/global Git config，并设置命令超时。
- runRoot 和 sourceRepository 两棵目录树必须完全不相交。
- 默认不向模型注册 Host Bash Tool；显式启用后仍始终按 write/open-world 权限处理。
- ArtifactStore 只能从经过验证的 Run Layout 创建，Artifact 必须位于 Repository 外。
