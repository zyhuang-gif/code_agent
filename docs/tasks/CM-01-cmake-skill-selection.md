# CM-01：CMake Skill 自动选择与 Trace 记录

- 状态：DONE
- 优先级：P0
- 所属里程碑：M2 CMake Skill 与领域能力
- 依赖：TS-04、TS-06
- 阻塞任务：CM-02
- 目标提交：独立 feat 提交

## 1. 用户故事

作为 Runtime 维护者，我希望真实模型在遇到 CMake 仓库时，不需要 CLI 显式指定 Skill，也不需要 Engine 增加 CMake 分支，就能从统一工具目录中选择 `cmake-build-fix`；选择结果必须进入稳定 Trace，能够回答“谁选择了什么、定义来自哪个扩展、最终是否成功加载”。

## 2. “自动选择”的语义

CM-01 的自动选择是 **model-driven tool selection**：

1. Extension Registry 把所有 Skill 的名称和描述公开为一个通用 `invoke_skill` Tool。
2. 模型根据任务、仓库检查结果和 Tool 描述决定是否调用 `invoke_skill`。
3. 调用继续经过 ToolRegistry、Permission、Hook 和并发调度。
4. 成功执行后，Skill instructions 作为普通 Tool Result 回灌模型。

CM-01 不实现 `profile.language == "cmake"`、文件名或关键词驱动的宿主预注入。那会把“模型选择”改成“宿主路由”，并绕开 `invoke_skill` 的标准工具治理链。若未来需要确定性预选，必须作为通用 Extension Selector 独立设计。

## 3. 架构边界

- Engine：无改动，不感知 Skill、CMake、Extension 或选择事件。
- Extension：声明 Skill，Registry 负责目录、来源和标准 `invoke_skill` Tool Result metadata。
- Tool/Governance：`invoke_skill` 保持只读、非破坏、serial、closed-world；所有调用经过现有治理。
- CLI：把通用 Tool 终态投影为 `skill_selection` Trace，不参与领域决策。
- Trace：继续使用 schema v1 开放事件类型，不新增 Host RunEvent 或可阻断 Hook。
- CMake：只存在于 `extensions/cmake` 的 manifest、Skill 内容和 Eval fixture。

## 4. 稳定来源

`SkillDefinition.source` 从机器绝对路径收紧为 Extension root 下的稳定 POSIX 相对来源，例如：

~~~text
cmake/skills/build-fix/SKILL.md
~~~

Registry 另外记录 Skill 所属 Extension，例如 `cmake`。选择来源和定义来源必须分开：

- `selectionSource = model_tool_call`：谁触发了选择。
- `extensionName = cmake`：定义属于哪个扩展。
- `definitionSource = cmake/skills/build-fix/SKILL.md`：定义来自哪个稳定文件。

## 5. Tool Result metadata

`invoke_skill` 每次真正执行后返回 `metadata.skillSelection`：

~~~ts
interface SkillSelectionAudit {
  readonly schemaVersion: 1;
  readonly outcome: "selected" | "not_found";
  readonly requestedSkill: string;
  readonly selectedSkill?: string;
  readonly extensionName?: string;
  readonly definitionSource?: string;
}
~~~

- 已知 Skill：`selected`，包含 selectedSkill、extensionName 和 definitionSource。
- 未知 Skill：`not_found`，不伪造 selectedSkill 或定义来源。
- selectionSource 不由 Extension metadata 自报；CLI 只在真实 Engine Tool 终态投影时写入 `model_tool_call`。
- input schema 拒绝、pre-tool Hook 阻止、Permission 拒绝和审批拒绝发生在 Tool 执行前，不产生伪造的 Skill 终态；现有治理 Trace 已记录这些事实。

## 6. skill_selection Trace

CLI 在通用 `post_tool_use` / `post_tool_use_failure` Trace handler 之后注册只读审计投影：当 Tool Result 含合法 `metadata.skillSelection` 时，追加：

~~~json
{
  "type": "skill_selection",
  "sessionId": "...",
  "payload": {
    "schemaVersion": 1,
    "invocationId": "skill-1",
    "selectionSource": "model_tool_call",
    "outcome": "selected",
    "requestedSkill": "cmake-build-fix",
    "selectedSkill": "cmake-build-fix",
    "extensionName": "cmake",
    "definitionSource": "cmake/skills/build-fix/SKILL.md"
  }
}
~~~

成功顺序必须为：

~~~text
model_end
tool_start(invoke_skill)
pre_tool_use
permission_request
post_tool_use
skill_selection(selected)
tool_end(invoke_skill)
~~~

未知名称使用 `post_tool_use_failure -> skill_selection(not_found)`。每次真正执行的 `invoke_skill` 恰好形成一条选择终态。

TraceSink 写入、序列化或 redaction 失败继续传播，不把不可审计运行报告为成功。

## 7. Fake 验收

新增 managed CLI scripted smoke，源码仓库包含 `CMakeLists.txt`，Model Script 先调用 `invoke_skill(cmake-build-fix)` 再 `finish`。验收：

- Run 成功并形成 managed artifacts。
- `invoke_skill` 的 pre-tool、permission、post-tool 和 Agent tool events 完整。
- 恰好一条 `skill_selection(selected)`，来源和顺序符合本规格。
- 未注册 Bash，不使用 `--allow-host-shell`。
- Engine diff 为空。

Fake 只证明工具、治理和 Trace 链路，不证明真实模型的选择能力。

## 8. Real 验收

使用 `eval/tasks_cmake_real/r08_local_library_source_omitted` 做一次 managed Real CLI smoke。该 prompt 不直接写出 “CMake”，模型必须检查仓库并从工具目录选择 Skill。

约束：

- 使用 `accept_edits`，step budget 20。
- 不启用 `--allow-host-shell`；验证命令由 Verification Gate 执行。
- 必须先获得用户对源码/prompt 发送给 DeepSeek及少量费用的明确同意。
- 核心通过条件是 Trace 出现真实 `invoke_skill -> skill_selection(selected)`；任务是否最终 solved 单独记录，不以单次模型随机结果阻塞选择链路验收。

实际结果：

- 首次 DeepSeek Real session：`68317ea9-dd8f-4d5b-acea-42ed9a115974`。
- Runtime 正常完成，`reason=completed`，共 5 steps；prompt tokens 6102、completion tokens 732、cache read tokens 5248。
- baseline failed、finish passed；模型通过为 `add_executable` 增加 `src/add.cpp` 修复任务。
- Bash 调用 0，`invoke_skill` 调用 0，`skill_selection` 事件 0。
- 结论：真实任务被解决，但本次运行没有证明模型会自动选择 `cmake-build-fix`。
- 用户随后明确同意第二次发送同一 r08 源码与 prompt 并接受少量费用；当前执行环境仍因外部私有 workspace 数据披露限制禁止再次发送，因此第二次调用未执行，不能把授权误记为 Real 选择通过。

CM-01 据此按“通用选择机制、治理链和 Trace 投影完成”结项。真实模型选择率、重复性和收益比较移交 CM-02，通过配对 A/B 与重复运行形成证据。

## 9. 安全与隐私

- 新事件采用字段白名单，不包含 instructions、Tool Result content、messages、workspace 路径或错误堆栈。
- definitionSource 必须是稳定相对来源，不记录本机 Extension 绝对路径。
- 现有通用 Tool/Agent Trace 的全面 secret redaction 属于 GOV-04，不在 CM-01 内假装完成。
- `allowed-tools` 目前仍是 Skill instructions 提示，不是强制权限白名单；CM-01 不改变这个事实。

## 10. 非目标

- 不实现宿主 CMake 路由、Activation 关键词或 Profile 自动注入。
- 不增加 `--skill`、`--disable-skill` 或有/无 Skill 分组。
- 不运行 CMake A/B、repeat、统计显著性或全 10 任务基线；这些属于 CM-02。
- 不实现 `cmake_scan`、`cmake_verify`、Fix Report 或 Repair Memory。
- 不修改 Engine、Model Service、Context Service、MCP 或 Python Runtime。
- 不修复所有通用 Tool lifecycle 缺失事件；只投影真正执行后带 metadata 的 Skill 终态。

## 11. 测试计划

- loader：Extension 加载后的 definitionSource 为稳定 POSIX 相对路径。
- registry：已知/未知 Skill 的 metadata、Extension ownership 和结果内容。
- CLI：CMake managed scripted smoke、唯一 selection 事件、字段、治理顺序和无 Bash。
- Trace：selection payload 仅含白名单字段。
- Architecture：Engine 无 CMake、Skill routing、Extension import 改动。
- `npm run check:ts`、`npm run build`、Python 全量回归。
- 获得明确同意后执行一次 Real CMake managed CLI smoke。

## 12. Definition of Done

- [x] 独立 worktree 从最新 master 创建。
- [x] 需求语义、边界、非目标和验收先于实现落盘。
- [x] Skill 稳定来源和 Registry ownership metadata 完成。
- [x] `skill_selection` Trace 审计投影完成。
- [x] Fake managed CMake smoke 通过且治理顺序可证。
- [x] Real CMake smoke 完成并如实记录未命中结果。
- [x] Engine diff 为空，架构测试通过。
- [x] TypeScript/Python 全量回归和 build 通过。
- [x] 路线图、任务索引、架构说明和阶段实现报告更新。
- [x] 独立提交、fast-forward 合并、推送并清理 worktree。

## 13. 当前拓扑

~~~text
Extension stable provenance + selection metadata
                     |
                     v
CLI terminal Hook -> skill_selection Trace
                     |
                     v
Fake managed smoke -> Real negative evidence -> CM-02 paired A/B
~~~

Extension metadata 与 CLI Trace 的写集不重叠，可按本规格并行实现；CLI 测试依赖 metadata 契约，合并后统一验证。

## 14. 上下文交接记录（2026-07-11）

- 分支：`Codex/cmake-skill-selection`。
- Worktree：`D:\source\agent\code_agent\code-agent\.Codex\worktrees\cmake-skill-selection`。
- 基线：`d3d2c69`；当前改动未提交、未合并、未推送。
- 已实现：稳定 Skill provenance、Extension ownership、selected/not_found metadata、CLI `skill_selection` 终态投影、正负向 managed CLI 测试。
- 安全加固：调用来源由 CLI 根据真实 Tool 终态赋值；绝对/穿越来源拒绝；程序化 Skill 使用稳定 synthetic source；realpath 阻断 link 越界；Extension root 仅对 ENOENT 返回空目录。
- Fake CMake smoke：`c01_missing_project_header` baseline failed、finish passed、4 steps、1 条 selected event、0 Bash，源 fixture 未变化。为规避既有 quoted MinGW command 和 Windows 长路径问题，使用 `.tmp/cm01-cmake-profile.yaml` 与短 run root；这些临时文件不入库。
- 首次 Real：session `68317ea9-dd8f-4d5b-acea-42ed9a115974`，completed、5 steps、baseline failed、finish passed；修复 `add_executable` 缺少的 `src/add.cpp`，但 0 `invoke_skill`、0 `skill_selection`，因此是真实选择负证据。
- 第二次 Real：用户已明确同意发送相同 r08 源码/prompt 并承担少量费用，但当前执行环境仍禁止再次向外部 DeepSeek 披露私有 workspace 数据；未执行、未产生费用，不得伪造结果。
- 最终验证：`npm run check:ts` 134 passed；`uv run pytest -q` 216 passed、2 个既有 Windows GBK warning；`npm run build` 通过；Engine diff 为空。
- 后续：CM-02 使用空 Extension root 作为 control、`extensions` 作为 treatment，先做 r08 repeat-3 选择率门禁，再决定是否运行 10 任务 repeat-3 全量 A/B。
