# TS-06 阶段实现报告

- 日期：2026-07-11
- 阶段：M1 安全执行与基础 Eval 闭环
- 任务：TS-06 基础五任务 Fake/Real Eval 验收
- 结论：完成

## 交付内容

1. 新增严格的 Model Script v1 loader：限制 1 MiB、100 responses、每 response 50 calls，拒绝未知字段和非法 usage；只读取常规文件且读取量最多为上限加 1 字节，兼容 UTF-8 BOM/CRLF。
2. TypeScript CLI 新增 `--model-script <json>`，与 CLI `--fake` 互斥，并在 managed Workspace 创建前完成加载。
3. 五个基础任务各自携带 `model-script.json`。任务逻辑仅存在于 fixture，Engine、Service、CLI 均无任务 ID 分支。
4. Python Bridge 支持 `model_script`；`--runtime typescript --fake` 按任务选择脚本，仍通过标准 Registry、Permission、Hook 和 Finish Gate。
5. Eval Report v1 增加 runtime、mode、预算、usage、session/artifact 路径和结构化基础设施错误；新增 `--budget-steps` 与退出码 0/1/2。
6. 任务发现和单任务基础设施错误会落入报告并继续后续任务；不存在的 workspace 不再伪装成 artifact。

## 基线结果

| 模式 | 解决率 | 平均 steps | 总估算费用 | 基础设施错误 |
|---|---:|---:|---:|---:|
| TypeScript Fake | 5/5 | 2.0 | $0 | 0 |
| TypeScript Real | 5/5 | 8.8 | $0.0024050712 | 0 |

Real 模型：`deepseek-v4-flash`，step budget 40，CLI timeout 600 秒。单次基线不能代表稳定模型能力；本轮用途是证明完整执行链路和形成可追溯基线。

| 任务 | 状态 | steps | 估算费用 | prompt | completion | cache read |
|---|---|---:|---:|---:|---:|---:|
| t01_implement | solved | 8 | $0.0003556728 | 9,427 | 759 | 8,576 |
| t02_fix_bug | solved | 5 | $0.0001979040 | 4,890 | 457 | 4,480 |
| t03_add_case | solved | 8 | $0.0003679144 | 9,249 | 829 | 8,448 |
| t04_fix_tested_bug | solved | 7 | $0.0004544344 | 9,599 | 963 | 8,448 |
| t05_multifile | solved | 16 | $0.0010291456 | 38,304 | 2,336 | 36,352 |
| 合计 | 5/5 | 44 | $0.0024050712 | 71,469 | 5,344 | 66,304 |

## 安全与架构

- Fake 和 Real 均使用 `accept_edits`，不启用 `--allow-unsafe-host-shell`，因此未注册 Bash。
- Model Script 只能生成标准 ModelResponse，不能直接修改 Workspace。
- Engine 无 Fake、Eval、task ID 或 model-script 分支；脚本加载属于 Host/CLI 进程边界。
- 最终 solved 状态由 Python `verify.py` 判定，Finish Gate 不充当最终 oracle。

## 审查与验证

独立 reviewer 提出的 5 项发现已全部处理：发现阶段错误隔离、虚假 workspace、Python Fake 模型元数据、有界读取和 Windows BOM 兼容。

针对性验证：

- `uv run pytest tests/test_ts_eval_bridge.py -q`：17 passed。
- `npx tsx --test tests-ts/model-script.test.ts`：31 passed。
- `npm run typecheck`：通过。

最终全量验证：

- `npm run check:ts`：125 passed，0 failed，包含架构边界测试。
- `uv run pytest -q`：216 passed；2 个既有 Windows GBK 解码 warning。
- `npm run build`：通过。
- 修复后 TypeScript Fake 五任务实跑：5/5 solved，0 infrastructure errors。
- Engine diff：为空。

## 后续拓扑

- 主线 NEXT：CM-01，完成 CMake Skill 自动选择和 Trace 记录，不修改 Engine。
- 可并行 READY：MODEL-01、MCP-01、GOV-01；三者分别属于服务层与治理层，建议使用独立 worktree 和不重叠写集。
- CM-02 继续依赖 CM-01；MA-01 继续依赖 MODEL-02。
