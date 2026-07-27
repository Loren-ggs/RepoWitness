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
                            "description": (
                                "Optional repository-relative glob patterns "
                                "explicitly supported by the cited contract. "
                                "Omit when the rule applies to the whole "
                                "contract source scope."
                            ),
                        },
                    },
                    "required": [
                        "source_span_id",
                        "statement",
                    ],
                },
            },
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_span_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["source_span_ids", "description"],
                },
            },
        },
        "required": ["rules"],
    }

    def __init__(self, collector: RuleCollector):
        self._collector = collector

    def execute(
        self,
        rules: list[dict],
        conflicts: list[dict] | None = None,
    ) -> str:
        return json.dumps(
            self._collector.submit(rules, conflicts),
            ensure_ascii=False,
        )
