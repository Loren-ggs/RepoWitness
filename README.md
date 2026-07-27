# RepoWitness

**Evidence-backed review against your repository's own rules.**

RepoWitness is a read-only repository contract review agent built on the
CoreCoder agent structure. It reviews the current Git change against explicit
rules already written in the repository, instead of applying generic AI code
review advice.

[中文说明](README_CN.md) · [Product strategy](docs/product-strategy_CN.md) ·
[CoreCoder architecture articles](article/00-index_EN.md)

## What it reviews

RepoWitness combines:

- authoritative repository contract documents;
- the current Git diff;
- related repository files;
- evidence returned by read-only review tools.

Every evaluated rule receives one verdict:

- `PASS`: positive evidence proves compliance;
- `FAIL`: direct evidence proves a violation;
- `WARN`: a concrete risk exists but evidence is insufficient for failure;
- `UNVERIFIED`: required evidence or capability is unavailable.

Every assessment includes the exact rule quote and source location, evidence
handles, rationale, and a next step.

## Read-only by capability

RepoWitness agents receive explicit tool sets. The normal audit path does not
register Bash, file writing, file editing, or sub-agent tools.

The audit does not:

- modify, stage, commit, or push repository files;
- execute tests, linters, pre-commit, or arbitrary commands;
- generate automatic fixes;
- block a pull request in the current advisory release.

Inherited CoreCoder implementations remain in the source tree for future
explicit use, but they are not registered in RepoWitness audit agents.

## Current vertical slice

Version `0.1.0` currently supports:

- `repowitness audit --base <ref>`;
- authoritative root `AGENTS.md` rules read from the base revision;
- tracked, staged, unstaged, and untracked worktree changes;
- a Contract Compiler Agent and a Review Agent using the same reused agent loop;
- repository-confined diff and file-reading tools;
- canonical JSON and Markdown reports;
- advisory exit behavior.

Not implemented yet:

- GitHub Actions publishing;
- nested `AGENTS.md`, `CONTRIBUTING.md`, and ADR discovery;
- JUnit/SARIF/check-result ingestion;
- YAML configuration;
- required-check or `--fail-on` behavior.

## Install

```bash
git clone https://github.com/Loren-ggs/RepoWitness.git
cd RepoWitness
python -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

Configure an OpenAI-compatible model:

```bash
export REPOWITNESS_API_KEY=sk-...
export REPOWITNESS_MODEL=gpt-5.5

# Optional custom endpoint
export REPOWITNESS_BASE_URL=https://api.example.com/v1
```

LiteLLM remains available through the inherited provider layer:

```bash
./.venv/bin/pip install -e ".[litellm]"
export REPOWITNESS_PROVIDER=litellm
```

## Use

Markdown to stdout:

```bash
repowitness audit --base main
```

JSON to stdout:

```bash
repowitness audit --base main --format json
```

Explicit report file:

```bash
repowitness audit --base main --format markdown --output report.md
```

The default target is the current worktree. Rules always come from the resolved
base commit, so a change cannot relax `AGENTS.md` and then review itself against
the relaxed text.

The current release is advisory. A completed audit returns exit code `0` even
when the report contains `FAIL`; repository, configuration, model, or report
generation errors return a non-zero code.

## Architecture

The core external seam is:

```python
from pathlib import Path

from repowitness import AuditEngine, AuditRequest, LLM

llm = LLM(model="...", api_key="...")
report = AuditEngine(llm).audit(
    AuditRequest(repository_path=Path("."), base_ref="main")
)
```

Both frontends and future GitHub integration use this same `AuditEngine`.
CoreCoder's agent loop, provider layer, tool protocol, parallel execution,
interrupt repair, and context compression are reused. RepoWitness adds the
Git snapshot, contract, evidence, validation, and reporting modules around that
loop.

See [docs/product-strategy_CN.md](docs/product-strategy_CN.md) for the approved
product boundaries and implementation sequence.

## Development

```bash
./.venv/bin/python -m pytest tests/ -q
python3 -m ruff check repowitness tests
./.venv/bin/python -m compileall -q repowitness
```

## Attribution and license

RepoWitness is derived from
[he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder) and retains its
MIT license. See [NOTICE](NOTICE) and [LICENSE](LICENSE).
