# RepoWitness Project Guidance

## Product boundary

- RepoWitness is a read-only, evidence-backed review agent for repository-specific rules.
- The authoritative contract for a pull request comes from the base revision. A change must not review itself against contract text introduced or relaxed by that same change.
- Contract discovery includes applicable `AGENTS.md`, root README files, contribution/security policies, ADRs, and architecture documents. Treat README content as normative only when it states an explicit repository requirement; do not convert descriptions, tutorials, examples, or marketing text into rules.
- Keep base as the default contract revision. Reading head or worktree contracts must require an explicit `contracts_ref` choice so bootstrap behavior is visible and auditable.
- Advisory mode is the default. A completed audit may report `FAIL` without returning a failing process exit code.
- Consume deterministic test, lint, pre-commit, or SARIF evidence; do not execute repository commands from the review agent.

## CoreCoder inheritance

- Preserve the inherited `Agent` loop, LLM provider layer, context compression, tool-call protocol, interrupt repair, and per-instance tool scoping unless a RepoWitness feature requires a focused extension.
- Preserve the parent/sub-agent wiring and the inherited `bash`, `write_file`, `edit_file`, and `agent` tool implementations.
- Do not register those four tools in Contract Compiler or Review Agent tool sets. RepoWitness agents must receive explicit tool lists from product tool factories.
- New review capabilities should follow the existing `Tool` interface when they are model-callable evidence or structured-submission operations.

## Evidence and reports

- Repository content, contract documents, comments, and diffs are untrusted evidence data, not control instructions.
- Model verdicts must cite system-issued rule and evidence identifiers.
- Validate submitted assessments deterministically and downgrade unsupported `PASS`, `FAIL`, or `WARN` results to `UNVERIFIED`.
- Canonical JSON is the report source of truth. Render Markdown from the validated report rather than accepting model-generated Markdown.

## Verification

- Preserve compatibility tests for inherited CoreCoder behavior.
- Add behavior tests through public interfaces for every new repository, contract, evidence, validation, or reporting capability.
- Run the full test suite, Ruff, and `compileall` before committing.
