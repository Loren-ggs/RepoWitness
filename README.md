<div align="center">
  <h1>🧾 RepoWitness（仓证）</h1>
  <p><strong>让每一次代码变更，都对仓库自己写下的规则负责。</strong></p>
  <p>
    RepoWitness 会读取项目文档中的明确要求，结合本次 Git diff 和可验证证据，
    给出可追溯的 <code>PASS</code> / <code>FAIL</code> / <code>WARN</code> / <code>UNVERIFIED</code> 审核结果。
  </p>
  <p>
    <a href="https://github.com/marketplace/actions/repowitness-advisory-audit">GitHub Marketplace</a>
    ·
    <a href="https://pypi.org/project/repowitness/">PyPI</a>
    ·
    <a href="README_EN.md">English</a>
    ·
    <a href="docs/product-strategy_CN.md">产品策略</a>
  </p>
  <p>
    <img alt="PyPI version" src="https://img.shields.io/pypi/v/repowitness?label=PyPI">
    <img alt="Python versions" src="https://img.shields.io/pypi/pyversions/repowitness">
    <img alt="License" src="https://img.shields.io/github/license/Loren-ggs/RepoWitness">
    <img alt="RepoWitness checks" src="https://github.com/Loren-ggs/RepoWitness/actions/workflows/repowitness-pr.yml/badge.svg">
  </p>
</div>

> **一句话理解：** 测试检查“代码能不能运行”，RepoWitness 检查“这次修改有没有遵守项目文档里已经写明的约定”。

RepoWitness 是一个只读、证据驱动的仓库契约审核 Agent。它不会给出泛化的
“AI Code Review 建议”，而是专门审核当前改动是否符合这个仓库自己的
`AGENTS.md`、README、贡献规范、安全策略、ADR 和架构文档。

## 🔍 What it reviews｜它审核什么

RepoWitness 关注的是传统 CI 很难直接表达的**文字契约**：

- “API 层不能直接访问数据库”；
- “高风险写操作必须先预览并由用户确认”；
- “新增公共接口必须提供兼容性测试”；
- “审查 Agent 不得执行仓库命令或修改文件”。

它把四类信息放在同一个审核上下文中：

1. **项目规则**：base revision 中明确写下的规范性要求；
2. **本次改动**：已提交、暂存、未暂存及可选的未跟踪文件；
3. **相关代码**：只读工具找到的文件、diff、glob 和 grep 证据；
4. **同期 CI 结果**：与本次 Snapshot 严格绑定的 pytest、Ruff、JUnit、
   SARIF 等确定性证据。

| 工具 | 最擅长回答的问题 | RepoWitness 如何配合 |
| --- | --- | --- |
| pytest / 单元测试 | 行为是否符合可执行断言？ | 读取结果作为确定性证据，不重复执行测试 |
| Ruff / Lint / 编译 | 代码是否满足静态规则、能否编译？ | 导入同期结果，不替代现有 CI |
| 安全扫描 / SARIF | 是否命中已知静态风险？ | 将命中位置关联到适用的仓库规则 |
| **RepoWitness** | **改动是否遵守项目文档中的文字要求？** | 汇总规则、diff 与外部证据，给出可追溯结论 |

因此 RepoWitness 是现有 CI 的**补充层**，不会与测试、Lint、构建或安全扫描
冲突。它不会偷偷再跑一遍这些命令；外部检查结果只有与同一 Snapshot 匹配时
才会被采信。

## ⚡ 60 秒接入

### 方式一：GitHub Actions（推荐）

#### 1. 配置 API Key

在目标仓库打开：

`Settings → Secrets and variables → Actions → New repository secret`

创建：

```text
Name:  REPOWITNESS_API_KEY
Value: 你的 OpenAI 或 OpenAI-compatible API Key
```

Secret 不会写进 workflow、日志或报告。默认模型为 `gpt-5.5`；如使用其他
OpenAI-compatible 服务，可在本地通过环境变量设置模型和 Base URL。

#### 2. 添加完整 workflow

在目标仓库新建 `.github/workflows/repowitness.yml`，完整粘贴以下内容：

```yaml
name: RepoWitness

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  audit:
    uses: Loren-ggs/RepoWitness/.github/workflows/repowitness.yml@v0.3.0
    secrets:
      api_key: ${{ secrets.REPOWITNESS_API_KEY }}
```

提交后，新建或更新 PR 即会自动：

- 选择 PR 的 base commit；
- 审核本次改动；
- 写入 GitHub Job Summary；
- 创建或更新同一条 PR 评论；
- 上传 `repowitness-report` artifact。

> 💡 **从 Marketplace 安装时为什么编辑器会“全红”？**
>
> GitHub Marketplace 自动生成的是一个 `steps` 片段，不是完整 workflow。
> 它不能直接作为 `.github/workflows/*.yml` 的顶层内容，必须放在
> `jobs.<job>.steps` 下面。新项目直接复制上面的完整 workflow 最简单；
> 已有 workflow 时，再把 Marketplace 片段放进已有 job 的 `steps`。

已有 workflow 的写法如下：

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0

      - uses: Loren-ggs/RepoWitness@v0.3.0
        with:
          api-key: ${{ secrets.REPOWITNESS_API_KEY }}
```

`base`、`contracts-ref`、`output`、`python-version`、`comment` 等可选字段都
可以删除或留空；v0.3.0 会恢复安全默认值。Marketplace 无法替你创建或读取
第三方模型密钥，所以 `REPOWITNESS_API_KEY` 仍需在目标仓库配置一次。

#### 3. 确保仓库中有可审核的文字规则

RepoWitness 会自动发现已有文档。若项目还没有明确规则，可以从根目录
`AGENTS.md` 开始：

```markdown
# Repository rules

- 所有公共 API 变更必须提供回归测试。
- 数据库迁移必须保持向后兼容，并说明回滚方式。
- PR 中不得提交密钥、Token 或真实用户数据。
```

默认从 base revision 读取规则，避免一次修改先放宽规则，再按放宽后的文本
审核自己。

### 方式二：本地一行运行

先在目标仓库根目录创建不会提交的 `.env`：

```dotenv
REPOWITNESS_API_KEY=sk-...
```

然后一行安装并审核：

```bash
python -m pip install -q repowitness==0.3.0 && repowitness audit --base main
```

已经安装后，日常只需：

```bash
repowitness audit --base main
```

如果远端基准分支更准确，可使用 `--base origin/main`。报告默认输出到终端，
也可以写入文件：

```bash
repowitness audit --base origin/main --format markdown --output repowitness-report.md
```

## 🧭 审核结果怎么看

每条适用规则只会得到一种结论：

| 结论 | 含义 |
| --- | --- |
| `PASS` | 有正向证据证明本次改动符合规则 |
| `FAIL` | 有直接证据证明本次改动违反规则 |
| `WARN` | 存在具体风险，但证据不足以判定失败 |
| `UNVERIFIED` | 缺少必要证据，或当前能力无法可靠验证 |

每条结论包含：

- 中文规则表述与规范原文位置；
- 系统签发的 rule/evidence handle；
- 判断依据；
- 下一步建议。

Canonical JSON 是报告事实源；Markdown 和 PR 评论都从已校验的 JSON 渲染，
而不是直接接受模型生成的最终报告。

## 🧰 常用配置

### 用 `.repowitness.yml` 固化团队配置

```yaml
version: 1
audit:
  base: main
  contracts-ref: base
  format: markdown
  output: repowitness-report.md
  include-untracked: true
  fail-on:
    - fail
```

支持的配置项：

`base`、`contracts-ref`、`format`、`output`、`include-untracked`、
`check-results`、`junit`、`sarif`、`evidence-snapshot`、`fail-on`。

显式 CLI 参数会覆盖 YAML；模型凭据只从环境变量读取，不进入配置文件。

### 导入 pytest、Ruff 或其他确定性检查

先在执行外部检查前记录当前 Snapshot：

```bash
snapshot="$(repowitness snapshot)"
pytest --junitxml junit.xml
repowitness audit \
  --base main \
  --junit junit.xml \
  --sarif results.sarif \
  --evidence-snapshot "${snapshot}"
```

RepoWitness 只解析 JUnit XML、SARIF 2.1.0 或标准 check-result JSON，不会自己
执行测试或分析命令。Snapshot 缺失或不匹配时，结果会被拒绝导入并记录原因。

标准 check-result JSON：

```json
{
  "schema_version": "1",
  "snapshot": "<repowitness snapshot 的输出>",
  "checks": [
    {
      "name": "pytest",
      "status": "pass",
      "summary": "全部测试通过"
    },
    {
      "name": "ruff",
      "status": "pass",
      "summary": "Ruff 执行成功"
    }
  ]
}
```

完整的 pytest、Ruff、`compileall` 采集示例见
[项目自身的 PR workflow](.github/workflows/repowitness-pr.yml)。

### 需要时才阻止合并

默认是 advisory 模式：报告出现 `FAIL`，完整审核仍返回退出码 `0`。

本地显式启用：

```bash
repowitness audit --base main --fail-on fail
```

Action 中启用：

```yaml
with:
  api-key: ${{ secrets.REPOWITNESS_API_KEY }}
  fail-on: fail
```

再把对应 workflow job 配置为 GitHub Required Check，即可让指定结论阻止合并。
仓库、配置、模型调用或报告生成错误始终返回非零。

### 首次引入规则

若 base 中还没有规范文档，可显式使用当前工作区规则进行一次 bootstrap：

```bash
repowitness audit --base main --contracts-ref worktree
```

`worktree` 不会成为默认值，这个选择会明确记录在报告中。

## 🧱 它如何工作

```text
base 中的项目文档 ─┐
当前 Git diff ─────┼─→ Contract Compiler → Review Agent → 确定性校验 → JSON / Markdown
只读代码证据 ─────┤
Snapshot 绑定的 CI ┘
```

CLI、composite Action 和 reusable workflow 最终都调用同一个 `AuditEngine`。
RepoWitness 复用 CoreCoder 的 Agent loop、LLM provider、Tool 协议、并行执行、
中断回填和上下文压缩，并在外层增加 Git Snapshot、契约、证据校验与报告模块。

## ✨ Current capabilities｜v0.3.0 当前能力

- 自动发现根目录及适用子目录的 `AGENTS.md`、根 README、
  `CONTRIBUTING.md`、`SECURITY.md`、ADR 和架构 Markdown；
- README 只提取明确的规范性要求，不把介绍、教程或营销文案当成规则；
- 默认使用 base contracts，并支持显式 `head` / `worktree` bootstrap；
- 审核已提交、暂存、未暂存和可选的未跟踪文件；
- 按嵌套目录作用域、规则 glob 和来源优先级筛选适用规则；
- 单独报告规范文档变更和模型识别出的显式规范冲突；
- 使用受仓库路径约束的 diff、read、glob、grep 只读工具；
- 导入 Snapshot 绑定的 check-result JSON、JUnit XML 和 SARIF 2.1.0；
- 严格校验 `.repowitness.yml`，并允许 CLI 覆盖；
- 输出 canonical JSON、Markdown、Job Summary、PR 评论和 artifact；
- 默认 advisory，并支持 `--fail-on fail|warn|unverified`；
- 提供 PyPI CLI、GitHub composite Action 和 reusable workflow。

## 🔒 Read-only by capability｜只读能力边界

RepoWitness 不是靠提示词要求模型“不要修改”，而是根本不向正式审核 Agent
注册 Bash、文件写入、文件编辑或子 Agent 工具。

它不会：

- 修改、暂存、提交或推送仓库文件；
- 执行测试、Lint、pre-commit 或任意仓库命令；
- 自动修复代码；
- 在未显式启用 `--fail-on` 时阻止 PR。

需要注意的边界：

- 模型仍需读取与审核相关的文档、diff 和代码片段；敏感仓库应选择符合组织
  数据策略的模型服务；
- Fork PR 默认无法访问目标仓库 Secret，可复用 workflow 会跳过不受信任的
  fork 上下文，避免向外部代码暴露 API Key；
- `UNVERIFIED` 不是系统故障，它表示现有证据不足以支持更强结论；
- RepoWitness 不替代代码测试、安全扫描、人工架构评审或发布审批。

## 🧑‍💻 开发 RepoWitness

只有参与本项目开发时才需要克隆源码：

```bash
git clone https://github.com/Loren-ggs/RepoWitness.git
cd RepoWitness
python -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

完整验证：

```bash
./.venv/bin/python -m pytest tests/ -q
./.venv/bin/python -m ruff check repowitness tests
./.venv/bin/python -m compileall -q repowitness tests
```

OpenAI-compatible 模型配置：

```bash
export REPOWITNESS_MODEL=gpt-5.5
export REPOWITNESS_BASE_URL=https://api.example.com/v1
export REPOWITNESS_API_KEY=sk-...
```

继承的 LiteLLM provider 仍可按需安装：

```bash
./.venv/bin/pip install -e ".[litellm]"
export REPOWITNESS_PROVIDER=litellm
```

## 📜 来源与 License

RepoWitness 基于
[he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder)
二次开发，并继续使用 MIT License。详见 [NOTICE](NOTICE) 和
[LICENSE](LICENSE)。
