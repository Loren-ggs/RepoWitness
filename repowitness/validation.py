"""Deterministic validation and conservative verdict downgrading."""

from __future__ import annotations

import json
from dataclasses import replace

from .domain import Assessment, Rule
from .evidence import EvidenceStore


def validate_assessments(
    rules: tuple[Rule, ...],
    evidence: EvidenceStore,
    assessments: tuple[Assessment, ...],
) -> tuple[Assessment, ...]:
    submitted = {assessment.rule_id: assessment for assessment in assessments}
    validated = []

    for rule in rules:
        assessment = submitted.get(rule.rule_id)
        if assessment is None:
            validated.append(
                Assessment(
                    rule_id=rule.rule_id,
                    verdict="UNVERIFIED",
                    evidence_handles=(),
                    rationale="No assessment was submitted for this rule.",
                    next_step="Review this rule manually or rerun the audit.",
                    limitations=("missing assessment",),
                )
            )
            continue

        limitations = [
            f"unknown evidence handle: {handle}" for handle in assessment.evidence_handles if evidence.get(handle) is None
        ]
        if assessment.verdict in {"PASS", "FAIL", "WARN"} and not assessment.evidence_handles:
            limitations.append(f"{assessment.verdict} requires at least one evidence handle")
        if assessment.verdict in {"PASS", "FAIL"}:
            expected_statuses = (
                {"pass"} if assessment.verdict == "PASS" else {"fail", "error"}
            )
            for handle in assessment.evidence_handles:
                record = evidence.get(handle)
                if record is None or record.kind != "check_result":
                    continue
                try:
                    status = json.loads(record.content)["status"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    limitations.append(
                        f"invalid check-result evidence: {handle}"
                    )
                    continue
                if status not in expected_statuses:
                    limitations.append(
                        f"{assessment.verdict} cannot cite a {status} "
                        f"check result: {handle}"
                    )

        if limitations:
            assessment = replace(
                assessment,
                verdict="UNVERIFIED",
                limitations=tuple(limitations),
            )
        validated.append(assessment)

    return tuple(validated)
