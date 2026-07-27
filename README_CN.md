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

每条结论都包含规则原文与来源、证据 handle、判断依据和下一步建议。

## 只读是能力边界

RepoWitness Agent 必须显式获得工具。正式审查路径不注册 Bash、文件写入、
文件编辑或子 Agent 工具。

审查过程不会：

- 修改、暂存、提交或推送仓库文件；
- 执行测试、Lint、pre-commit 或任意命令；
- 自动修复问题；
- 在当前建议模式中阻止 PR 合并。

继承自 CoreCoder 的相关工具源码仍然保留，供未来显式扩展，但不会进入
RepoWitness 审查 Agent。

## 当前能力

`0.2.0` 当前已经支持：

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
- canonical JSON 和 Markdown 报告；
- GitHub composite Action，在 Job Summary 发布 Markdown 报告；
- advisory 退出语义。

暂未实现：

- JUnit、SARIF 原生解析（当前可转换为标准 check-result JSON）；
- YAML 配置；
- Required Check 或 `--fail-on`。

## 安装

```bash
git clone https://github.com/Loren-ggs/RepoWitness.git
cd RepoWitness
python -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

配置一个 OpenAI 兼容模型：

```bash
export REPOWITNESS_API_KEY=sk-...
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

标准结果文件格式：

```json
{
  "schema_version": "1",
  "snapshot": "<repowitness snapshot 的输出>",
  "checks": [
    {
      "name": "pytest",
      "status": "pass",
      "summary": "106 tests passed"
    }
  ]
}
```

## GitHub Actions

调用仓库中的 composite Action；checkout 必须保留 base 历史：

```yaml
steps:
  - uses: actions/checkout@v6
    with:
      fetch-depth: 0
  - uses: Loren-ggs/RepoWitness@v0.2.0
    with:
      base: ${{ github.event.pull_request.base.sha }}
    env:
      REPOWITNESS_API_KEY: ${{ secrets.REPOWITNESS_API_KEY }}
```

报告写入 GitHub Job Summary。当前仍是建议模式，不会因为审查结论为 `FAIL`
而阻止合并。

当前版本为建议模式。即使报告包含 `FAIL`，只要审查完整执行，退出码仍为
`0`；仓库、配置、模型或报告生成错误使用非零退出码。

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

CLI 与未来的 GitHub Actions 都调用同一个 `AuditEngine`。

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
