"""Structured output tool for the contract compiler agent."""

import json

from ..collectors import RuleCollector
from .base import Tool


class SubmitRulesTool(Tool):
    name = "submit_rules"
    description = "Submit actionable repository rules. Every rule must cite a source_span_id returned by contract_sources."
    parameters = {
        "type": "object",
        "properties": {
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_span_id": {"type": "string"},
                        "statement": {"type": "string"},
                        "applies_to": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "source_span_id",
                        "statement",
                        "applies_to",
                    ],
                },
            }
        },
        "required": ["rules"],
    }

    def __init__(self, collector: RuleCollector):
        self._collector = collector

    def execute(self, rules: list[dict]) -> str:
        return json.dumps(self._collector.submit(rules), ensure_ascii=False)
