# TypeScript Runtime 迁移路线图

- 创建日期：2026-07-11
- 状态：Active
- 当前主干阶段：TS-01 到 TS-06 与 CM-01 已完成；CM-02 为下一项
- 核心原则：纵向切片、兼容迁移、每项独立验收

## 1. 目标

将当前 Python Agent 原型逐步迁移为 TypeScript 的 CC-like Runtime，同时保留 Python Eval 作为行为基线，直到 TypeScript 在安全执行、基础 Eval、CMake、治理、MCP 和多 Agent 等方面达到切换条件。

迁移不是逐文件翻译。每个任务必须交付一条用户可感知的端到端能力，并能通过自动测试和实际 CLI 或 Eval 验证。

## 2. 架构约束

四层核心保持如下边界：

1. 引擎层：协调模型、上下文和工具，不包含领域业务和直接 I/O。
2. 工具层：Agent 的全部可执行能力，统一声明访问、破坏性、并发、幂等和开放世界属性。
3. 服务层：仅包含模型 API、上下文管理/压缩和 MCP 生命周期/发现。
4. 安全与治理层：权限、Hook、Bash/执行安全、审计和恢复等横切控制。

产品功能以 Extension 形式接入。CMake、Python、Rust 等能力不得在引擎中出现硬编码分支。

## 3. 状态定义

| 状态 | 含义 |
|---|---|
| DONE | 已实现、测试、合并并推送 |
| NEXT | 当前下一项，可直接进入实现 |
| READY | 依赖已经满足 |
| BLOCKED | 存在未满足依赖或外部决策 |
| BACKLOG | 已存档，暂未进入实现 |

## 4. 里程碑和任务

### M0：TypeScript 四层基础

| ID | 状态 | 任务 | 验收摘要 |
|---|---|---|---|
| TS-00 | DONE | 四层 Runtime Foundation | TS 类型检查、15 个测试、Python 199 个回归测试通过；提交 9e7dac9 |

### M1：安全执行与基础 Eval 闭环

目标：TypeScript Runtime 能在隔离 Workspace 中修改代码、验证、生成 Diff，并由现有 Python Eval 驱动。

| ID | 状态 | 任务 | 依赖 | 核心验收 |
|---|---|---|---|---|
| TS-01 | DONE | Workspace 隔离、Git Checkpoint、Rollback、Final Diff | TS-00 | 源仓库不变；修改仅发生在 Run Workspace；新增/修改/删除均进入 Diff；可安全回滚 |
| TS-02 | DONE | Project Profile YAML 兼容加载 | TS-00 | 兼容现有 Python/Node/CMake Profile；默认值和超时语义稳定 |
| TS-03 | DONE | Verification Hook 与 Finish Gate | TS-01, TS-02 | 测试失败阻止 Finish；基线失败与新增失败可区分 |
| TS-04 | DONE | Trace、Result 和 Artifact 持久化 | TS-01 | 生成 trace.jsonl、result.json、verification.json、final.diff |
| TS-05 | DONE | Python Eval 调用 TS CLI | TS-01..TS-04 | 现有 Eval 能读取 steps、cost、reason、trace、diff |
| TS-06 | DONE | 基础五任务验收 | TS-05 | t01 到 t05 Fake/Real 均 5/5；形成结构化基线报告 |

### M2：CMake Skill 与领域能力

目标：先证明 Skill 有价值，再提取确定性工具，始终保持引擎无 CMake 分支。

| ID | 状态 | 任务 | 依赖 | 核心验收 |
|---|---|---|---|---|
| CM-01 | DONE | Skill 自动选择和 Trace 记录 | TS-04, TS-06 | 通用选择机制、稳定来源和 Trace 投影完成；首次 Real 未选择 Skill，证据移交 CM-02 |
| CM-02 | READY | CMake Skill A/B Eval | CM-01 | 比较无 Skill 与有 Skill 的 Solve Rate、选择率、步骤和成本 |
| CM-03 | BLOCKED | cmake_scan 只读工具 | CM-02 | 只有 Eval 证明重复扫描是瓶颈后才实现；结构化返回 targets/includes/links |
| CM-04 | BLOCKED | cmake_verify 独占工具 | TS-03, CM-02 | configure/build/ctest 阶段化执行；并发属性为 exclusive |
| CM-05 | BLOCKED | Fix Report 和 Repair Memory Hooks | TS-04, CM-04 | PostRun 生成报告；成功后保存可追溯 Repair Case |
| CM-06 | BLOCKED | CMake 迁移验收 | CM-01..CM-05 | 现有 CMake Eval 不低于 Python 基线；引擎架构测试继续通过 |

### M3：共享服务产品化

| ID | 状态 | 任务 | 依赖 | 核心验收 |
|---|---|---|---|---|
| MODEL-01 | READY | Streaming、Retry、Timeout 和错误分类 | TS-06 | 模型中断和限流有结构化错误；事件可流式展示 |
| MODEL-02 | BACKLOG | Model Routing、Usage 和 Cost | MODEL-01 | 不同角色可配置模型；成本进入 RunResult 和 Eval |
| CTX-01 | BACKLOG | Token Budget 和 Tool Result Pruning | TS-04 | 按真实 Token/预算触发，不只按字符数 |
| CTX-02 | BACKLOG | LLM Conversation Compaction | CTX-01, MODEL-01 | 压缩前后 Hook 可用；关键约束和未完成事项保留 |
| MCP-01 | READY | 真实 MCP Transport | TS-06 | 支持至少一种 Transport；连接、发现、关闭和超时可测试 |
| MCP-02 | BACKLOG | MCP ToolPolicy 映射与权限 | MCP-01 | Annotation 转换为内部 ToolPolicy；MCP 工具不能绕过治理 |

### M4：安全与治理产品化

| ID | 状态 | 任务 | 依赖 | 核心验收 |
|---|---|---|---|---|
| GOV-01 | READY | 持久化 Permission Rules | TS-06 | 支持 allow/ask/deny，匹配 Tool、路径、命令、域名和 MCP Server |
| GOV-02 | BACKLOG | Plugin/项目 Hook 配置 | TS-04 | Plugin 可注册 Hook，不修改引擎；Hook 结果可审计 |
| GOV-03 | BACKLOG | Shell AST/命令段风险分析 | GOV-01 | 正确处理管道、连接符、PowerShell/cmd/bash 差异 |
| GOV-04 | BACKLOG | Secret Redaction 和审计完整性 | TS-04 | Tool Result、Trace 和模型回灌前统一脱敏 |
| GOV-05 | BACKLOG | OS 级文件系统和网络沙箱 | GOV-03 | 安全不依赖字符串白名单；资源和网络限制可验证 |

### M5：多 Agent

| ID | 状态 | 任务 | 依赖 | 核心验收 |
|---|---|---|---|---|
| MA-01 | BACKLOG | RoleSpec 和角色工具集 | TS-06, MODEL-02 | Planner/Coder/Reviewer 配置化，无角色硬编码 |
| MA-02 | BACKLOG | 全局任务预算和角色子预算 | MA-01 | 角色预算总和不能突破 Task Budget |
| MA-03 | BACKLOG | Planner/Coder/Reviewer 编排 | MA-01, MA-02 | Review/Rework 回路不修改基础 Agent Runtime |
| MA-04 | BACKLOG | 多 Agent Eval | MA-03 | 与单 Agent 比较 Solve Rate、成本和步骤 |

### M6：切换和 Python Runtime 退出

| ID | 状态 | 任务 | 依赖 | 核心验收 |
|---|---|---|---|---|
| CUT-01 | BACKLOG | CLI 和 Artifact 完整兼容 | M1..M5 | TS 覆盖当前用户可见能力和输出格式 |
| CUT-02 | BACKLOG | 默认入口切换到 TS | CUT-01 | README、CI、Eval 默认使用 TS；Python 仍可回退 |
| CUT-03 | BACKLOG | Python Agent Runtime 弃用/删除 | CUT-02 | 经过稳定窗口后删除；Python Eval 和数据分析可保留 |

## 5. 依赖图

~~~mermaid
flowchart LR
  TS00["TS-00 Foundation"] --> TS01["TS-01 Workspace"]
  TS00 --> TS02["TS-02 Profile"]
  TS01 --> TS03["TS-03 Verification"]
  TS02 --> TS03
  TS01 --> TS04["TS-04 Artifacts"]
  TS03 --> TS05["TS-05 Eval Bridge"]
  TS04 --> TS05
  TS05 --> TS06["TS-06 Basic Eval Gate"]
  TS06 --> CM01["CM-01 Skill Selection"]
  CM01 --> CM02["CM-02 CMake A/B"]
  CM02 --> CM03["CM-03 cmake_scan"]
  CM02 --> CM04["CM-04 cmake_verify"]
  CM04 --> CM05["CM-05 Report/Memory Hooks"]
~~~

## 6. 每个任务的 Definition of Done

每项任务必须同时满足：

1. 从最新 master 创建独立 worktree。
2. 需求、非目标、接口和验收条件在实现前明确。
3. 新增自动测试，并先验证失败场景。
4. TypeScript 严格类型检查通过。
5. 全部 TypeScript 测试通过。
6. 现有 Python 测试无回归。
7. 使用真实 CLI 或 Eval 验证用户可感知行为。
8. 架构边界测试继续通过。
9. 文档与状态表同步更新。
10. 一个任务形成独立提交，fast-forward 合并并推送。

## 7. 当前下一项

TS-01 到 TS-06 与 CM-01 已完成。CM-01 的 Fake 验证证明了通用 Skill 选择、治理和 Trace 链路；首次 Real 任务虽 solved，但模型未调用 `invoke_skill`，因此不能把自动选择能力标记为已证明。当前主线 NEXT 是 CM-02：CMake Skill 配对 A/B Eval。

MODEL-01、MCP-01 和 GOV-01 的依赖也已满足，可在互不重叠的 worktree 中并行规格化和实现。CM-02 已解除依赖，但真实运行必须由具备外发权限且获得用户明确同意的执行者完成。

完成规格见：../tasks/TS-01-workspace-checkpoint.md、../tasks/TS-02-project-profile.md、../tasks/TS-03-verification-gate.md、../tasks/TS-04-trace-artifacts.md、../tasks/TS-05-python-eval-bridge.md 和 ../tasks/TS-06-basic-eval-gate.md
