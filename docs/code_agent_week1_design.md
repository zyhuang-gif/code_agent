# 第 1 周详细设计：Agent Loop + 工具集 + Eval + Trace

> 配套《代码 Agent 原型开发方案（修订版 v2）》§20 第 1 周。
> 已定决策：**LLM = DeepSeek（`deepseek-v4-flash`）**、**目标仓库语言无关**、**先出设计再写实现**。

## 0. 本周目标与边界

**目标**：跑通最小 ReAct 循环——agent 能在 1 个简单任务上完成「读文件 → 改文件 → 输出 diff」，`eval` 能出解决率分数，`trace` 能记录每步。

**本周做**：agent loop 骨架、工具集（read/list/grep/edit/run_command/finish）、eval harness（3 个任务）、结构化 trace、DeepSeek 接入。

**本周不做**（按方案分期）：自动修复闭环（第 3 周）、repo map 检索（第 4 周）、多 Agent（阶段三）。
注意：本周工具里**包含** `run_command`，但只是让 agent 能跑命令、让 eval 能判定；「测试失败→自动修复」的循环留到第 3 周。

## 1. 模块划分

| 模块 | 文件 | 职责 | 本周实现 |
|---|---|---|---|
| 主循环 | `agent/loop.py` | ReAct 循环、预算检查、循环检测、收尾产出 diff | ✅ |
| LLM 客户端 | `agent/llm.py` | 封装 DeepSeek（OpenAI SDK）、记 token/cache/cost | ✅ |
| 工具集 | `agent/tools.py` | 工具注册表 + 6 个工具实现 | ✅ |
| 检索 | `agent/locator.py` | `Locator` 接口 + `GrepLocator`（§5.1） | ✅（grep 版） |
| 编辑器 | `agent/editor.py` | SEARCH/REPLACE 应用 + 可选语法校验 + 失败反馈 | ✅（校验靠 profile） |
| 项目配置 | `agent/profile.py` | ProjectProfile：语言无关的关键抽象 | ✅ |
| Trace | `agent/trace.py` | JSONL 事件记录 | ✅ |
| 检查点 | `agent/checkpoint.py` | git 初始化/快照/出 diff | ✅（最小版） |
| Eval | `eval/run_eval.py` | 跑任务、调 verify、汇总解决率 | ✅ |

## 2. 核心数据结构

```python
# 消息：直接用 OpenAI 兼容结构（DeepSeek 同款）
Message = dict  # {"role": "system|user|assistant|tool",
                #  "content": str|None,
                #  "tool_calls": [...]?, "tool_call_id": str?}

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict          # JSON Schema，作为 tools 参数传给 DeepSeek
    handler: Callable[[dict, "RunContext"], "ToolResult"]

@dataclass
class ToolResult:
    content: str              # 回灌给 LLM 的文本（必须可截断）
    is_error: bool = False
    meta: dict = field(default_factory=dict)

@dataclass
class Budget:
    max_steps: int = 40
    max_tokens: int = 400_000
    max_wallclock_s: int = 600

@dataclass
class RunContext:
    workspace: Path           # 临时副本/worktree，所有操作限定在此
    profile: "ProjectProfile"
    trace: "Trace"
    budget: Budget
```

## 3. 语言无关怎么落地（本周关键设计）

核心思路：**agent 核心不内置语言知识，把语言相关的部分分三层处理，只有最上层需要未来扩展核心**。L0/L1 换语言只改配置；L2 走插件式适配器，不改 loop 与工具协议。

> 这条路线是被验证过的主流架构（Claude Code、早期 SWE-agent 都基本是「语言无关 + 通用工具 + 强 LLM」，不为每种语言内置解析器），不是妥协。repo map / LSP 是**优化项，不是必需项**。

### 3.1 语言知识三层模型

| 层 | 环节 | 实现方式 | 本周 |
|---|---|---|---|
| **L0 命令层** | 语法校验 / 测试 / lint / 构建 / 忽略 / 环境准备 | 纯配置（ProjectProfile 命令字符串） | ✅ |
| **L1 编辑层** | SEARCH/REPLACE 文本编辑 | 语言无关文本操作，靠 L0 校验命令兜质量 | ✅ |
| **L2 理解层** | 符号地图 / 找引用 / 跳定义 / 类型 | **插件式语言适配器**（tree-sitter / LSP），非纯配置 | ❌ 仅留接口 |

MVP（第 1~3 周）只用 L0 + L1，纯配置即可语言无关；L2 留 `Locator` 接口（见 §5.1），未来扩展时核心不动。

### 3.2 ProjectProfile（覆盖 L0 + L1）

```python
@dataclass
class ProjectProfile:
    ignore: list[str] = field(default_factory=list)            # [".git","node_modules","__pycache__","target",...]
    syntax_check: dict[str, str] = field(default_factory=dict) # 扩展名→校验命令；{".py":"python -m py_compile {file}"}；没有则跳过
    setup_cmd: str | None = None        # 环境准备：pip install / npm ci / go mod download
    setup_needs_network: bool = True    # setup 通常需联网，与默认断网冲突 → 单列开关，仅 setup 阶段放行
    test_cmd: str | None = None         # 本周可为 None
    pass_when: str = "exit_zero"        # 何为通过：exit_zero | 自定义；不锁死成 exit 0
    parse_test_output: str | None = None # 第 3 周用，per-framework 解析；先留空，靠 LLM 读原始输出
    language: str | None = None         # L2 用：触发加载对应语言适配器；MVP 不依赖
    max_file_bytes: int = 200_000       # 超大文件不读/不全读
```

- **编辑**走 SEARCH/REPLACE（纯文本匹配替换），天生语言无关。
- **校验**：`edit` 后若 `syntax_check` 有该扩展名命令就跑；没有只保证「文件写入成功」。语法不过 → 错误回灌让 LLM 重出（不浪费后续步骤）。
- 预置三份示例 profile（python / node / 空）放 `profiles/`，核心代码对它们零感知。

### 3.3 语言无关的边界（已知会破功的点，提前标注）

| 瓶颈 | 影响层 | 何时撞上 | 缓解 |
|---|---|---|---|
| 环境/依赖准备（install）强语言相关、需联网 | L0 | 第 3 周跑真实测试 | `setup_cmd` + `setup_needs_network` 开关，联网仅限 setup 阶段 |
| 测试输出解析 per-framework（格式各异） | L0/L1 | 第 3 周自动修复 | 先把截断后的原始输出喂 LLM，不解析 |
| 缩进敏感语言（Python/YAML）文本编辑易错 | L1 | MVP 即可能遇到 | 改后语法校验 + 失败重试（已设计） |
| 符号级定位需 tree-sitter/LSP | L2 | 第 4 周 repo map | 走 `Locator` 适配器，core 不动 |

## 4. Agent Loop 控制流（伪代码）

```python
def run(task: str, ctx: RunContext) -> RunResult:
    ctx.checkpoint.init()                     # git init + 首次 commit，留回滚基线
    messages = [system_prompt(ctx), user_prompt(task, repo_overview(ctx))]
    # ↑ 前缀（system + repo_overview）保持稳定 → DeepSeek 自动缓存命中

    seen_actions = []                          # 循环检测
    while ctx.budget.ok():
        resp = ctx.llm.chat(messages, tools=TOOL_SCHEMAS)   # trace: llm_call
        messages.append(resp.assistant_message)

        if not resp.tool_calls:                # 无工具调用＝模型想结束/纯文本
            messages.append(nudge_to_finish()) # 提示它要么调 finish 要么继续
            continue

        for call in resp.tool_calls:           # DeepSeek：按顺序逐个处理，别假设并行
            if call.name == "finish":
                return finalize(ctx)            # 产出 diff + trace + 成本汇总
            if is_repeating(call, seen_actions):# 循环检测：反复同一动作
                result = ToolResult("检测到重复动作，请换思路", is_error=True)
            else:
                result = TOOLS[call.name].handler(call.args, ctx)  # trace: tool_exec
            seen_actions.append(call)
            messages.append(tool_message(call.id, truncate(result.content)))

    return finalize(ctx, reason="budget_exceeded")   # 优雅放弃，输出已完成部分
```

要点：
- **一次处理一个工具调用**（DeepSeek 不保证并行）。
- **预算三维**（步/ token/时间）任一超限即优雅收尾。
- **循环检测**针对 DeepSeek FC 历史上的循环/空回复问题。
- 收尾统一靠 `git diff` 对比初始 commit 产出最终补丁。

## 5. 工具集接口（本周 6 个）

| 工具 | 参数（JSON Schema 要点） | 返回 | 注意 |
|---|---|---|---|
| `list_dir` | `path` | 目录树（已按 profile.ignore 过滤） | 不展开被忽略目录 |
| `read_file` | `path, start_line?, end_line?` | 带行号的片段 | **按行区间读**；超 `max_file_bytes` 强制要求区间 |
| `grep` | `pattern, glob?` | 命中行（文件:行号:内容） | 底层 ripgrep；本周主力定位手段 |
| `edit` | `path, search, replace` | 成功/失败+校验结果 | 走 §3 SEARCH/REPLACE+校验+失败反馈 |
| `run_command` | `cmd` | exit_code, stdout, stderr（截断） | 限 workspace、设超时、默认断网 |
| `finish` | `summary` | — | 触发 finalize |

所有工具结果**先截断再回灌**（如 stdout 只留头尾各 N 行），防止撑爆上下文。

### 5.1 检索抽象：`Locator` 接口（为 L2 预留）

`grep` 工具底层不写死 ripgrep，而是依赖一个 `Locator` 抽象。本周只实现纯文本版；未来加语言版时，**工具协议与 loop 不变，只换注入**。

```python
class Locator(Protocol):
    def search(self, pattern: str, glob: str | None) -> list[Hit]: ...
    def symbols(self, path: str) -> list[Symbol]: ...   # MVP 抛 NotImplementedError

class GrepLocator:          # 本周：ripgrep，语言无关
    ...
# 未来（不改 core，按 profile.language 选择注入）：
# class TreeSitterLocator:  # 符号地图 / repo map（第 4 周）
# class LspLocator:         # 找引用 / 跳定义 / 类型
```

`agent/loop.py` 与工具协议只依赖 `Locator` 抽象；MVP 注入 `GrepLocator`，上 L2 时换注入即可。

## 6. Trace 设计（JSONL，一行一事件）

```jsonc
{"t":"llm_call","step":3,"model":"deepseek-v4-flash",
 "prompt_tokens":12000,"completion_tokens":180,
 "cache_hit_tokens":11800,"cache_miss_tokens":200,   // 监控缓存命中率
 "latency_ms":900,"cost_usd":0.0021,"tool_calls":["read_file"]}
{"t":"tool_exec","step":3,"tool":"read_file","args":{...},
 "result_preview":"...","is_error":false,"duration_ms":12}
{"t":"run_summary","task_id":"t01","steps":7,"total_tokens":83000,
 "total_cost_usd":0.014,"result":"solved","diff_path":"..."}
```

## 7. Eval Harness 设计

```text
eval/
├── tasks/
│   └── t01_add_function/
│       ├── repo/            # 任务初始代码（或一个可 git init 的目录）
│       ├── prompt.md        # 给 agent 的需求
│       └── verify.sh        # exit 0 = 解决（语言无关的判定）
└── run_eval.py
```

`run_eval.py` 流程：对每个任务 → 复制 `repo/` 到临时 workspace → 跑 agent(prompt) → 在 workspace 跑 `verify.sh` → exit 0 记 solved → 汇总解决率 + 平均成本/步数。

**判定语言无关**：每个任务自带 `verify`（可以是脚本/命令），核心不关心语言。第 1 周放 3 个简单任务（例：让 verify 脚本从失败变通过），先把"出分"这条链路打通。

## 8. 目录骨架（第 1 周最小子集）

```text
code-agent/
├── agent/{loop,llm,tools,locator,editor,profile,trace,checkpoint}.py
├── prompts/system.md
├── profiles/{python.yaml,node.yaml,empty.yaml}
├── eval/{run_eval.py, tasks/t01.../}
├── trace/                  # 运行产出
├── workspace/              # 临时副本
├── config.example.yaml     # 模型/预算/路径
├── requirements.txt        # openai, pyyaml, （ripgrep 走系统二进制）
└── main.py                 # CLI 入口：单任务跑一遍
```

## 9. DeepSeek 接入落地注意点

```python
client = OpenAI(api_key=KEY, base_url="https://api.deepseek.com")
resp = client.chat.completions.create(model="deepseek-v4-flash", messages=..., tools=...)
```

- **模型用 `deepseek-v4-flash`**，不要用将于 2026/07/24 弃用的 `deepseek-chat`。
- **缓存零代码**：保证 `messages` 前缀稳定（system + repo_overview 放最前且每轮不变，变动内容追加在尾），自动命中（hit 比 miss 便宜约 50×）；在 trace 里记 `prompt_cache_hit_tokens/miss` 监控命中率。
- **循环检测必做**（FC 历史上有循环/空回复）。
- **一次一个工具**，不依赖并行 tool_calls。
- **strict schema 是 beta 端点**，原型先不用，靠 editor 的校验+失败反馈兜底。
- 若启用思维模式：工具调用轮次需把 `reasoning_content` 回传，否则推理链断。

## 10. 第 1 周验收

- [ ] `main.py` 能对 1 个简单任务跑通 ReAct 循环，输出最终 `git diff`。
- [ ] `eval/run_eval.py` 能跑 3 个任务并打印解决率与平均成本。
- [ ] `trace/` 下能看到每步 llm_call / tool_exec，含 token、cache hit/miss、cost。
- [ ] 切换 `profiles/python.yaml` ↔ `profiles/empty.yaml` 无需改核心代码（验证语言无关）。
- [ ] 预算超限能优雅收尾、循环动作能被拦截。
