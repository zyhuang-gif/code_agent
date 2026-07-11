# TypeScript Migration Tasks

本目录保存 TypeScript Runtime 迁移任务的可执行需求规格。路线图和状态总表见：../roadmap/2026-07-11-typescript-runtime-roadmap.md

## Active

| ID | 状态 | 文档 |
|---|---|---|
| TS-01 | DONE | Workspace 隔离、Git Checkpoint、Rollback 和 Final Diff：TS-01-workspace-checkpoint.md |
| TS-02 | DONE | Project Profile YAML 兼容加载：TS-02-project-profile.md |
| TS-03 | DONE | Verification Hook 与 Finish Gate：TS-03-verification-gate.md |
| TS-04 | DONE | Trace、Result 和 Artifact 持久化：TS-04-trace-artifacts.md |
| TS-05 | DONE | Python Eval 调用 TypeScript CLI：TS-05-python-eval-bridge.md |
| TS-06 | NEXT | 基础五任务 Fake/Real Eval 验收（实现前创建独立规格） |

## 归档规则

- 任务进入实现前必须有独立规格文档。
- 文档必须包含范围、非目标、接口、风险、测试和验收条件。
- 实现完成后将状态改为 DONE，并记录提交哈希、测试结果和后续遗留项。
- 尚未进入 NEXT/READY 的任务只保留在路线图，避免过早写出失效的细节设计。
