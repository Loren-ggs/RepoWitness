"""Bounded, read-only search tools over explicit repository revisions."""

from __future__ import annotations

import fnmatch
import json
import re

from ..evidence import EvidenceStore
from ..repository import RepositoryError, RepositoryView
from .base import Tool


class GlobRepositoryTool(Tool):
    name = "glob_repository"
    description = (
        "List repository-relative files matching a glob at base, head, or "
        "worktree revision. Results are bounded and receive an evidence handle."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "revision": {
                "type": "string",
                "enum": ["base", "head", "worktree"],
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, repository: RepositoryView, evidence: EvidenceStore):
        self._repository = repository
        self._evidence = evidence

    def execute(self, pattern: str, revision: str = "worktree") -> str:
        normalized = pattern.strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise RepositoryError("glob pattern must stay inside the repository")
        matches = [
            path
            for path in self._repository.list_files(revision=revision)
            if _glob_match(path, normalized)
        ]
        truncated = len(matches) > 500
        matches = matches[:500]
        content = "\n".join(matches)
        record = self._evidence.add(
            kind="repository_glob",
            revision=revision,
            content=content,
        )
        return json.dumps(
            {
                "evidence_handle": record.handle,
                "revision": revision,
                "pattern": normalized,
                "matches": matches,
                "truncated": truncated,
            },
            ensure_ascii=False,
        )


class GrepRepositoryTool(Tool):
    name = "grep_repository"
    description = (
        "Search UTF-8 repository files with a regex at an explicit revision. "
        "Returns bounded path, line, and text matches with an evidence handle."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "include": {"type": "string"},
            "revision": {
                "type": "string",
                "enum": ["base", "head", "worktree"],
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, repository: RepositoryView, evidence: EvidenceStore):
        self._repository = repository
        self._evidence = evidence

    def execute(
        self,
        pattern: str,
        include: str = "**/*",
        revision: str = "worktree",
    ) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise RepositoryError(f"invalid search regex: {exc}") from exc
        normalized_include = include.strip().replace("\\", "/")
        if (
            not normalized_include
            or normalized_include.startswith("/")
            or ".." in normalized_include.split("/")
        ):
            raise RepositoryError("include pattern must stay inside the repository")

        matches = []
        scanned = 0
        for path in self._repository.list_files(revision=revision):
            if not _glob_match(path, normalized_include):
                continue
            if scanned >= 2_000 or len(matches) >= 200:
                break
            scanned += 1
            try:
                text = self._repository.read_text(
                    path,
                    revision=revision,
                    max_bytes=500_000,
                )
            except RepositoryError:
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(
                        {
                            "path": path,
                            "line": line_number,
                            "text": line,
                        }
                    )
                    if len(matches) >= 200:
                        break

        content = "\n".join(
            f"{match['path']}:{match['line']}: {match['text']}"
            for match in matches
        )
        record = self._evidence.add(
            kind="repository_grep",
            revision=revision,
            content=content,
        )
        return json.dumps(
            {
                "evidence_handle": record.handle,
                "revision": revision,
                "pattern": pattern,
                "include": normalized_include,
                "matches": matches,
                "truncated": len(matches) >= 200 or scanned >= 2_000,
            },
            ensure_ascii=False,
        )


def _glob_match(path: str, pattern: str) -> bool:
    if pattern in {"*", "**", "**/*"}:
        return True
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.startswith("**/"):
        return fnmatch.fnmatchcase(path, pattern[3:])
    return False
