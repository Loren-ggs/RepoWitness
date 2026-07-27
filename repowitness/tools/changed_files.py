"""Tool listing files changed since the audit base revision."""

import json

from ..repository import RepositoryView
from .base import Tool


class ChangedFilesTool(Tool):
    name = "changed_files"
    description = "List tracked and untracked files changed since the audit base revision."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, repository: RepositoryView, include_untracked: bool = True):
        self._repository = repository
        self._include_untracked = include_untracked

    def execute(self) -> str:
        return json.dumps(
            {
                "changes": [
                    {
                        "path": change.path,
                        "status": change.status,
                        "old_path": change.old_path,
                        "binary": change.binary,
                    }
                    for change in self._repository.changed_files(include_untracked=self._include_untracked)
                ]
            },
            ensure_ascii=False,
        )
