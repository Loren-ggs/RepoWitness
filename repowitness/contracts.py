"""Discover repository contract sources and preserve exact provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from .domain import ContractSource, SourceSpan
from .repository import RepositoryError, RepositoryView

_ROOT_POLICIES = {
    "AGENTS.md": ("agent_instructions", 300),
    "CONTRIBUTING.md": ("contribution_policy", 220),
    "SECURITY.md": ("security_policy", 220),
}


@dataclass(frozen=True)
class ContractCatalog:
    sources: tuple[ContractSource, ...]
    issues: tuple[str, ...] = ()

    @property
    def spans(self) -> tuple[SourceSpan, ...]:
        return tuple(span for source in self.sources for span in source.spans)

    @classmethod
    def discover(
        cls,
        repository: RepositoryView,
        *,
        revision: str = "base",
        changed_paths: tuple[str, ...] = (),
    ) -> "ContractCatalog":
        if revision not in {"base", "head", "worktree"}:
            raise RepositoryError(f"unsupported contract revision: {revision}")

        available = set(repository.list_files(revision=revision))
        candidates = _contract_candidates(available, changed_paths)
        sources = []
        issues = []
        if len(candidates) > 64:
            issues.append(
                f"Contract discovery found {len(candidates)} sources; "
                "only the first 64 by priority were loaded."
            )
        remaining_bytes = 2_000_000
        for path, kind, scope_path, priority in candidates[:64]:
            if remaining_bytes <= 0:
                issues.append(
                    "Contract source loading stopped at the 2 MB total limit."
                )
                break
            try:
                text = repository.read_text(
                    path,
                    revision=revision,
                    max_bytes=min(500_000, remaining_bytes),
                )
            except RepositoryError as exc:
                issues.append(f"Skipped contract source {path}: {exc}")
                continue
            remaining_bytes -= len(text.encode("utf-8"))
            spans = tuple(_split_spans(path, text, revision))
            sources.append(
                ContractSource(
                    path=path,
                    revision=revision,
                    spans=spans,
                    kind=kind,
                    scope_path=scope_path,
                    priority=priority,
                )
            )
        return cls(sources=tuple(sources), issues=tuple(issues))

    def span(self, span_id: str) -> SourceSpan | None:
        return next(
            (span for span in self.spans if span.span_id == span_id),
            None,
        )

    def source_for_span(self, span_id: str) -> ContractSource | None:
        return next(
            (
                source
                for source in self.sources
                if any(span.span_id == span_id for span in source.spans)
            ),
            None,
        )


def _contract_candidates(
    available: set[str],
    changed_paths: tuple[str, ...],
) -> tuple[tuple[str, str, str, int], ...]:
    candidates: dict[str, tuple[str, str, int]] = {}

    for path, (kind, priority) in _ROOT_POLICIES.items():
        if path in available:
            candidates[path] = (kind, "", priority)

    for path in available:
        pure = PurePosixPath(path)
        lower_name = pure.name.lower()
        lower_parts = tuple(part.lower() for part in pure.parts)

        if pure.name == "AGENTS.md" and pure.parent != PurePosixPath("."):
            scope_path = pure.parent.as_posix()
            if any(_path_is_in_scope(changed_path, scope_path) for changed_path in changed_paths):
                candidates[path] = (
                    "agent_instructions",
                    scope_path,
                    300 + len(pure.parent.parts),
                )
            continue

        if pure.parent == PurePosixPath(".") and lower_name.startswith("readme") and pure.suffix.lower() == ".md":
            candidates[path] = ("readme", "", 100)
            continue

        is_architecture = (
            lower_name in {"architecture.md", "architectures.md"}
            or any(part in {"adr", "adrs", "architecture", "architectures"} for part in lower_parts[:-1])
        )
        if is_architecture and pure.suffix.lower() == ".md":
            kind = "adr" if any(part in {"adr", "adrs"} for part in lower_parts) else "architecture"
            candidates[path] = (kind, "", 180)

    ordered = sorted(
        (
            (path, kind, scope_path, priority)
            for path, (kind, scope_path, priority) in candidates.items()
        ),
        key=lambda item: (-item[3], item[0].count("/"), item[0].lower()),
    )
    return tuple(ordered)


def is_contract_path(path: str) -> bool:
    """Return whether a changed path can act as a repository contract source."""
    pure = PurePosixPath(path)
    lower_name = pure.name.lower()
    lower_parts = tuple(part.lower() for part in pure.parts)
    if pure.name == "AGENTS.md":
        return True
    if pure.parent == PurePosixPath(".") and (
        pure.name in _ROOT_POLICIES
        or (lower_name.startswith("readme") and pure.suffix.lower() == ".md")
    ):
        return True
    return pure.suffix.lower() == ".md" and (
        lower_name in {"architecture.md", "architectures.md"}
        or any(
            part in {"adr", "adrs", "architecture", "architectures"}
            for part in lower_parts[:-1]
        )
    )


def _path_is_in_scope(path: str, scope_path: str) -> bool:
    return path == scope_path or path.startswith(f"{scope_path}/")


def _split_spans(path: str, text: str, revision: str) -> list[SourceSpan]:
    lines = text.splitlines()
    spans = []
    start = None
    block = []

    def flush(end_line: int) -> None:
        nonlocal start, block
        if start is None:
            return
        exact = "\n".join(block)
        digest = hashlib.sha256(
            f"{path}\0{revision}\0{start}\0{end_line}\0{exact}".encode("utf-8")
        ).hexdigest()[:16]
        spans.append(
            SourceSpan(
                span_id=f"span-{digest}",
                path=path,
                revision=revision,
                start_line=start,
                end_line=end_line,
                text=exact,
            )
        )
        start = None
        block = []

    for line_number, line in enumerate(lines, 1):
        if line.strip():
            if start is None:
                start = line_number
            block.append(line)
        else:
            flush(line_number - 1)
    flush(len(lines))
    return spans
