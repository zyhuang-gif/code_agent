# CM-01 阶段实现报告

- 日期：2026-07-11
- 阶段：M2 CMake Skill 与领域能力
- 任务：CM-01 CMake Skill 自动选择与 Trace 记录
- 结论：通用机制完成；首次 Real 未命中自动选择，移交 CM-02 做配对重复验证

## 交付内容

- `SkillDefinition.source` 使用稳定相对来源，Registry 记录 Extension ownership。
- `invoke_skill` 返回 schema v1 `skillSelection` metadata，区分 `selected` 与 `not_found`。
- CLI 只从真实 Tool 终态投影 `skill_selection` Trace，并由 CLI 写入 `selectionSource=model_tool_call`。
- 选择事件位于现有 Tool governance lifecycle 中，不新增 Engine 分支或 CMake 路由。
- 拒绝绝对来源、路径穿越和 link 越界；程序化 Skill 使用稳定 synthetic provenance。
- Extension root 仅对 `ENOENT` 返回空列表，其他加载错误显式传播。

## Fake 验收

- 任务：`c01_missing_project_header`。
- baseline failed、finish passed，共 4 steps。
- 恰好 1 条 `skill_selection(selected)`，来源为 `model_tool_call`。
- `extensionName=cmake`，`definitionSource=cmake/skills/build-fix/SKILL.md`。
- Bash 调用 0，源 fixture 未变化。
- 该结果证明 Tool、Governance 和 Trace 链路，不证明真实模型选择率。

## Real 验收

- Session：`68317ea9-dd8f-4d5b-acea-42ed9a115974`。
- 结果：`reason=completed`，5 steps，baseline failed、finish passed。
- 使用量：prompt 6102、completion 732、cache read 5248 tokens。
- 修复内容：为 `add_executable` 增加遗漏的 `src/add.cpp`。
- Bash 0、`invoke_skill` 0、`skill_selection` 0。
- 结论：任务解决，但真实模型自动选择 Skill 未通过证据门槛。

用户随后明确同意第二次发送相同 r08 源码/prompt 并接受额外少量费用。当前执行环境仍因外部私有 workspace 数据披露限制禁止再次发送，因此第二次调用未执行、未产生费用，也没有用间接方式绕过。

## 安全与架构

- Engine diff 为空；Engine 不感知 Skill、Extension、CMake 或选择事件。
- `invoke_skill` 保持只读、非破坏、serial、closed-world 属性。
- input schema、Hook、Permission 或审批在 Tool 执行前拒绝时，不伪造 Skill 终态。
- Trace payload 使用字段白名单，不包含 Skill instructions、Tool Result content、messages、本机绝对路径或 secrets。
- `allowed-tools` 仍是 Skill instructions 提示，不在 CM-01 中假装成为强制权限白名单。

## 审查与验证

- `npm run check:ts`：134 passed，0 failed。
- `uv run pytest -q`：216 passed，2 个既有 Windows GBK 解码 warning。
- `npm run build`：通过。
- `git diff master -- src/engine`：为空。
- 标准 Python 首次重跑因系统 Temp ACL 产生 153 个 fixture setup errors；将 TMP/TEMP 和 `--basetemp` 固定到 worktree 后全量通过，确认不是代码断言回归。
- 标准 build 在沙箱内因既有 `dist` 产物写权限失败；同一 `npm run build` 在批准的沙箱外执行通过。

## 后续拓扑

- 主线 NEXT：CM-02，先实现通用 A/B harness，不调用外部模型。
- Real pilot：r08 control/treatment repeat-3，treatment 至少 2/3 selected 才申请 full。
- Full：10 tasks x 2 variants x repeat-3，共 60 次；必须独立获得数据外发与费用批准。
- CM-03/CM-04 继续由 CM-02 的 traces 和量化结果决定，不提前实现领域工具。
- 可并行 READY：MODEL-01、MCP-01、GOV-01，使用独立 worktree 和不重叠写集。
