# RepoWitness（仓证）

**让每次代码变更都对仓库自己的规则负责。**

英文标语：

> Evidence-backed review against your repository’s own rules.

RepoWitness 是一个基于 CoreCoder Agent 结构二次开发的只读仓库契约审查
Agent。它根据仓库已经明确写下的规则审查本次 Git 变更，而不是套用泛化的
AI 代码评审建议。

[English](README.md) ·
[产品策略与实施边界](docs/product-strategy_CN.md) ·
[CoreCoder 架构文章](article/00-index.md)

## 它检查什么

RepoWitness 综合以下输入：

- 仓库规范文档，包括 `AGENTS.md`、README、贡献/安全策略和 ADR/架构文档；
- 本次 Git diff；
- 相关仓库代码；
- 可选的、与当前 snapshot 绑定的外部检查结果；
- 只读取证工具返回的证据。

每条适用规则只能得到一种结论：

- `PASS`：有正向证据证明符合；
- `FAIL`：有直接证据证明违反；
- `WARN`：存在具体风险，但不足以判定失败；
- `UNVERIFIED`：缺少必要证据或当前能力无法验证。

每条结论都包含中文规则表述与原文来源、证据 handle、判断依据和下一步建议；
canonical JSON 同时保留规范原文。

## 只读是能力边界

RepoWitness Agent 必须显式获得工具。正式审查路径不注册 Bash、文件写入、
文件编辑或子 Agent 工具。

审查过程不会：

- 修改、暂存、提交或推送仓库文件；
- 执行测试、Lint、pre-commit 或任意命令；
- 自动修复问题；
- 阻止 PR 合并，除非调用方显式启用 `--fail-on`。

继承自 CoreCoder 的相关工具源码仍然保留，供未来显式扩展，但不会进入
RepoWitness 审查 Agent。

## 当前能力

`0.3.0` 当前已经支持：

- `repowitness audit --base <ref>`；
- 默认从 base revision 读取仓库规范，并可显式选择 `head`/`worktree`；
- 自动发现根及适用目录的 `AGENTS.md`、根 README、`CONTRIBUTING.md`、
  `SECURITY.md`、ADR 和架构 Markdown；
- README 仅提取明确的规范性要求，不把产品介绍或教程当成规则；
- 按嵌套目录作用域、规则 glob 和来源优先级筛选适用规则；
- 单独报告本次规范文档变更和模型识别出的显式规范冲突；
- 审查已提交、暂存、未暂存和未跟踪的工作区变更；
- Contract Compiler Agent 与 Review Agent；
- 受仓库路径约束的 diff、文件读取、glob 和 grep 工具；
- 导入与 snapshot 严格匹配的标准 check-result JSON；
- 导入与 snapshot 严格绑定的 JUnit XML 和 SARIF 2.1.0；
- 严格校验的 `.repowitness.yml` 配置及 CLI 覆盖；
- canonical JSON 和 Markdown 报告；
- GitHub composite Action，在 Job Summary 发布 Markdown 报告，并可更新一条
  带固定标记的 PR 评论；
- 默认 advisory、可显式启用 `--fail-on` 的退出语义。

## 安装

普通使用直接从 PyPI 安装：

```bash
python -m pip install repowitness
export REPOWITNESS_API_KEY=sk-...
```

然后进入任意目标仓库即可审查：

```bash
cd /path/to/repository
repowitness audit --base main
```

只有参与 RepoWitness 开发时才需要克隆源码：

```bash
git clone https://github.com/Loren-ggs/RepoWitness.git
cd RepoWitness
python -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

默认模型之外的 OpenAI 兼容模型可以额外配置：

```bash
export REPOWITNESS_MODEL=gpt-5.5

# 可选的自定义模型地址
export REPOWITNESS_BASE_URL=https://api.example.com/v1
```

底层继续保留 LiteLLM provider：

```bash
./.venv/bin/pip install -e ".[litellm]"
export REPOWITNESS_PROVIDER=litellm
```

## 使用

仓库根目录的 `.repowitness.yml` 会被自动发现：

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

支持的 audit 配置项包括 `base`、`contracts-ref`、`format`、`output`、
`include-untracked`、`check-results`、`junit`、`sarif`、
`evidence-snapshot` 和 `fail-on`。配置文件中的路径相对于配置文件目录；
显式 CLI 参数覆盖同名 YAML 配置。模型凭据仍只从环境变量读取。

输出 Markdown：

```bash
repowitness audit --base main
```

输出 JSON：

```bash
repowitness audit --base main --format json
```

写入显式指定的报告文件：

```bash
repowitness audit --base main --format markdown --output report.md
```

默认审查当前工作区，但规则始终来自解析后的 base commit，因此一次修改不能
先放宽 `AGENTS.md`，再按放宽后的文本审查自己。

仓库刚开始引入规范、base 中还不存在规范文档时，可以显式从当前工作区读取：

```bash
repowitness audit --base main --contracts-ref worktree
```

查看当前审查 snapshot：

```bash
repowitness snapshot
```

导入已有测试、Lint 或静态检查结果：

```bash
repowitness audit \
  --base main \
  --check-results .repowitness/pytest-result.json
```

JUnit 和 SARIF 本身不携带 RepoWitness snapshot。必须先记录 snapshot，再执行
外部检查并显式传入：

```bash
snapshot="$(repowitness snapshot)"
pytest --junitxml junit.xml
repowitness audit \
  --base main \
  --junit junit.xml \
  --sarif results.sarif \
  --evidence-snapshot "${snapshot}"
```

RepoWitness 只解析结果文件，仍不会执行测试或静态分析。缺少或不匹配的
snapshot 会导致原生结果被拒绝导入。

标准结果文件格式：

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
    },
    {
      "name": "compileall",
      "status": "pass",
      "summary": "Python 源码编译成功"
    }
  ]
}
```

## GitHub Actions

最简接入使用可复用 workflow。目标仓库只需创建
`REPOWITNESS_API_KEY` Secret，并添加：

```yaml
name: RepoWitness

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  audit:
    uses: Loren-ggs/RepoWitness/.github/workflows/repowitness.yml@v0
    secrets:
      api_key: ${{ secrets.REPOWITNESS_API_KEY }}
```

该 workflow 自动 checkout 全历史、选择 PR base SHA、运行审查、写入 Job
Summary、创建或更新 PR 评论，并上传 `repowitness-report` artifact。由手动
workflow 调用时自动使用仓库默认分支。PR 评论默认开启；传入
`comment: false` 可以关闭。

需要导入自定义检查结果时，可直接调用 composite Action：

```yaml
steps:
  - uses: actions/checkout@v6
    with:
      fetch-depth: 0
  - uses: Loren-ggs/RepoWitness@v0
    with:
      api-key: ${{ secrets.REPOWITNESS_API_KEY }}
      check-results: ${{ runner.temp }}/repowitness-check-results.json
      fail-on: fail
```

`base`、`comment` 和 `github-token` 都可省略：Action 会自动选择 PR base SHA
或默认分支，默认更新 PR 评论，并使用当前 `github.token`。旧的
`REPOWITNESS_API_KEY` 环境变量调用方式继续兼容。评论需要 workflow 授予
`pull-requests: write`。

确定性检查执行前先记录 `repowitness snapshot`，检查完成后把结果写成上述标准
JSON。`check-results` 也支持一行一个路径的多文件输入。Snapshot 不匹配时，
结果会被拒绝导入并写入报告问题列表。仓库自身的
[PR workflow](.github/workflows/repowitness-pr.yml) 提供了 pytest、Ruff 和
`compileall` 的完整采集示例：即使检查失败也保留结果作为证据，同时审查仍
保持 advisory。

报告写入 GitHub Job Summary。评论过长时会截断，完整报告仍保存在 artifact。

默认仍是建议模式：即使报告包含 `FAIL`，只要审查完整执行，退出码仍为 `0`。
可重复传入 `--fail-on fail|warn|unverified`，或使用 Action 的多行
`fail-on` 输入，让指定结论返回非零。若要阻止合并，再在 GitHub 分支保护中
把对应 workflow job 设为 Required Check。仓库、配置、模型或报告生成错误
始终使用非零退出码。

## 架构

统一对外接口是：

```python
from pathlib import Path

from repowitness import AuditEngine, AuditRequest, LLM

llm = LLM(model="...", api_key="...")
report = AuditEngine(llm).audit(
    AuditRequest(repository_path=Path("."), base_ref="main")
)
```

CLI 与 composite GitHub Action 都调用同一个 `AuditEngine`。

项目继续复用 CoreCoder 的 Agent loop、provider、Tool 协议、并行执行、
中断回填和上下文压缩；RepoWitness 在外层增加 Git 快照、契约、证据、
后置校验和报告模块。

完整策略见
[docs/product-strategy_CN.md](docs/product-strategy_CN.md)。

## 开发验证

```bash
./.venv/bin/python -m pytest tests/ -q
python3 -m ruff check repowitness tests
./.venv/bin/python -m compileall -q repowitness
```

## 来源与 License

RepoWitness 基于
[he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder)
二次开发，并继续使用 MIT License。详见 [NOTICE](NOTICE) 和
[LICENSE](LICENSE)。
