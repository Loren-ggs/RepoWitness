# RepoWitness（仓证）产品策略与第一阶段实施边界

## 1. 产品定位

RepoWitness 是一个基于 CoreCoder Agent 结构二次开发的只读仓库契约审查 Agent。

一句话定位：

> 一个基于 CoreCoder 的只读仓库契约审查 Agent，让每次代码变更都对仓库自己的规则负责。

英文标语：

> Evidence-backed review against your repository’s own rules.

RepoWitness 连接的是“仓库中以自然语言存在的项目规范”和“本次真实代码变更”。它不判断一段代码是否符合通用最佳实践，而是判断本次变更是否遵守目标仓库已经明确写下的架构、兼容性、安全、测试和开发规范。

## 2. 要解决的问题

仓库通常已经在以下位置积累了大量规则：

- `AGENTS.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- ADR 和架构文档
- 目录边界与依赖规则
- 测试、兼容性和安全要求

这些规则通常只能依赖开发者和 Reviewer 记忆。现有工具各有明确但有限的职责：

- pre-commit、Lint 和静态检查适合确定性任务；
- Conftest/Rego 适合结构化配置；
- 测试框架只能验证已经被编码成测试的行为；
- 通用 AI Reviewer 往往使用泛化最佳实践，无法准确代表当前仓库自己的约束。

RepoWitness 填补自然语言项目规范与实际 Git diff 之间的审查空白。

## 3. 已确认的产品决策

### 3.1 规则权威版本

PR 审查默认使用目标分支（base revision）中的规则。

本次变更可以修改 `AGENTS.md` 或其他契约文档，但修改后的规则不会反过来成为审查本次变更的依据。契约文档变更会在报告中单独展示。

本地场景如需审查尚未合并的新规则，必须显式指定 worktree/head 作为契约来源。

### 3.2 确定性检查只消费、不执行

RepoWitness 第一版可以消费预先产生的测试、Lint、pre-commit、JUnit、SARIF 或标准 evidence JSON 结果，但不负责执行这些命令。

外部检查结果只有在其 commit SHA 或工作区 fingerprint 与本次审查快照匹配时，才能作为 `PASS` 的正向证据。

### 3.3 第一版为建议模式

第一版是 advisory mode：

- 报告可以包含 `FAIL`；
- `FAIL` 不会默认让 CLI 或 GitHub Actions 失败；
- 审查完整执行后退出码为 `0`；
- 仓库、配置、模型鉴权或报告生成等运行错误使用非零退出码。

Required Check 和 `--fail-on fail` 在规则质量及误报率稳定后再引入。

### 3.4 基于现有 CoreCoder 做最小扩展

项目直接在当前 `corecoder/` 基础上开发，并将 Python 包重命名为 `repowitness/`。

以下 CoreCoder 能力继续复用：

- Agent 主循环；
- 实例级工具集；
- 工具参数校验和错误分类；
- 并行工具执行；
- tool call/result 配对；
- Ctrl+C 中断后的 tool reply 回填；
- 上下文压缩；
- LLM provider、重试、流式工具调用和 token 统计；
- 父子 Agent 接线逻辑。

Agent 框架只增加 RepoWitness 新功能所必需的扩展，例如可注入的 system prompt。

## 4. 能力边界

RepoWitness：

- 读取仓库规范文档；
- 读取本次 Git diff；
- 读取相关代码和测试；
- 消费已有确定性检查结果；
- 生成 JSON 和 Markdown 审查报告；
- 在 GitHub Actions 中发布建议性审查结果。

RepoWitness 不会：

- 修改、创建或删除仓库文件；
- 暂存、提交或推送代码；
- 执行 Bash；
- 自动运行测试、Lint 或 pre-commit；
- 自动修复问题；
- 生成业务功能；
- 输出泛化代码风格建议；
- 取代人工 Reviewer；
- 第一版阻止 PR 合并。

## 5. CoreCoder 复用与工具注册策略

原有以下工具源码暂时保留：

- `bash`
- `write_file`
- `edit_file`
- `agent`

父子 Agent 逻辑也继续保留，但第一版不使用。

保留源码不等于注册能力。RepoWitness 的默认工具注册表为空，每个 Agent 必须显式获得自己的工具集。上述四个工具不会出现在 Contract Compiler Agent 或 Review Agent 的 tool schemas 中。

正式运行路径只注册仓库契约审查需要的工具。

## 6. 两类 Agent

### 6.1 Contract Compiler Agent

职责是读取 base revision 中由确定性代码发现的契约文档，并将自然语言规范编译成结构化规则。

第一阶段工具：

- `contract_sources`
- `submit_rules`

它不能读取 head/worktree 中被当前变更修改后的规则，也不能访问代码写入或命令执行能力。

### 6.2 Review Agent

职责是针对已选中的规则读取 diff、相关代码和已有检查结果，然后提交结构化审查结论。

第一阶段工具：

- `changed_files`
- `read_diff`
- `read_repository_file`
- `submit_assessments`

后续扩展：

- `grep_repository`
- `glob_repository`
- `rules`
- `check_results`

审查按规则批次创建独立 Agent，通过独立对话历史隔离上下文。第一版不启用父子 Agent。

## 7. 四态判定

每条适用规则只能得到以下状态之一：

- `PASS`：存在可复核的正向证据证明规则已满足。
- `FAIL`：规则适用，并存在直接、明确、可定位的违反证据。
- `WARN`：存在具体风险信号，但证据不足以证明违反。
- `UNVERIFIED`：缺少必要输入、能力、上下文或确定性检查结果。

缺少通过证据不能自动判定为 `FAIL`。模型也不能创建第五种状态或以置信度分数代替证据。

每条结论必须包含：

- 规则原文和来源；
- 涉及的代码路径及位置；
- 判断依据；
- 使用的 evidence handles；
- 建议的下一步；
- 已知限制。

## 8. 证据与确定性校验

规范文档由确定性代码切分为带稳定 ID 的 source spans。模型只能引用已有 span ID，报告中的规则原文、路径和行号由系统回填。

代码、diff 和检查结果同样通过 evidence handle 暴露。模型提交结论后，Validator 必须重新验证：

- `rule_id` 是否存在；
- 规则引用是否准确；
- evidence handle 是否真实存在；
- 路径、revision 和行号是否有效；
- `PASS` 是否包含正向证据；
- `FAIL` 是否包含直接违反证据；
- 是否提供判断依据和下一步。

不满足要求的 `PASS` 或 `FAIL` 不得保留，应降级为 `UNVERIFIED` 并说明校验失败原因。

JSON `AuditReport` 是唯一事实来源，Markdown 必须由经过校验的 JSON 渲染，不能直接采用模型生成的 Markdown。

## 9. 安全边界

所有模型可调用的读取工具只能接受仓库相对路径，并拒绝：

- 绝对路径；
- `..` 路径穿越；
- NUL 字符；
- 解析后逃出仓库的符号链接；
- 超过限制的文件和输出；
- 子模块内部内容；
- 未允许的 revision。

Git 操作使用固定参数数组和 `subprocess`，禁止 `shell=True`，并关闭 external diff 和 textconv，避免仓库配置间接执行命令。

仓库文档、代码、注释和 diff 都作为不可信证据数据处理，不能覆盖 RepoWitness 的控制提示词。

## 10. 第一阶段 Vertical Slice

第一阶段实现：

1. 将 `corecoder/` 重命名为 `repowitness/`；
2. 更新包名、命令入口、import 和产品元数据；
3. 为 Agent 增加可注入 system prompt；
4. 保留父子 Agent 和四个闲置工具源码，但不注册；
5. 建立 `AuditRequest`、`Rule`、`Evidence`、`Assessment`、`AuditReport`；
6. 实现只读 `RepositoryView`；
7. 支持 base revision 根目录 `AGENTS.md`；
8. 实现 Contract Compiler Agent；
9. 实现 Review Agent；
10. 实现结构化 Collector 和后置 Validator；
11. 实现 canonical JSON 与 Markdown renderer；
12. 跑通：

```bash
repowitness audit --base main
```

第一阶段暂不实现 GitHub Action、JUnit/SARIF、多层级 `AGENTS.md`、ADR 自动发现、YAML 配置和 Required Check。

## 11. 第一阶段验收标准

- CoreCoder 原有 Agent loop 相关行为继续通过测试；
- 四个闲置工具源码存在，但不会出现在 RepoWitness Agent schema 中；
- 审查过程不修改工作区、index、commit 或 refs；
- 模型不能读取仓库外文件；
- 当前变更修改 `AGENTS.md` 时仍按 base 规则审查；
- 规则引用能映射回准确路径和行号；
- 四态结论只能通过 `submit_assessments` 提交；
- 无效引用会被 Validator 降级；
- JSON 和 Markdown 来自同一份 `AuditReport`；
- advisory mode 下审查报告包含 `FAIL` 时仍正常退出；
- 全量测试和静态检查通过。
