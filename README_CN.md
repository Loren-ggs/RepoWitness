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

- 仓库规范文档；
- 本次 Git diff；
- 相关仓库代码；
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

## 当前第一阶段能力

`0.1.0` 当前已经支持：

- `repowitness audit --base <ref>`；
- 从 base revision 读取根目录 `AGENTS.md`；
- 审查已提交、暂存、未暂存和未跟踪的工作区变更；
- Contract Compiler Agent 与 Review Agent；
- 受仓库路径约束的 diff 和文件读取工具；
- canonical JSON 和 Markdown 报告；
- advisory 退出语义。

暂未实现：

- GitHub Actions 发布；
- 多层级 `AGENTS.md`、`CONTRIBUTING.md` 和 ADR 自动发现；
- JUnit、SARIF 和检查结果导入；
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
