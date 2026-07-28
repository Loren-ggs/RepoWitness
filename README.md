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

- repository contracts including `AGENTS.md`, README files, contribution and
  security policies, ADRs, and architecture documents;
- the current Git diff;
- related repository files;
- optional external check results bound to the exact audit snapshot;
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

## Current capabilities

Version `0.2.0` currently supports:

- `repowitness audit --base <ref>`;
- base contracts by default, with explicit `head` and `worktree` bootstrap modes;
- root and scoped `AGENTS.md`, root README files, `CONTRIBUTING.md`,
  `SECURITY.md`, ADR, and architecture document discovery;
- normative-only README extraction guidance;
- deterministic source scope, rule glob, and priority filtering;
- separate contract-change and explicit conflict reporting;
- tracked, staged, unstaged, and untracked worktree changes;
- a Contract Compiler Agent and a Review Agent using the same reused agent loop;
- repository-confined diff, read, glob, and grep tools;
- snapshot-bound standard check-result JSON ingestion;
- canonical JSON and Markdown reports;
- a composite GitHub Action that publishes to the Job Summary;
- advisory exit behavior.

Not implemented yet:

- native JUnit and SARIF parsing (they can be converted to standard check JSON);
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

Bootstrap contracts that do not exist on base explicitly:

```bash
repowitness audit --base main --contracts-ref worktree
```

Print the current snapshot identity and import matching deterministic results:

```bash
repowitness snapshot
repowitness audit --base main --check-results .repowitness/pytest-result.json
```

The standard result envelope is:

```json
{
  "schema_version": "1",
  "snapshot": "<output of repowitness snapshot>",
  "checks": [
    {
      "name": "pytest",
      "status": "pass",
      "summary": "All tests passed"
    },
    {
      "name": "ruff",
      "status": "pass",
      "summary": "Ruff completed successfully"
    },
    {
      "name": "compileall",
      "status": "pass",
      "summary": "Python sources compiled successfully"
    }
  ]
}
```

## GitHub Actions

Use the composite action after a full-history checkout:

```yaml
steps:
  - uses: actions/checkout@v6
    with:
      fetch-depth: 0
  - uses: Loren-ggs/RepoWitness@v0.2.0
    with:
      base: ${{ github.event.pull_request.base.sha }}
      check-results: ${{ runner.temp }}/repowitness-check-results.json
    env:
      REPOWITNESS_API_KEY: ${{ secrets.REPOWITNESS_API_KEY }}
```

Generate the standard JSON after running deterministic checks and bind it to
the output of `repowitness snapshot` captured before those checks. The
`check-results` input also accepts multiple paths, one per line. Snapshot
mismatches are reported and the results are not imported. See
[the repository's PR workflow](.github/workflows/repowitness-pr.yml) for a
complete pytest, Ruff, and `compileall` collection example that preserves
failed checks as evidence while the audit remains advisory.

The Markdown report is appended to the GitHub Job Summary. The action remains
advisory and does not fail the job for a `FAIL` assessment.

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

Both the CLI and composite GitHub Action use this same `AuditEngine`.
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
