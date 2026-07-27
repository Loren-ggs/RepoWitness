"""Tool exposing the exact rules assigned to one review agent."""

import json

from ..domain import Rule
from .base import Tool


class RulesTool(Tool):
    name = "rules"
    description = "List the exact repository rules assigned to this review."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, rules: tuple[Rule, ...]):
        self._rules = rules

    def execute(self) -> str:
        return json.dumps(
            {
                "rules": [
                    {
                        "rule_id": rule.rule_id,
                        "statement": rule.statement,
                        "source_span_id": rule.source_span_id,
                        "source_path": rule.source_path,
                        "scope_path": rule.scope_path,
                        "priority": rule.priority,
                        "applies_to": list(rule.applies_to),
                    }
                    for rule in self._rules
                ]
            },
            ensure_ascii=False,
        )
