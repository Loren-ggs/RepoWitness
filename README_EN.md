# RepoWitness

**Evidence-backed review against your repository's own rules.**

RepoWitness is a read-only repository contract review agent built on the
CoreCoder agent structure. It reviews the current Git change against explicit
rules already written in the repository, instead of applying generic AI code
review advice.

[中文首页](README.md) · [Product strategy](docs/product-strategy_CN.md) ·
[CoreCoder architecture articles](article/00-index_EN.md)

## What it reviews

RepoWitness combines:

- repository contracts including `AGENTS.md`, `CLAUDE.md`, README files,
  contribution and security policies, ADRs, and architecture documents;
- the current Git diff;
- related repository files;
- optional external check results bound to the exact audit snapshot;
- evidence returned by read-only review tools.

Every applicable rule must have a traceable result. RepoWitness asks the
Review Agent to repair incomplete submissions and explicitly marks any rule
that remains uncovered as `UNVERIFIED` instead of silently omitting it.

Every evaluated rule receives one verdict:

- `PASS`: positive evidence proves compliance;
- `FAIL`: direct evidence proves a violation;
- `WARN`: a concrete risk exists but evidence is insufficient for failure;
- `UNVERIFIED`: required evidence or capability is unavailable.

Every assessment includes a Chinese rule statement, the original source
location, evidence handles, rationale, and a next step. Canonical JSON also
retains the exact source quote.

## Read-only by capability

RepoWitness agents receive explicit tool sets. The normal audit path does not
register Bash, file writing, file editing, or sub-agent tools.

The audit does not:

- modify, stage, commit, or push repository files;
- execute tests, linters, pre-commit, or arbitrary commands;
- generate automatic fixes;
- block a pull request unless the caller explicitly enables `--fail-on`.

Inherited CoreCoder implementations remain in the source tree for future
explicit use, but they are not registered in RepoWitness review agents.

## Current capabilities

Version `0.4.1` currently supports:

- `repowitness audit --base <ref>`;
- base contracts by default, with explicit `head` and `worktree` bootstrap modes;
- priority inclusion of root and scoped `AGENTS.md` and `CLAUDE.md`, plus root
  `CONTRIBUTING.md` and `SECURITY.md`;
- model selection from root README and documentation candidates, bounded to
  12 files and 150 KB of contract text;
- normative-only README and documentation extraction guidance;
- deterministic source scope, rule glob, and priority filtering;
- separate contract-change and explicit conflict reporting;
- complete assessment coverage with batched submissions, one focused repair
  pass, and explicit `UNVERIFIED` results for rules that remain uncovered;
- early rejection of unknown evidence handles while preserving final
  fail-closed validation;
- tracked, staged, unstaged, and untracked worktree changes;
- a Contract Compiler Agent and a Review Agent using the same reused agent loop;
- repository-confined diff, read, glob, and grep tools;
- snapshot-bound standard check-result JSON ingestion;
- snapshot-bound native JUnit XML and SARIF 2.1.0 ingestion;
- strict `.repowitness.yml` configuration with CLI overrides;
- canonical JSON and Markdown reports;
- Markdown finding headings that surface the cited code path and line while
  keeping the rule identifier below the evidence list;
- a composite GitHub Action that publishes to the Job Summary and can update
  one marker-bound PR comment;
- advisory exit behavior by default, with opt-in `--fail-on` enforcement.

## Install

Install the published CLI from PyPI:

```bash
python -m pip install repowitness
export REPOWITNESS_API_KEY=sk-...
```

Then audit any target repository:

```bash
cd /path/to/repository
repowitness audit --base main
```

Clone the source only when developing RepoWitness itself:

```bash
git clone https://github.com/Loren-ggs/RepoWitness.git
cd RepoWitness
python -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

Configure another OpenAI-compatible model only when needed:

```bash
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

Repository configuration is discovered at `.repowitness.yml`:

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

Supported audit keys are `base`, `contracts-ref`, `format`, `output`,
`include-untracked`, `check-results`, `junit`, `sarif`,
`evidence-snapshot`, and `fail-on`. Paths in the file are relative to the
configuration file. Explicit CLI options override the matching YAML values.
Model credentials remain environment-only.

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

JUnit and SARIF do not carry RepoWitness provenance themselves. Capture the
snapshot before running the external tool, then provide it explicitly:

```bash
snapshot="$(repowitness snapshot)"
pytest --junitxml junit.xml
repowitness audit \
  --base main \
  --junit junit.xml \
  --sarif results.sarif \
  --evidence-snapshot "${snapshot}"
```

RepoWitness parses the files but still does not execute the test or analyzer.
Missing or mismatched provenance rejects the native results.

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

For the shortest setup, create a `REPOWITNESS_API_KEY` repository Secret and
call the reusable workflow:

```yaml
name: RepoWitness

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  repowitness:
    uses: Loren-ggs/RepoWitness/.github/workflows/repowitness.yml@v0.4.1
    with:
      fail_on: fail
    secrets:
      api_key: ${{ secrets.REPOWITNESS_API_KEY }}
```

This recommended configuration turns the `repowitness / repowitness` check
red when the report contains `FAIL`. Add that check as a required status check
in the target branch ruleset when it must block merging.

The Secret alone is sufficient for the default OpenAI configuration. An API
key cannot identify or route to another OpenAI-compatible service by itself.
For DeepSeek or another compatible endpoint, also create these non-sensitive
repository Variables under `Settings → Secrets and variables → Actions`:

```text
REPOWITNESS_MODEL = deepseek-v4-flash
REPOWITNESS_BASE_URL = https://api.deepseek.com
```

Use the model and base URL supplied by your provider. The reusable workflow
automatically exposes the caller repository's Variables as
`REPOWITNESS_MODEL` and `REPOWITNESS_BASE_URL`. Undefined Variables remain
empty and RepoWitness falls back to its default OpenAI configuration.

The workflow checks out full history, selects the PR base SHA, runs the audit,
writes the Job Summary, creates or updates the PR comment, and uploads the
`repowitness-report` artifact. Calls triggered by a manual caller use the
repository default branch. PR comments default on; pass `comment: false` to
disable them.

Call the composite Action directly when importing custom check results:

```yaml
steps:
  - uses: actions/checkout@v6
    with:
      fetch-depth: 0
  - uses: Loren-ggs/RepoWitness@v0.4.1
    env:
      REPOWITNESS_MODEL: ${{ vars.REPOWITNESS_MODEL }}
      REPOWITNESS_BASE_URL: ${{ vars.REPOWITNESS_BASE_URL }}
    with:
      api-key: ${{ secrets.REPOWITNESS_API_KEY }}
      check-results: ${{ runner.temp }}/repowitness-check-results.json
      fail-on: fail
```

`base`, `comment`, and `github-token` are optional. The Action selects the PR
base SHA or default branch, updates the PR comment by default, and uses the
current `github.token`. Existing `REPOWITNESS_API_KEY` environment-variable
calls remain supported. Commenting requires `pull-requests: write`.

Generate the standard JSON after running deterministic checks and bind it to
the output of `repowitness snapshot` captured before those checks. The
`check-results` input also accepts multiple paths, one per line. Snapshot
mismatches are reported and the results are not imported. See
[the repository's PR workflow](.github/workflows/repowitness-pr.yml) for a
complete pytest, Ruff, and `compileall` collection example that preserves
failed checks as evidence while the audit remains advisory.

The Markdown report is appended to the GitHub Job Summary. The full report
remains the artifact if a comment must be truncated.

The CLI and Action metadata remain advisory by default for backward
compatibility, while the recommended PR workflow above opts into
`fail_on: fail`. Use repeatable `--fail-on fail|warn|unverified`, or the
Action's newline-separated `fail-on` input, to return non-zero for selected
verdicts. Configure `repowitness / repowitness` as a required status check when
it should block merges. Repository, configuration, model, or report generation
errors are always non-zero.

After changing a caller workflow, do not only re-run an old workflow run. The
old run continues to use the workflow from its original base commit. Update the
PR branch, reopen the PR, or create a new PR, then verify that the new run lists
`fail_on: fail` in its Inputs.

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
