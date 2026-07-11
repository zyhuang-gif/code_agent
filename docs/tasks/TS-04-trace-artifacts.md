# TS-04：Trace、Result 和 Artifact 持久化

- 状态：DONE
- 优先级：P0
- 所属里程碑：M1 安全执行与基础 Eval 闭环
- 依赖：TS-01
- 阻塞任务：TS-05、CM-01、GOV-02、GOV-04
- 目标提交：独立 feat 提交

## 1. 用户故事

作为代码 Agent 的使用者和 Eval 调用方，我希望一次 managed run 的 Host 生命周期、Agent 事件和治理事件能够按确定顺序持久化，并能通过稳定的 Result 与 Artifact 路径定位最终 Diff、Trace 和后续 Verification 结果。

## 2. 当前问题

TS-01 已提供隔离 Workspace、Git Checkpoint、`final.diff` 和最小 `result.json`，但仍缺少：

- Host 自己的版本化运行生命周期事件。
- 可并发调用但不会交叉写坏的 JSONL Trace。
- Trace 写入失败的结构化错误语义。
- `trace.jsonl` 与 `verification.json` 的固定 Artifact 路径。
- 稳定、明确且不包含完整模型消息的 Result Schema。
- managed run 对 Workspace、Checkpoint、Diff 和 Result 生命周期的可测试事件顺序。

## 3. 目标

本任务形成以下最小持久化闭环：

~~~text
prepareManagedRun
  workspace_create_start
  workspace_create_end
  checkpoint_start
  checkpoint_ready

Agent / Hook / Permission / Tool events
  -> serialized JSONL TraceSink
  -> artifacts/trace.jsonl

finalizeManagedRun
  Checkpoint.diff
  -> artifacts/final.diff
  -> diff_generated
  -> artifacts/result.json
  -> exactly one final run_result

TS-03 follow-up
  -> ArtifactStore.writeVerification(...)
  -> artifacts/verification.json
~~~

## 4. 范围

### 4.1 Host RunEvent

在 `src/host/run-events.ts` 定义独立于 Engine `AgentEvent` 的 Host 事件联合，版本为 1：

- `workspace_create_start`
- `workspace_create_end`
- `checkpoint_start`
- `checkpoint_ready`
- `diff_generated`
- `run_result`

每个 Host 事件都使用以下基础结构：

~~~typescript
interface HostRunEvent<TType extends string, TPayload> {
  schemaVersion: 1;
  sessionId: string;
  type: TType;
  payload: TPayload;
}
~~~

`RunEventSink` 只负责按调用顺序接收 Host 事件；Host 事件不得加入或扩展 `engine/contracts.ts` 中的 `AgentEvent`。

### 4.2 JSONL Trace

在 `src/governance/trace.ts` 提供串行追加写的 TraceSink。TraceSink 接收任何至少包含 `sessionId` 和 `type` 的事件，因此可记录：

- Engine `AgentEvent`。
- Host `RunEvent`。
- `HookEvent`。
- 调用方包装后的 Permission/Tool 事件。

统一落盘 Envelope：

~~~typescript
interface TraceEnvelope<TPayload = unknown> {
  schemaVersion: 1;
  timestamp: string; // UTC ISO-8601
  sessionId: string;
  type: string;
  payload: TPayload;
}
~~~

规范化规则：

1. 输入事件已有 `payload` 时直接使用该字段。
2. 输入事件没有 `payload` 时，将 `type`、`sessionId` 之外的字段组成 payload。
3. 每个 Envelope 使用一次 JSON 序列化和一次追加写，并以单个换行结束。
4. 同一个 TraceSink 实例的 `record` 调用按调用先后进入 Promise 队列；并发调用不能交叉写行，成功行顺序必须确定。
5. TraceSink 不吞掉初始化、脱敏、序列化或文件写入错误。

### 4.3 TraceError 与降级

Trace 失败通过结构化 `TraceError` 拒绝当前 `record` Promise，至少区分：

- 输入事件无效。
- Redactor 失败。
- JSON 序列化失败。
- 目录或文件追加写失败。

错误包含 Trace 路径以及可用的 `sessionId`、事件类型和原始 cause。默认实现不得把失败当作成功；是否捕获 `TraceError` 并以 best-effort 模式继续，由 Host/CLI 调用方决定。

### 4.4 Redactor 预留

提供最小同步 `Redactor` 接口，在 JSON 序列化前处理 payload。默认实现保持原值。完整 Secret Redaction、模型回灌脱敏和审计完整性属于 GOV-04，本任务不实现字段规则或 Secret 检测。

### 4.5 Artifact 布局

`ArtifactPaths` 固定提供四个文件路径：

~~~text
artifacts/
  final.diff
  result.json
  trace.jsonl
  verification.json
~~~

`ArtifactStore` 新增：

~~~typescript
writeVerification(verification: unknown): Promise<string>
~~~

该 API 只负责稳定 JSON 写入。Verification 的真实阶段、命令、退出码和基线比较 Schema 由 TS-03 定义。

### 4.6 Managed Result Schema

`result.json` 使用 `schemaVersion: 1`，固定包含：

- `type: "run_result"`
- `schemaVersion`
- `mode: "managed"`
- `sessionId`
- `sourceRepository`
- `workspace`
- `runDirectory`
- `artifactsDirectory`
- `diffPath`
- `resultPath`
- `tracePath`
- `verificationPath`
- `reason`
- `summary`
- `steps`
- `usage`

不得写入 `RunResult.messages` 或完整模型会话。未来新增字段必须通过新 Schema 版本或保持向后兼容。

### 4.7 Managed Run 生命周期

`prepareManagedRun` 与 `finalizeManagedRun` 接收可选 `RunEventSink`，不传时保持 TS-01 行为兼容。

Prepare 顺序：

1. 发 `workspace_create_start`。
2. 创建隔离 Workspace。
3. 发 `workspace_create_end`。
4. 初始化 Artifact 目录。
5. 发 `checkpoint_start`。
6. 初始化 Checkpoint。
7. 发 `checkpoint_ready`。

Finalize 顺序：

1. 生成 Diff。
2. 成功写入 `final.diff`。
3. 发 `diff_generated`。
4. 构造稳定 `ManagedRunResult` 并写入 `result.json`。
5. 发一次且仅一次 `run_result`，并保证它是该次成功生命周期的最后一个 Host 事件。

任何前置步骤失败时，不发送其对应的完成事件；Sink 失败直接向调用方传播。

## 5. 非目标

TS-04 不负责：

- Verification 命令执行、Finish Gate 或验证结果判定（TS-03）。
- 完整 Secret Redaction（GOV-04）。
- Trace 文件轮转、压缩、远程上传或数据库索引。
- 跨多个 TraceSink 实例协调同一文件的全局顺序。
- 持久化完整模型 messages。

## 6. 接口与依赖边界

- `governance/trace.ts` 不导入 Engine 或 Host 类型，只依赖事件共有的结构，从而保持四层依赖测试通过。
- `host/run-events.ts` 定义 Host 事件与 `RunEventSink`。
- `host/managed-run.ts` 负责生命周期编排，不把 Host 事件加入 Engine Runtime。
- `DeferredRunEventSink` 在 Artifact 目录创建前缓冲 Host 事件，CLI 创建 TraceSink 后按原顺序重放并转发后续事件。
- `governance/artifacts.ts` 只管理已验证 Run Layout 下的路径和原子文件写入。
- `src/index.ts` 导出新增公共接口。

## 7. 风险与处理

1. **并发追加交叉**：单 Sink 内用 Promise 队列串行化，每行一次 append。
2. **一次失败污染后续队列**：每个调用收到自己的失败；内部队列恢复后允许后续记录继续尝试。
3. **Trace 静默丢失**：所有失败包装为 `TraceError` 并 reject，不做默认降级。
4. **Result 泄漏完整上下文**：只从 `RunResult` 选择 reason、summary、steps、usage。
5. **Host/Engine 事件混层**：RunEvent 保持在 Host 层，AgentEvent 不修改。
6. **Artifact 进入代码 Diff**：所有四个 Artifact 路径继续位于隔离 repository 外。

## 8. 测试计划

### 8.1 Trace

- 多次顺序写入产生可逐行解析的 JSONL。
- 并发 `record` 调用保持调用顺序，行内容不交叉。
- AgentEvent、Host RunEvent 和带 payload 的治理事件使用统一 Envelope。
- Envelope 的 `schemaVersion`、ISO timestamp、sessionId、type、payload 正确。
- 写入或序列化失败返回结构化 `TraceError`，后续调用仍可按队列继续。
- Redactor 在序列化前被调用。

### 8.2 Artifact

- `ArtifactPaths` 同时包含 final.diff、result.json、trace.jsonl、verification.json。
- 四个文件都位于 Artifact Directory 且在 Repository 外。
- `writeVerification` 写入带末尾换行的稳定 JSON。
- 原有路径逃逸和目录边界校验继续通过。

### 8.3 Managed Run

- Prepare 事件顺序固定为 workspace start/end、checkpoint start/ready。
- Finalize 先写 Diff，再写 Result。
- `diff_generated` 在 Diff 成功持久化后出现。
- `run_result` 只有一个并且是最后一个事件。
- 持久化 Result 与返回值一致，包含四个 Artifact 路径，不包含 messages。
- Source Repository 保持不变。

## 9. 验收标准

- [x] Host RunEvent 为 schemaVersion 1 的独立联合，未修改 Engine AgentEvent。
- [x] JSONL TraceSink 串行、追加写，重复和并发调用均不产生交叉行。
- [x] Trace 失败以结构化 TraceError 暴露，默认不吞错。
- [x] Trace Envelope 字段和事件规范化规则有自动测试。
- [x] ArtifactPaths 提供四个固定文件路径。
- [x] `writeVerification` 可写入最小 JSON Artifact。
- [x] Result Schema 为版本 1 且不持久化完整 messages。
- [x] managed prepare/finalize 生命周期事件顺序有测试。
- [x] 每次成功 finalize 只发送一个、且最后发送 `run_result`。
- [x] managed CLI 自动持久化 Host、Engine 和 Hook 事件，stdout 最后一条仍为 Host `run_result`。
- [x] `npm run check:ts` 通过。
- [x] `npm run build` 通过。
- [x] 只修改任务允许的文件且不创建提交。

## 10. 实现记录

- 新增独立 Host `RunEvent` v1 与可选 `RunEventSink`。
- 新增 `DeferredRunEventSink`，避免 Trace 提前创建 run directory 干扰 Workspace 创建。
- 新增串行追加写 `FileSystemTraceSink`、统一 Trace Envelope、结构化 `TraceError` 与 Redactor 预留。
- Artifact 布局扩展为 `final.diff`、`result.json`、`trace.jsonl`、`verification.json`，并提供 `writeVerification`。
- managed prepare/finalize 生命周期按规格发事件；Result v1 不包含模型 messages。
- CLI 将 Engine 事件与 Hook/Permission/Tool 生命周期写入同一 Trace，并保持最终 Host `run_result` 顺序。
- Targeted tests：12 passed，0 failed。
- `npm run check:ts`：76 passed，0 failed。
- Python 回归：199 passed，3 个既有 warning。
- `npm run build`：通过。
- 编译后 managed CLI smoke：21 条 Trace；前四条为 workspace/checkpoint 生命周期；最后且唯一的 Host `run_result`。
