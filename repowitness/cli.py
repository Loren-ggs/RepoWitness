"""RepoWitness command-line adapter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .audit import AuditEngine
from .config import Config
from .domain import AuditRequest
from .llm import LLM, LiteLLM
from .reporting import render_json, render_markdown


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
    audit.add_argument("--base", required=True, help="Base Git ref")
    audit.add_argument(
        "--repository",
        default=".",
        help="Repository path (default: current directory)",
    )
    audit.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
    )
    audit.add_argument(
        "--output",
        help="Write the report to this explicit path instead of stdout",
    )
    audit.add_argument(
        "--no-untracked",
        action="store_true",
        help="Exclude untracked, non-ignored files",
    )
    return parser


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
        repository_path=Path(args.repository).expanduser().resolve(),
        base_ref=args.base,
        include_untracked=not args.no_untracked,
    )
    try:
        report = engine.audit(request)
        rendered = render_json(report) if args.format == "json" else render_markdown(report)
        if args.output:
            Path(args.output).expanduser().resolve().write_text(
                rendered,
                encoding="utf-8",
            )
        else:
            print(rendered, end="", file=stdout)
    except Exception as exc:
        print(f"RepoWitness audit failed: {exc}", file=stderr)
        return 1

    # Advisory mode: a report containing FAIL is still a successful audit run.
    return 0
