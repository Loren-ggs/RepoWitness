"""Immutable evidence records issued by read-only audit tools."""

from __future__ import annotations

import hashlib
import threading

from .domain import Evidence


class EvidenceStore:
    def __init__(self):
        self._records: dict[str, Evidence] = {}
        self._lock = threading.Lock()

    def add(
        self,
        *,
        kind: str,
        revision: str,
        content: str,
        path: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> Evidence:
        digest = hashlib.sha256(
            "\0".join(
                [
                    kind,
                    revision,
                    path or "",
                    str(start_line or ""),
                    str(end_line or ""),
                    content,
                ]
            ).encode("utf-8")
        ).hexdigest()[:16]
        handle = f"evidence-{digest}"
        record = Evidence(
            handle=handle,
            kind=kind,
            path=path,
            revision=revision,
            content=content,
            start_line=start_line,
            end_line=end_line,
        )
        with self._lock:
            self._records[handle] = record
        return record

    def get(self, handle: str) -> Evidence | None:
        with self._lock:
            return self._records.get(handle)

    @property
    def records(self) -> tuple[Evidence, ...]:
        with self._lock:
            return tuple(self._records.values())
