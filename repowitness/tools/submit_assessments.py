"""Structured output tool for the repository review agent."""

import json

from ..collectors import AssessmentCollector
from .base import Tool


class SubmitAssessmentsTool(Tool):
    name = "submit_assessments"
    description = "Submit one evidence-backed verdict for each assigned repository rule."
    parameters = {
        "type": "object",
        "properties": {
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": [
                                "PASS",
                                "FAIL",
                                "WARN",
                                "UNVERIFIED",
                            ],
                        },
                        "evidence_handles": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "rationale": {"type": "string"},
                        "next_step": {"type": "string"},
                    },
                    "required": [
                        "rule_id",
                        "verdict",
                        "evidence_handles",
                        "rationale",
                        "next_step",
                    ],
                },
            }
        },
        "required": ["assessments"],
    }

    def __init__(self, collector: AssessmentCollector):
        self._collector = collector

    def execute(self, assessments: list[dict]) -> str:
        return json.dumps(
            self._collector.submit(assessments),
            ensure_ascii=False,
        )
