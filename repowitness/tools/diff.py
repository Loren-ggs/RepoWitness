"""Tool reading a bounded repository diff and issuing an evidence handle."""

import json

from ..evidence import EvidenceStore
from ..repository import RepositoryView
from .base import Tool


class DiffTool(Tool):
    name = "read_diff"
    description = "Read the audited diff for one changed repository-relative file."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "context_lines": {"type": "integer"},
        },
        "required": ["file_path"],
    }

    def __init__(self, repository: RepositoryView, evidence: EvidenceStore):
        self._repository = repository
        self._evidence = evidence

    def execute(self, file_path: str, context_lines: int = 20) -> str:
        content = self._repository.diff(file_path, context_lines=max(0, min(context_lines, 100)))
        record = self._evidence.add(
            kind="diff",
            path=file_path,
            revision="base...worktree",
            content=content,
        )
        return json.dumps(
            {
                "evidence_handle": record.handle,
                "path": file_path,
                "revision": record.revision,
                "content": content,
            },
            ensure_ascii=False,
        )
