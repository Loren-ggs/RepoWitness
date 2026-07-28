"""Discover repository contract sources and preserve exact provenance."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .domain import ContractSource, SourceSpan
from .repository import RepositoryError, RepositoryView

_ROOT_POLICIES = {
    "AGENTS.md": ("agent_instructions", 300),
    "CLAUDE.md": ("agent_instructions", 300),
    "CONTRIBUTING.md": ("contribution_policy", 220),
    "SECURITY.md": ("security_policy", 220),
}
_AGENT_INSTRUCTION_FILES = {"AGENTS.md", "CLAUDE.md"}
_DOC_DIRECTORIES = {
    "doc",
    "docs",
    "adr",
    "adrs",
    "architecture",
    "architectures",
    "design",
    "decisions",
}
MAX_CONTRACT_FILES = 12
MAX_CONTRACT_BYTES = 150_000
MAX_CONTRACT_CANDIDATES = 128


@dataclass(frozen=True)
class ContractCandidate:
    path: str
    kind: str
    scope_path: str
    priority: int
    required: bool


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
        discovery = ContractSourceDiscovery.discover(
            repository,
            revision=revision,
            changed_paths=changed_paths,
        )
        remaining = max(0, MAX_CONTRACT_FILES - len(discovery.required))
        catalog = discovery.load(discovery.optional_paths[:remaining])
        if len(discovery.required) + len(discovery.optional) <= MAX_CONTRACT_FILES:
            return catalog
        return cls(
            sources=catalog.sources,
            issues=(
                f"Contract discovery found "
                f"{len(discovery.required) + len(discovery.optional)} sources; "
                f"only the first {MAX_CONTRACT_FILES} by priority were loaded "
                f"because of the {MAX_CONTRACT_FILES}-file limit.",
                *catalog.issues,
            ),
        )

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


@dataclass
class ContractSourceDiscovery:
    repository: RepositoryView
    revision: str
    required: tuple[ContractCandidate, ...]
    optional: tuple[ContractCandidate, ...]
    issues: tuple[str, ...] = ()
    _catalog: ContractCatalog | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    @classmethod
    def discover(
        cls,
        repository: RepositoryView,
        *,
        revision: str = "base",
        changed_paths: tuple[str, ...] = (),
    ) -> "ContractSourceDiscovery":
        if revision not in {"base", "head", "worktree"}:
            raise RepositoryError(f"unsupported contract revision: {revision}")
        candidates = _contract_candidates(
            set(repository.list_files(revision=revision)),
            changed_paths,
        )
        required = tuple(
            candidate for candidate in candidates if candidate.required
        )
        optional = tuple(
            candidate for candidate in candidates if not candidate.required
        )
        issues = ()
        if len(optional) > MAX_CONTRACT_CANDIDATES:
            issues = (
                f"Contract discovery found {len(optional)} optional candidates; "
                f"only the first {MAX_CONTRACT_CANDIDATES} paths were exposed "
                "to the contract compiler.",
            )
            optional = optional[:MAX_CONTRACT_CANDIDATES]
        return cls(
            repository=repository,
            revision=revision,
            required=required,
            optional=optional,
            issues=issues,
        )

    @property
    def optional_paths(self) -> tuple[str, ...]:
        return tuple(candidate.path for candidate in self.optional)

    @property
    def max_optional_files(self) -> int:
        return max(0, MAX_CONTRACT_FILES - len(self.required))

    @property
    def catalog(self) -> ContractCatalog | None:
        with self._lock:
            return self._catalog

    def load(self, selected_paths: tuple[str, ...] | list[str]) -> ContractCatalog:
        if (
            not isinstance(selected_paths, (list, tuple))
            or any(not isinstance(path, str) for path in selected_paths)
        ):
            raise ValueError("selected contract paths must be a string array")
        selected = tuple(selected_paths)
        if len(selected) != len(set(selected)):
            raise ValueError("selected contract paths must be unique")
        unknown = set(selected) - set(self.optional_paths)
        if unknown:
            raise ValueError(
                f"unknown contract source path: {sorted(unknown)[0]}"
            )
        if len(selected) > self.max_optional_files:
            raise ValueError(
                f"at most {self.max_optional_files} optional contract sources "
                "can be selected"
            )

        with self._lock:
            if self._catalog is not None:
                raise ValueError("contract sources were already selected")
            by_path = {
                candidate.path: candidate for candidate in self.optional
            }
            candidates = self.required[:MAX_CONTRACT_FILES] + tuple(
                by_path[path] for path in selected
            )
            issues = list(self.issues)
            if len(self.required) > MAX_CONTRACT_FILES:
                issues.append(
                    f"Contract discovery found {len(self.required)} priority "
                    f"sources; only {MAX_CONTRACT_FILES} fit the file limit."
                )
            catalog = _load_catalog(
                self.repository,
                self.revision,
                candidates,
                issues,
            )
            self._catalog = catalog
        return catalog

    def span(self, span_id: str) -> SourceSpan | None:
        catalog = self.catalog
        return catalog.span(span_id) if catalog else None

    def source_for_span(self, span_id: str) -> ContractSource | None:
        catalog = self.catalog
        return catalog.source_for_span(span_id) if catalog else None


def _load_catalog(
    repository: RepositoryView,
    revision: str,
    candidates: tuple[ContractCandidate, ...],
    issues: list[str],
) -> ContractCatalog:
    sources = []
    remaining_bytes = MAX_CONTRACT_BYTES
    for candidate in candidates:
        if remaining_bytes <= 0:
            issues.append(
                f"Contract source loading stopped at the "
                f"{MAX_CONTRACT_BYTES}-byte total limit."
            )
            break
        try:
            text = repository.read_text(
                candidate.path,
                revision=revision,
                max_bytes=min(500_000, remaining_bytes),
            )
        except RepositoryError as exc:
            issues.append(
                f"Skipped contract source {candidate.path}: {exc}"
            )
            continue
        remaining_bytes -= len(text.encode("utf-8"))
        sources.append(
            ContractSource(
                path=candidate.path,
                revision=revision,
                spans=tuple(
                    _split_spans(candidate.path, text, revision)
                ),
                kind=candidate.kind,
                scope_path=candidate.scope_path,
                priority=candidate.priority,
            )
        )
    return ContractCatalog(sources=tuple(sources), issues=tuple(issues))


def _contract_candidates(
    available: set[str],
    changed_paths: tuple[str, ...],
) -> tuple[ContractCandidate, ...]:
    candidates: dict[str, ContractCandidate] = {}

    for path, (kind, priority) in _ROOT_POLICIES.items():
        if path in available:
            candidates[path] = ContractCandidate(
                path=path,
                kind=kind,
                scope_path="",
                priority=priority,
                required=True,
            )

    for path in available:
        pure = PurePosixPath(path)
        lower_name = pure.name.lower()
        lower_parts = tuple(part.lower() for part in pure.parts)

        if (
            pure.name in _AGENT_INSTRUCTION_FILES
            and pure.parent != PurePosixPath(".")
        ):
            scope_path = pure.parent.as_posix()
            if any(
                _path_is_in_scope(changed_path, scope_path)
                for changed_path in changed_paths
            ):
                candidates[path] = ContractCandidate(
                    path=path,
                    kind="agent_instructions",
                    scope_path=scope_path,
                    priority=300 + len(pure.parent.parts),
                    required=True,
                )
            continue

        if (
            pure.parent == PurePosixPath(".")
            and lower_name.startswith("readme")
            and pure.suffix.lower() == ".md"
        ):
            candidates[path] = ContractCandidate(
                path=path,
                kind="readme",
                scope_path="",
                priority=100,
                required=False,
            )
            continue

        is_architecture_name = lower_name in {
            "architecture.md",
            "architectures.md",
        }
        if pure.suffix.lower() != ".md" or not (
            is_architecture_name
            or any(part in _DOC_DIRECTORIES for part in lower_parts[:-1])
        ):
            continue
        kind = (
            "adr"
            if any(
                part in {"adr", "adrs", "decisions"}
                for part in lower_parts
            )
            else "architecture"
            if is_architecture_name or any(
                part in {"architecture", "architectures", "design"}
                for part in lower_parts
            )
            else "documentation"
        )
        candidates[path] = ContractCandidate(
            path=path,
            kind=kind,
            scope_path="",
            priority=180 if kind in {"adr", "architecture"} else 120,
            required=False,
        )

    root_order = {path: index for index, path in enumerate(_ROOT_POLICIES)}
    required = sorted(
        (
            candidate
            for candidate in candidates.values()
            if candidate.required
        ),
        key=lambda candidate: (
            0 if candidate.path in root_order else 1,
            root_order.get(candidate.path, 0),
            -candidate.priority,
            candidate.path.lower(),
        ),
    )
    optional = sorted(
        (
            candidate
            for candidate in candidates.values()
            if not candidate.required
        ),
        key=lambda candidate: (
            -candidate.priority,
            candidate.path.count("/"),
            candidate.path.lower(),
        ),
    )
    return tuple(required + optional)


def is_contract_path(path: str) -> bool:
    """Return whether a changed path can act as a repository contract source."""
    pure = PurePosixPath(path)
    lower_name = pure.name.lower()
    lower_parts = tuple(part.lower() for part in pure.parts)
    if pure.name in _AGENT_INSTRUCTION_FILES:
        return True
    if pure.parent == PurePosixPath(".") and (
        pure.name in _ROOT_POLICIES
        or (lower_name.startswith("readme") and pure.suffix.lower() == ".md")
    ):
        return True
    return (
        pure.suffix.lower() == ".md"
        and (
            lower_name in {"architecture.md", "architectures.md"}
            or any(part in _DOC_DIRECTORIES for part in lower_parts[:-1])
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
