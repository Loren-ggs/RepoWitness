"""File reading with line numbers."""

from pathlib import Path
import json

from ..evidence import EvidenceStore
from ..repository import RepositoryView
from .base import Tool


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read a file's contents with line numbers. "
        "Always read a file before editing it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file",
            },
            "offset": {
                "type": "integer",
                "description": "Start line (1-based). Default 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Max lines to read. Default 2000.",
            },
        },
        "required": ["file_path"],
    }

    def execute(self, file_path: str, offset: int = 1, limit: int = 2000) -> str:
        try:
            p = Path(file_path).expanduser().resolve()
            if not p.exists():
                return f"Error: {file_path} not found"
            if not p.is_file():
                return f"Error: {file_path} is a directory, not a file"

            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            total = len(lines)

            start = max(0, offset - 1)
            chunk = lines[start : start + limit]
            numbered = [f"{start + i + 1}\t{ln}" for i, ln in enumerate(chunk)]
            result = "\n".join(numbered)

            if total > start + limit:
                result += f"\n... ({total} lines total, showing {start+1}-{start+len(chunk)})"
            return result or "(empty file)"
        except Exception as e:
            return f"Error: {e}"


class ReadRepositoryFileTool(Tool):
    """Read a repository snapshot without allowing paths outside its root."""

    name = "read_repository_file"
    description = (
        "Read a UTF-8 repository file at base, head, or worktree revision. "
        "Paths must be repository-relative."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "revision": {
                "type": "string",
                "enum": ["base", "head", "worktree"],
            },
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "required": ["file_path"],
    }

    def __init__(
        self, repository: RepositoryView, evidence: EvidenceStore
    ):
        self._repository = repository
        self._evidence = evidence

    def execute(
        self,
        file_path: str,
        revision: str = "worktree",
        offset: int = 1,
        limit: int = 300,
    ) -> str:
        text = self._repository.read_text(file_path, revision=revision)
        lines = text.splitlines()
        start = max(0, offset - 1)
        bounded_limit = max(1, min(limit, 1000))
        chunk = lines[start : start + bounded_limit]
        numbered = "\n".join(
            f"{start + index + 1}\t{line}"
            for index, line in enumerate(chunk)
        )
        end_line = start + len(chunk)
        record = self._evidence.add(
            kind="repository_file",
            path=file_path,
            revision=revision,
            start_line=start + 1,
            end_line=end_line,
            content=numbered,
        )
        return json.dumps(
            {
                "evidence_handle": record.handle,
                "path": file_path,
                "revision": revision,
                "start_line": start + 1,
                "end_line": end_line,
                "content": numbered,
                "total_lines": len(lines),
            },
            ensure_ascii=False,
        )
