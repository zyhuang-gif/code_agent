# 第 1 周验收修复指令（给 Codex，严格 TDD）

> 执行者：Codex。工作目录：`D:\source\agent\code_agent\code-agent`（已是 git 仓库）。
> 背景：第 1 周 MVP 已验收，24 测试全绿、契约基本达标。本文件是验收发现的问题修复单，按严重度 P0→P2。
>
> **铁律不变**：每个修复都走 TDD —— **先写一个能暴露该问题的失败测试（RED，亲眼看它失败且失败原因正确），再写最小修复（GREEN），再 REFACTOR**。
> **硬约束**：① 不得破坏现有 24 个测试，最终 `pytest -v --basetemp .tmp/pytest` 必须全绿且无 warning；② 测试不得触达真实网络（继续用注入 fake）；③ 不改已立住的契约语义，只做下列修复。
> **每个问题都要留 RED 失败片段 + GREEN 通过片段**，我据此验收。

---

## 🔴 P0 — workspace 隔离（会污染/改写用户真实仓库，最高优先级）

**现状**：`main.py:50` 把 `RunContext` 的 workspace 直接设为用户传入的 `args.repo`；`agent/loop.py:27-29` 会在该目录 `git init` + `add -A` + `commit`，并把 `trace.jsonl`/`final.diff` 写进去。
**后果**：在用户真实仓库上跑会污染目录；若目标本身是 git 仓库，baseline commit 会把用户未提交的改动一并吞掉。违反设计 `code_agent_prototype_plan.md` §9 与 `code_agent_week1_design.md` §9「只在临时副本操作，绝不直接动用户主工作区」。

**期望行为**：
- `main.py` 先把目标仓库**复制到一个一次性 workspace**（如 `workspace/run-<uuid>/` 或带时间戳目录），在**副本**上跑 loop。
- 复制时**排除 `.git`**（让 checkpoint 在干净副本上重建 baseline，不继承用户历史）。
- `trace.jsonl` / `final.diff` 写进 workspace 或独立运行目录，**绝不写入用户原始仓库**。
- 用户原始仓库在整个过程中**只读**（仅作复制源）。
- workspace 根目录可配置（`--workspace` 参数或 config，默认项目内 `workspace/`）。

**TDD**：
1. RED：写 `tests/test_main.py`（或新增）一个测试——准备一个临时"用户 repo"目录（含一个文件，**并预先 `git init` + commit 一个状态**），记录其修改前快照（文件列表 + 内容 + 有无新增提交）；用 `--fake` 跑 `main`；断言：
   - 用户原始 repo **未被修改**（无新文件、无 `final.diff`/`trace.jsonl`、git 状态/提交数不变）；
   - 实际产物落在独立 workspace 副本里。
   当前实现下该测试应**失败**（证明确有污染）。
2. GREEN：在 `main` 里用 `shutil.copytree(repo, workspace, ignore=ignore_patterns(".git"))` 建副本，`RunContext` 指向副本，trace/diff 写副本或运行目录。
3. 复跑全套确认仍全绿。

---

## 🟠 P1 — 工具真实 JSON Schema（真实 DeepSeek 工具调用质量）

**现状**：`agent/tools.py:127` 用 `any_schema`（空 `properties`、`additionalProperties:True`）作所有工具参数。测试因直接调 handler 绕过，但真实 LLM 拿不到参数定义，function calling 会大幅降准。

**期望**：每个工具给出精确 `parameters`（JSON Schema），`required` 正确、`additionalProperties:false`：
- `list_dir`：`path`(string，可选，默认 ".")
- `read_file`：`path`(string，必填)、`start_line`(integer，可选)、`end_line`(integer，可选)
- `grep`：`pattern`(string，必填)、`glob`(string，可选)
- `edit`：`path`、`search`、`replace`（均 string，必填）
- `run_command`：`cmd`(string，必填)、`timeout`(integer，可选)、`allow_network`(boolean，可选，默认 false)（与 P2-② 一起做）
- `finish`：`summary`(string，必填)

**TDD**：
1. RED：写测试断言 `build_default_registry()` 中 `edit` 的 `parameters.required == ["path","search","replace"]`、`read_file.parameters.properties` 含 `start_line`/`end_line`、`additionalProperties is False` 等。当前 `any_schema` 下断言失败。
2. GREEN：为每个 `ToolSpec` 写真实 schema。
3. 确认 `to_openai_tools()` 输出结构正确、全套全绿。

---

## 🟡 P2 — 瑕疵修复（逐条 TDD）

### ② run_command 增加 allow_network 参数
**现状**：`agent/tools.py:108` 的 `default_runner` 与 `run_command` 只在注释提 allow_network，签名无此参数。
**期望**：`run_command` 从 `args` 取 `allow_network`(默认 False) 并**透传给 runner**；`default_runner` 签名加 `allow_network: bool=False` + TODO（MVP 不真实现断网，仅留策略 hook）。
**TDD**：注入 fake runner 记录收到的 kwargs，断言 `allow_network` 被透传（默认 False；显式传 True 时为 True）。

### ① cost 真实累计
**现状**：`agent/loop.py:63` 写死 `total_cost_usd=0.0`；`LLMResult.cost_usd` 未被 loop 汇总；eval `avg_cost_usd=0.0` 即此因。
**期望**：loop 每步累计 `getattr(response,"cost_usd",0.0)`，`_finalize` 写真实总成本到 `run_summary`；eval 汇总 `avg_cost_usd` 用真实值。
**TDD**：fake LLM 的响应带 `cost_usd`（如每步 0.01），跑 read→edit→finish，断言 `run_summary` 的 `total_cost_usd` == 累计值（且 trace 里读得到）。

### ③ llm latency_ms 实测
**现状**：`agent/llm.py:68` `latency_ms=0` 硬编码。
**期望**：给 `LLMClient` 注入 `clock`（默认 `time.monotonic`），围绕 `client.chat.completions.create` 计时，写真实 `latency_ms`。
**TDD**：注入返回递增值的 fake clock，断言 trace 事件的 `latency_ms` == 计时差（不再恒为 0）。

### ④ eval 非 --fake 分支不要静默走 fake
**现状**：`eval/run_eval.py` 非 `--fake` 也走 fake，易误导。
**期望**：把 agent 构造做成可注入（`agent_factory`）。`--fake` 用 fake factory；不带 `--fake` 时走"真实"工厂（构造 `AgentLoop + LLMClient`），若未配置 `DEEPSEEK_API_KEY` 则**明确报错退出**并提示，而不是假装跑 fake。
**TDD**：注入一个假的 real factory，断言不带 `--fake` 时调用的是 real factory（而非 fake）；未配置 key 时给出明确错误（注意此测试仍不真连网络，靠注入）。

### ⑤ 语言无关显式测试（补我列过的硬指标）
**期望**：用两个不同 profile（`ProjectProfile()` 空 vs 配了 `.py` syntax_check 的 profile）跑**同一段** read→edit→finish 序列，都能成功，证明切 profile **无需改核心代码**。
**TDD**：参数化测试覆盖两种 profile，断言两次都 `finished` 且产出预期 diff；syntax_check 的命令用注入 runner 模拟（返回 exit 0），不真跑解释器。

### ⑥ loop 复用 checkpoint.diff() + 不吞 init 异常
**现状**：`agent/loop.py:31` `try/except pass` 静默吞掉 `checkpoint.init()` 异常；`_finalize` 用裸 `subprocess git diff` 而非复用 `GitCheckpoint.diff()`。
**期望**：把 `GitCheckpoint` 实例提到 `run` 开头、`_finalize` 复用其 `diff()`；`init()` 失败不静默吞，至少写一条 trace 警告（diff 退化为空但不崩）。配合 P0（副本排除 .git）后，init 应正常成功。
**TDD**：断言正常路径下 `result.diff` 来自 checkpoint 且非空；init 失败（注入会失败的 runner）时 loop 不抛、reason 仍正常、trace 有警告记录。

---

## 交付物（我据此验收）

1. `pytest -v --basetemp .tmp/pytest` 全绿、无 warning 的完整输出（测试数应比现在的 24 增加）。
2. 每个问题（P0、P1、P2 各条）的 **RED 失败片段 + GREEN 通过片段**；P0 的 RED 必须能看出"用户 repo 被污染"。
3. 受影响文件清单 + 每条修复对应的测试函数名。
4. 偏离说明（如有）。
5. git 历史：建议每条修复一个 commit（`fix(p0): ...` 等）。
6. 重申 P0 后的端到端真跑命令（确认现在跑 `main.py` 不再碰用户原始仓库）。

完成后把上述交付物贴给我，我再验收并收尾。
