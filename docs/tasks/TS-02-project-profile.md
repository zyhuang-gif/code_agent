# TS-02：Project Profile YAML 兼容加载

- 状态：DONE
- 任务：TS-02 Project Profile
- 工作分支：`Codex/ts-project-profile`
- 依赖：TS-01 的 TypeScript CLI、内置工具和隔离工作区
- 并行任务：TS-04 在其他 worktree 开发；本任务不修改共享路线图及其汇总文档

## 1. 范围

本任务把现有 Python `agent/profile.py` 的项目配置能力接入 TypeScript Runtime，保持 `profiles/*.yaml` 的字段名、默认值和匹配语义兼容。

### 1.1 Profile 字段

YAML 使用现有 snake_case 字段；TypeScript 对外类型使用 camelCase：

| YAML | TypeScript | 默认值 | 校验 |
|---|---|---:|---|
| `ignore` | `ignore` | `[]` | 字符串数组 |
| `syntax_check` | `syntaxCheck` | `{}` | 字符串到字符串的映射 |
| `setup_cmd` | `setupCmd` | `null` | `string \| null` |
| `setup_needs_network` | `setupNeedsNetwork` | `true` | boolean |
| `setup_timeout` | `setupTimeout` | `300` | 正整数（秒） |
| `test_cmd` | `testCmd` | `null` | `string \| null` |
| `test_timeout` | `testTimeout` | `300` | 正整数（秒） |
| `command_timeout` | `commandTimeout` | `300` | 正整数（秒） |
| `pass_when` | `passWhen` | `exit_zero` | 非空字符串 |
| `parse_test_output` | `parseTestOutput` | `null` | `string \| null` |
| `language` | `language` | `null` | `string \| null` |
| `max_file_bytes` | `maxFileBytes` | `200000` | 正整数（字节） |

`null` 或空 YAML 文档表示默认 Profile。所有默认值与 Python `ProjectProfile` 保持一致。

### 1.2 错误契约

解析、读取和校验失败统一抛出结构化 `ProfileError`，至少包含：

- 稳定的 `code`（读取失败、YAML 语法错误、根节点错误、未知字段、类型错误或范围错误）；
- `field`（字段级错误时）；
- `source`（配置文件路径或 `<memory>`）；
- 面向用户的 `message`，不得静默忽略未知字段。

未知字段在 snake_case 和已支持字段集合之外均报错。当前不做 snake_case/camelCase 混用的隐式兼容，以避免拼写错误被吞掉。

### 1.3 CLI 和工具接入

- CLI 增加可选 `--profile <yaml>`；未指定时使用默认 Profile。
- Profile 只在 CLI 启动阶段加载一次，并将工具所需的派生配置传给 `createBuiltInTools`。
- `ignore` 只追加到内置工具已有的核心忽略集合，不能取消 `.git`、缓存目录等核心安全忽略。
- `maxFileBytes` 用于 `read_file` 的大文件保护和 `grep` 的候选文件过滤。
- `commandTimeout`（秒）转换为 bash 工具默认的 `timeoutMs`（毫秒）；调用方显式传入的超时仍可覆盖默认值。
- `setup*`、`test*`、`syntaxCheck`、`passWhen` 和 `parseTestOutput` 在本任务只加载并暴露，不自动执行或解释，留给 TS-03。

## 2. 非目标

- 不实现 setup、syntax check、test command 的执行编排或输出解析。
- 不修改 engine、services、governance 层，也不引入 Profile 对这些层的依赖。
- 不修改 Python Profile 实现、现有 YAML 文件、共享路线图、`docs/tasks/README`、README 或架构总览。
- 不支持未知字段透传、隐式类型转换、未知字段忽略或危险的 YAML 执行标签。
- 不改变 CLI 的 workspace 隔离、权限审批和 host shell 策略。

## 3. 接口草案

`src/host/project-profile.ts` 提供：

- `ProjectProfile`：包含上述 camelCase 字段及 `shouldIgnore(relPath)`；
- `createDefaultProjectProfile()`：返回独立的默认实例；
- `parseProjectProfile(value, source?)`：校验已解析的 YAML 值；
- `loadProjectProfile(filePath)`：读取 UTF-8 YAML 并返回 Profile；
- `ProfileError`：结构化、可被 CLI 直接展示的错误类型。

`src/tools/builtins.ts` 提供一个不依赖 host 层的 Profile 派生配置接口，`createBuiltInTools(config?)` 默认使用 Python 兼容的 200000 字节/300 秒配置。CLI 负责把 `ProjectProfile` 映射为该配置。

## 4. 测试计划

- 读取仓库真实的 `profiles/python.yaml`、`node.yaml`、`cmake.yaml`、`empty.yaml`；验证 snake_case 到 camelCase 的映射。
- 验证所有默认值、最小 Profile、未知字段、错误类型、零/负数/非整数范围错误和 YAML 语法错误。
- 验证目录名、glob、硬性 VCS/缓存忽略，以及自定义 ignore 不能取消核心忽略。
- 验证 `read_file`/`grep` 的 `maxFileBytes` 行为和 bash schema/执行默认超时配置。
- 验证 CLI 使用 `--profile` 的 fake smoke；非法 Profile 的结构化错误由 Profile 单元测试覆盖。
- 运行 `npm run check:ts`、`npm run build`；若环境权限阻止 build，至少完成 typecheck/test 并记录原因。

## 5. Definition of Done

- [x] Profile YAML 加载、默认值、snake_case 映射和结构化错误契约完成。
- [x] 四个真实仓库 Profile 均可读取，未知字段和错误类型不会被静默吞掉。
- [x] CLI 的 `--profile` 和默认 Profile 路径均可工作。
- [x] 内置工具保留核心安全忽略，并应用自定义 ignore、文件大小限制和命令默认超时。
- [x] setup/test/syntax_check 仅暴露，不自动执行。
- [x] TypeScript 测试、typecheck、build 结果已记录。
- [x] 只修改本任务允许的文件，未提交 commit，未触碰主仓库及其他 worktree。

## 6. 完成记录

- 实现文件：`src/host/project-profile.ts`、`src/tools/builtins.ts`、`src/cli.ts`、`src/index.ts`。
- 测试文件：`tests-ts/profile.test.ts`、`tests-ts/tools.test.ts`、`tests-ts/cli.test.ts`。
- 依赖：主线程已加入 `yaml@^2.9.0` 并更新 `package.json` / `package-lock.json`。
- 关键决策：YAML 仅接受 snake_case 已知字段；Profile 对外使用 camelCase；超时单位在 Profile 中为秒，在 bash schema 中转换为毫秒；核心忽略与 Profile ignore 取并集且不支持反向取消。
- 验证：`npm run check:ts` 通过（typecheck 通过，71 tests passed，0 failed）；`npm run build` 通过。
- 范围确认：未修改 engine、services、governance、共享路线图、`docs/tasks/README`、README 或架构总览；未创建提交。
