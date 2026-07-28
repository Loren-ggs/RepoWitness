"""RepoWitness command-line adapter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .audit import AuditEngine
from .config import Config, load_audit_config
from .domain import AuditRequest
from .llm import LLM, LiteLLM
from .reporting import render_json, render_markdown
from .repository import RepositoryView


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repowitness",
        description=("Evidence-backed review against your repository's own rules."),
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    audit = subcommands.add_parser(
        "audit",
        help="Audit current repository changes against base rules.",
    )
    audit.add_argument("--base", help="Base Git ref")
    audit.add_argument(
        "--contracts-ref",
        choices=("base", "head", "worktree"),
        default=None,
        help=(
            "Revision used to read repository contracts (default: base). "
            "Use worktree explicitly when bootstrapping new rules."
        ),
    )
    audit.add_argument(
        "--config",
        help="YAML configuration path (default: .repowitness.yml if present)",
    )
    audit.add_argument(
        "--repository",
        default=".",
        help="Repository path (default: current directory)",
    )
    audit.add_argument(
        "--format",
        choices=("markdown", "json"),
        default=None,
    )
    audit.add_argument(
        "--output",
        help="Write the report to this explicit path instead of stdout",
    )
    untracked = audit.add_mutually_exclusive_group()
    untracked.add_argument(
        "--include-untracked",
        action="store_true",
        dest="include_untracked",
        default=None,
        help="Include untracked, non-ignored files",
    )
    untracked.add_argument(
        "--no-untracked",
        action="store_false",
        dest="include_untracked",
        help="Exclude untracked, non-ignored files",
    )
    audit.add_argument(
        "--check-results",
        action="append",
        default=None,
        metavar="PATH",
        help="Import a provenance-bound RepoWitness evidence JSON file",
    )
    audit.add_argument(
        "--junit",
        action="append",
        default=None,
        metavar="PATH",
        help="Import a JUnit XML file",
    )
    audit.add_argument(
        "--sarif",
        action="append",
        default=None,
        metavar="PATH",
        help="Import a SARIF JSON file",
    )
    audit.add_argument(
        "--evidence-snapshot",
        help="Snapshot captured before generating native JUnit/SARIF evidence",
    )
    audit.add_argument(
        "--fail-on",
        action="append",
        choices=("fail", "warn", "unverified"),
        default=None,
        help="Return non-zero when the report contains this verdict; repeatable",
    )
    snapshot = subcommands.add_parser(
        "snapshot",
        help="Print the current repository snapshot identity for check evidence.",
    )
    snapshot.add_argument(
        "--repository",
        default=".",
        help="Repository path (default: current directory)",
    )
    snapshot.add_argument(
        "--no-untracked",
        action="store_true",
        help="Exclude untracked, non-ignored files from the fingerprint",
    )
    return parser


def _audit_options(args) -> dict:
    repository_path = Path(args.repository).expanduser().resolve()
    config_path = (
        Path(args.config).expanduser().resolve()
        if args.config
        else next(
            (
                candidate
                for candidate in (
                    repository_path / ".repowitness.yml",
                    repository_path / ".repowitness.yaml",
                )
                if candidate.is_file()
            ),
            None,
        )
    )
    configured = load_audit_config(config_path) if config_path else {}
    base = args.base or configured.get("base")
    if not base:
        raise ValueError(
            "--base is required unless audit.base is set in .repowitness.yml"
        )

    def paths(option: str, cli_value):
        values = cli_value if cli_value is not None else configured.get(option, ())
        root = Path.cwd() if cli_value is not None or config_path is None else config_path.parent
        return tuple(
            path
            if (path := Path(value).expanduser()).is_absolute()
            else (root / path).resolve()
            for value in values
        )

    configured_output = configured.get("output")
    if configured_output and config_path and not Path(configured_output).is_absolute():
        configured_output = str((config_path.parent / configured_output).resolve())

    return {
        "repository_path": repository_path,
        "base": base,
        "contracts_ref": (
            args.contracts_ref or configured.get("contracts-ref", "base")
        ),
        "format": args.format or configured.get("format", "markdown"),
        "output": args.output if args.output is not None else configured_output,
        "include_untracked": (
            args.include_untracked
            if args.include_untracked is not None
            else configured.get("include-untracked", True)
        ),
        "check_results": paths("check-results", args.check_results),
        "junit": paths("junit", args.junit),
        "sarif": paths("sarif", args.sarif),
        "evidence_snapshot": (
            args.evidence_snapshot or configured.get("evidence-snapshot")
        ),
        "fail_on": tuple(args.fail_on or configured.get("fail-on", ())),
    }


def main(
    argv=None,
    *,
    engine=None,
    stdout=None,
    stderr=None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = _parser().parse_args(argv)

    if args.command == "snapshot":
        try:
            repository = RepositoryView.open(
                Path(args.repository).expanduser().resolve(),
                base_ref="HEAD",
            )
            print(
                repository.snapshot_identity(
                    include_untracked=not args.no_untracked
                ),
                file=stdout,
            )
            return 0
        except Exception as exc:
            print(f"RepoWitness snapshot failed: {exc}", file=stderr)
            return 1

    try:
        options = _audit_options(args)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"RepoWitness configuration failed: {exc}", file=stderr)
        return 1

    if engine is None:
        config = Config.from_env()
        if not config.api_key:
            print(
                "No API key found. Set REPOWITNESS_API_KEY or OPENAI_API_KEY.",
                file=stderr,
            )
            return 1
        llm_cls = LiteLLM if config.provider == "litellm" else LLM
        llm = llm_cls(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        engine = AuditEngine(llm)

    request = AuditRequest(
        repository_path=options["repository_path"],
        base_ref=options["base"],
        include_untracked=options["include_untracked"],
        contracts_ref=options["contracts_ref"],
        check_result_paths=options["check_results"],
        junit_paths=options["junit"],
        sarif_paths=options["sarif"],
        evidence_snapshot=options["evidence_snapshot"],
    )
    try:
        report = engine.audit(request)
        rendered = (
            render_json(report)
            if options["format"] == "json"
            else render_markdown(report)
        )
        if options["output"]:
            Path(options["output"]).expanduser().resolve().write_text(
                rendered,
                encoding="utf-8",
            )
        else:
            print(rendered, end="", file=stdout)
    except Exception as exc:
        print(f"RepoWitness failed: {exc}", file=stderr)
        return 1

    if any(report.counts[verdict.upper()] for verdict in options["fail_on"]):
        matched = ", ".join(
            verdict.upper()
            for verdict in options["fail_on"]
            if report.counts[verdict.upper()]
        )
        print(f"RepoWitness --fail-on matched: {matched}", file=stderr)
        return 1

    # Advisory remains the default when --fail-on is absent.
    return 0
