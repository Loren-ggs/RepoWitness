"""Discover repository contract sources and preserve exact provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .domain import ContractSource, SourceSpan
from .repository import RepositoryError, RepositoryView


@dataclass(frozen=True)
class ContractCatalog:
    sources: tuple[ContractSource, ...]

    @property
    def spans(self) -> tuple[SourceSpan, ...]:
        return tuple(span for source in self.sources for span in source.spans)

    @classmethod
    def discover(cls, repository: RepositoryView) -> "ContractCatalog":
        sources = []
        for path in ("AGENTS.md",):
            try:
                text = repository.read_text(path, revision="base")
            except RepositoryError:
                continue
            spans = tuple(_split_spans(path, text))
            sources.append(ContractSource(path=path, revision="base", spans=spans))
        return cls(sources=tuple(sources))

    def span(self, span_id: str) -> SourceSpan | None:
        return next(
            (span for span in self.spans if span.span_id == span_id),
            None,
        )


def _split_spans(path: str, text: str) -> list[SourceSpan]:
    lines = text.splitlines()
    spans = []
    start = None
    block = []

    def flush(end_line: int) -> None:
        nonlocal start, block
        if start is None:
            return
        exact = "\n".join(block)
        digest = hashlib.sha256(f"{path}\0base\0{start}\0{end_line}\0{exact}".encode("utf-8")).hexdigest()[:16]
        spans.append(
            SourceSpan(
                span_id=f"span-{digest}",
                path=path,
                revision="base",
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
