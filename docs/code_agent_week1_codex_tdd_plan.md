# 第 1 周实现执行指令（给 Codex，严格 TDD）

> 执行者：Codex。本文件是你的唯一任务书。开工前**必读**同目录两份文档：
> - `code_agent_prototype_plan.md`（整体路线，理解边界）
> - `code_agent_week1_design.md`（第 1 周详细设计：模块/数据结构/接口/Locator/ProjectProfile）
>
> 本文件 = 上面设计的 **TDD 落地步骤 + 注意事项 + 交付要求**。设计文档里的接口契约（`ProjectProfile` 字段、`Locator` 协议、工具集、trace 格式）是**契约，不得擅自改**；如确需偏离，必须在交付说明里单列「偏离项 + 理由」。

---

## 0. 铁律（TDD，违反即作废重来）

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
没有一个先失败的测试，就不准写任何产品代码。
```

每个行为都走 **RED → 验证 RED → GREEN → 验证 GREEN → REFACTOR**：

1. **RED**：先写一个测试，只测一个行为，命名清晰，测真实行为（不要测 mock 的行为）。
2. **验证 RED**：运行该测试，**亲眼确认它失败，且失败原因是"功能缺失"而非拼写/导入错误**。
3. **GREEN**：写**刚好够让测试通过**的最小实现。不要提前加设计文档没要求的功能（YAGNI）。
4. **验证 GREEN**：再运行，确认该测试通过、且其它测试仍全绿、输出无 error/warning。
5. **REFACTOR**：仅在绿灯下清理（去重、改名、抽函数），不加新行为，保持全绿。

**如果你已经先写了产品代码再补测试 —— 删掉那段产品代码，从测试重写。不要"留作参考"、不要"边写测试边改它"。删就是删。**

测试立即通过（没经历过 RED）= 这个测试无效，重写。

### 你必须留下 TDD 证据（我据此验收）
对每个模块，在交付里贴出**至少一个代表性行为**的：
- RED 阶段 `pytest` 失败输出片段（看得出是"功能缺失"）
- GREEN 阶段 `pytest` 通过输出片段

没有 RED/GREEN 证据的模块，视为未按 TDD 完成。

---

## 1. 环境与技术约束

- **语言/运行**：Python，使用虚拟环境（`python -m venv .venv`）。本机是 **Python 3.14**；若 `openai`/`pyyaml` 在 3.14 无 wheel 装不上，降级到 3.12/3.13 并在交付里说明。
- **测试框架**：`pytest`。所有测试放 `code-agent/tests/`，文件名 `test_<module>.py`。
- **依赖**：`openai`、`pyyaml`、`pytest`（写进 `requirements.txt`）。`git`、`ripgrep` 已装，但见下条。
- **关键约束 ①｜测试全程不联网、不调真实 DeepSeek**。`llm.py` 必须支持**依赖注入**：构造时可传入一个 client 对象；测试注入 fake client 返回预设响应。真实 DeepSeek key 留给人工端到端验收，不进自动化测试。
- **关键约束 ②｜`GrepLocator` 用纯 Python 实现**（`os.walk`/`pathlib` + `re`），**不依赖 ripgrep 二进制**。理由：测试确定性 + 跨平台。接口保持 `Locator` 协议不变，未来要性能再换 rg（设计 §5.1 已留位）。
- **关键约束 ③｜跨平台**：一律用 `pathlib.Path`，不要硬编码 `/` 或 `\`；不要假设 bash。本机是 Windows。
- **关键约束 ④｜外部进程可注入**：凡是要跑子进程的地方（`run_command`、editor 的语法校验、checkpoint 的 git），把"执行器"做成可注入参数，测试可注入 fake，真实实现用 `subprocess`。
- **小步提交**：在 `code-agent/` 里 `git init`，每个模块全绿后 `git commit`（提交信息含模块名），便于我按 commit 验收 TDD 节奏。

---

## 2. 实现顺序（自底向上，依赖在前）

```
1 profile.py      6 tools.py
2 trace.py        7 checkpoint.py
3 locator.py      8 budget.py
4 llm.py          9 loop.py        （集成，fake LLM）
5 editor.py      10 main.py        （CLI 薄封装）
                 11 eval/run_eval.py + eval/tasks/t01..t03
```

每个模块**先全部走完自己的 TDD 循环并全绿**，再进入下一个。不要并行铺开半成品。

---

## 3. 逐模块 TDD 任务清单

> 下面每个「行为」= 一个独立的 RED-GREEN-REFACTOR 循环。签名是契约，可按需补类型，但不得改变语义。

### 3.1 `profile.py` —— ProjectProfile + 加载
契约见设计 §3.2。行为：
- [ ] 从 dict 构造 `ProjectProfile`，未提供字段取默认值（`pass_when="exit_zero"`、`max_file_bytes=200_000` 等）。
- [ ] `load_profile(path)` 从 YAML 文件加载并返回 `ProjectProfile`。
- [ ] 加载缺省 YAML（只有 `ignore`）时其余字段为默认。
- [ ] 提供 `should_ignore(rel_path)`：命中 `ignore` 里的目录名/glob 返回 True。
注意：可变默认值用 `field(default_factory=...)`，别用 `={}`。

### 3.2 `trace.py` —— JSONL 事件记录
契约见设计 §6。行为：
- [ ] `Trace(path)` 写入一条 `llm_call` 事件，读回该 JSONL 行字段齐全（含 `cache_hit_tokens`/`cache_miss_tokens`/`cost_usd`）。
- [ ] 追加多条事件 → 文件有多行，顺序一致。
- [ ] 写 `tool_exec` 与 `run_summary` 事件，字段符合 §6。
注意：每行一个合法 JSON 对象；大字段（args/result）截断后再写。

### 3.3 `locator.py` —— Locator 接口 + GrepLocator（纯 Python）
契约见设计 §5.1。行为：
- [ ] 临时目录建几个文件，`GrepLocator.search(pattern)` 返回命中（含 `path`、`line_no`、`line`）。
- [ ] `glob` 参数限定只搜匹配文件。
- [ ] 命中所在被 `ignore` 的目录（如 `node_modules`）不返回。
- [ ] `symbols(path)` 抛 `NotImplementedError`（L2 未实现，留接口）。
注意：`Locator` 写成 `typing.Protocol`；`GrepLocator` 注入 profile 以读 `ignore`/`max_file_bytes`。

### 3.4 `llm.py` —— DeepSeek 客户端封装（依赖注入）
行为：
- [ ] 注入 fake client，`LLMClient.chat(messages, tools)` 把 `model=deepseek-v4-flash`、messages、tools 正确传给底层 client。
- [ ] 解析响应里的 `tool_calls`（OpenAI 格式：`id`/`function.name`/`function.arguments`），返回结构化结果；`arguments` 是 JSON 字符串需 `json.loads`。
- [ ] 从 `response.usage` 提取 `prompt_cache_hit_tokens`、`prompt_cache_miss_tokens`、`completion_tokens`，并按下方价格算 `cost_usd`。
- [ ] 每次调用写一条 `llm_call` 事件到注入的 `Trace`。
- [ ] 响应无 `tool_calls`、只有 `content` 时也能正确返回（供 loop 判断"想结束"）。

**价格常量（`deepseek-v4-flash`，$/百万 token）**，放模块常量或 config：
```
INPUT_CACHE_HIT  = 0.0028
INPUT_CACHE_MISS = 0.14
OUTPUT           = 0.28
cost = (hit*0.0028 + miss*0.14 + completion*0.28) / 1_000_000
# 注意 prompt_tokens = cache_hit_tokens + cache_miss_tokens
```
注意（写进代码注释/交付说明）：
- base_url = `https://api.deepseek.com`，用 `openai` SDK；模型名 **`deepseek-v4-flash`**（不要用将于 2026/07/24 弃用的 `deepseek-chat`）。
- **缓存零代码**：靠 messages 前缀稳定自动命中，无需 `cache_control`。loop 构造 messages 时务必把 system + 仓库概览放最前且每轮不变。
- **不要依赖并行 tool_calls**；按一次一个处理（见 loop）。
- fake client 的响应对象结构要贴近 openai SDK（`.choices[0].message.tool_calls` / `.usage.prompt_cache_hit_tokens` 等），便于将来换真 client 不改 `LLMClient`。

### 3.5 `editor.py` —— SEARCH/REPLACE + 校验
契约见设计 §6（编辑策略）。注入一个 command runner 以跑语法校验。行为：
- [ ] `search` 在文件中唯一命中 → 替换成功，文件内容正确变更。
- [ ] `search` 不存在 → 返回 `is_error=True`，**文件不被修改**，错误信息可回灌让 LLM 重出。
- [ ] `search` 多处命中（歧义）→ 返回错误，要求更精确，不乱改。
- [ ] profile 配了该扩展名的 `syntax_check` 且改后语法错 → 返回校验失败（注入 fake runner 返回非零）；语法对 → 成功。
- [ ] profile 没配该扩展名校验 → 跳过校验、仅保证写入成功。
注意：替换后做语法校验时调用注入的 runner，测试不真跑解释器（也可对 `.py` 真用 `py_compile`，二选一，但要可注入）。

### 3.6 `tools.py` —— 工具注册表 + 6 个工具
契约见设计 §5。每个工具暴露 `ToolSpec`（name/description/parameters JSON Schema/handler）。行为：
- [ ] `list_dir`：返回目录树，**过滤 profile.ignore**，不展开被忽略目录。
- [ ] `read_file`：按 `start_line/end_line` 返回**带行号**的片段；超 `max_file_bytes` 且未给区间 → 返回提示要求指定区间。
- [ ] `grep`：委托 `Locator`，返回命中（验证它确实调用了注入的 locator）。
- [ ] `edit`：委托 `editor`，透传成功/失败。
- [ ] `run_command`：注入 runner，验证设置了 `cwd=workspace`、`timeout`，输出 stdout/stderr/exit_code 且**超长截断**。
- [ ] `finish`：返回一个可被 loop 识别的"结束"信号（如 `ToolResult(meta={"finish": True})`）。
- [ ] 工具注册表能按 name 取到 ToolSpec，且能导出 `tools` 参数（schema 列表）给 `LLMClient`。
注意：**断网**在 MVP 先不强制实现（平台相关）；`run_command` 留 `allow_network: bool=False` 参数与 TODO 注释即可，不阻塞本周。

### 3.7 `checkpoint.py` —— git 检查点（真调 git）
行为（用临时目录真跑 git）：
- [ ] `init(workspace)`：`git init` + 首次 `git add -A && git commit`，建立基线。
- [ ] 改动文件后 `diff()` 返回非空 unified diff；无改动时返回空。
- [ ] `rollback()` 能把 workspace 恢复到基线 commit。
注意：git 调用走注入的 runner（真实实现 subprocess）；设置 `user.name/email` 局部配置避免环境无 git 身份导致 commit 失败。

### 3.8 `budget.py` —— 预算 + 循环检测
契约见设计 §2、§4。行为：
- [ ] `Budget.ok()`：步数/累计 token/墙钟任一超限返回 False，否则 True（用可注入的时钟测时间维度，别 sleep）。
- [ ] `tick(tokens)` 累加步数与 token。
- [ ] `LoopDetector.is_repeating(action)`：同一 (tool, args) 连续/多次出现达到阈值时返回 True。
注意：时间维度测试注入 fake clock（DI），不要用真实 `time.sleep`。

### 3.9 `loop.py` —— ReAct 主循环（集成，fake LLM）
契约见设计 §4 伪代码。用**注入的 fake LLMClient**（脚本化返回一串 tool_calls，最后一步返回 `finish`）+ 真实 tools + 临时 workspace。行为：
- [ ] 正常流程：fake LLM 依次让它 `read_file`→`edit`→`finish`，loop 执行工具、把结果回灌进 messages、最终 `finalize` 产出非空 diff。
- [ ] 预算超限：fake LLM 一直不 finish，达到 `max_steps` → loop 优雅收尾（reason=budget_exceeded），不抛异常。
- [ ] 循环拦截：fake LLM 反复发同一动作 → `LoopDetector` 触发，loop 回灌"换思路"提示而非真执行。
- [ ] 无 tool_calls 的纯文本响应 → loop 不崩，按"提示去 finish/继续"处理。
- [ ] messages 前缀（system + 仓库概览）每轮保持不变（可断言首两条 message 恒定）。
注意：loop 不得内置任何语言知识；一切语言相关只经 profile / tools。

### 3.10 `main.py` —— CLI 入口（薄）
- [ ] 解析参数（任务描述、目标仓库路径、profile、配置），组装 `RunContext`，复制目标到 `workspace/`，调用 `loop.run`，打印最终 diff 路径与成本汇总。
最薄即可；可只写 1 个冒烟测试（用 fake LLM 跑通 `main()` 主流程）。

### 3.11 `eval/run_eval.py` + `eval/tasks/t01..t03`
**Harness 逻辑用 TDD + fake agent 测；真实跑真 LLM 留人工验收。**
任务素材结构（设计 §7）：每个 `eval/tasks/<id>/` 含 `repo/`、`prompt.md`、`verify`（脚本/命令，exit 0 = 解决）。

先造 3 个**简单、可自动判定**的任务（示例，可用 Python 素材，但 harness 本身语言无关）：
- `t01_implement`：`repo/greeting.py` 内 `def greet(name): ...` 未实现；verify 跑断言 `greet("World")=="Hello, World!"`。
- `t02_fix_bug`：一个函数有 off-by-one / 边界 bug；verify 跑一组断言。
- `t03_add_case`：缺一个边界处理（如空输入），verify 覆盖该边界。

`run_eval.py` 行为（TDD，注入 **fake agent** = 把预设修改写进 workspace 的假函数）：
- [ ] 对一个任务：复制 `repo/` 到临时 workspace → 跑 agent → 在 workspace 跑 `verify` → exit 0 记 `solved`。
- [ ] verify 非 0 → 记 `failed`。
- [ ] 多任务汇总：输出解决率（solved/total）与平均步数/成本（从 trace 汇总）。
注意：自动化测试里 agent 用 fake；**额外提供一份说明**：人工如何用真实 DeepSeek key 端到端跑 `run_eval`（设环境变量、装依赖、执行命令）。

---

## 4. 全局注意事项（坑）

1. **YAGNI**：只实现本文件 + 设计 §（第 1 周）列出的东西。**不要**写 repo map、tree-sitter、LSP、多 Agent、自动修复循环、断网沙箱——那些是后续周次。
2. **不要改契约**：`ProjectProfile` 字段、`Locator` 协议、6 个工具、trace 格式照设计走。要改先记偏离。
3. **DI 是 TDD 能离线跑的关键**：LLM client、command runner、clock 全部可注入。凡是"测试要联网/起子进程/等时间"的，都是该注入 fake 的信号。
4. **截断**：所有回灌给 LLM 的工具输出（stdout、文件、grep 结果）先截断（如头尾各 N 行 + 省略提示），防止撑爆上下文。
5. **mock 克制**：能用真实代码就别 mock（如 profile/trace/locator/checkpoint 用临时目录真跑）。只有"网络（LLM）/不确定的子进程/时间"才注入 fake——这属于 skill 说的"unavoidable"。
6. **输出干净**：GREEN 时 pytest 不能有 warning（如 deprecation、未关闭文件、可变默认值告警）。

---

## 5. 完成定义（DoD）与交付物（我据此验收）

交付时请一并给我：
1. **`pytest -v` 全绿**的完整输出（根目录跑）。
2. **每个模块的 TDD 证据**：至少一个行为的 RED 失败片段 + GREEN 通过片段（§0 要求）。
3. **目录树**（`code-agent/` 实际结构）与 `requirements.txt`。
4. **行为覆盖清单**：逐模块勾掉 §3 的 checkbox，标注每条对应的测试函数名。
5. **偏离说明**：任何偏离设计契约/本指令的点 + 理由（没有就写"无"）。
6. **端到端真跑说明**：人工用真实 DeepSeek key 跑通一次 `main.py` + `run_eval.py` 的命令步骤。
7. **git log**（每模块一个 commit 的历史），便于核查 TDD 节奏。

### 我的验收口径（你要满足的硬指标）
- 每个产品模块都有对应测试，且能从 git 历史/证据看出**测试先于实现**。
- 切换 `profiles/python.yaml` ↔ `profiles/empty.yaml`，loop 与 tools **无需改代码**即可运行（验证语言无关 = L0/L1 成立）。
- 预算超限能优雅收尾、重复动作被拦截（有测试覆盖）。
- 全程无真实网络调用即可让整套测试通过。
- `eval/run_eval.py` 能用 fake agent 打印解决率。

完成后把上述交付物贴出来，我来验收并收尾。
