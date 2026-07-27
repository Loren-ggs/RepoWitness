"""Tool exposing validated deterministic check-result evidence."""

import json

from ..evidence import EvidenceStore
from .base import Tool


class CheckResultsTool(Tool):
    name = "check_results"
    description = (
        "List external test, lint, or static-check results whose snapshot "
        "provenance was validated for this audit."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, evidence: EvidenceStore):
        self._evidence = evidence

    def execute(self) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "evidence_handle": record.handle,
                        "revision": record.revision,
                        "path": record.path,
                        "content": record.content,
                    }
                    for record in self._evidence.records
                    if record.kind == "check_result"
                ]
            },
            ensure_ascii=False,
        )
