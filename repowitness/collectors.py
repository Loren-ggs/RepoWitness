"""Thread-safe structured result collectors used by RepoWitness tools."""

from __future__ import annotations

import hashlib
import threading

from .contracts import ContractCatalog
from .domain import Assessment, Rule


class RuleCollector:
    def __init__(self, contracts: ContractCatalog):
        self._contracts = contracts
        self._rules: list[Rule] = []
        self._lock = threading.Lock()

    @property
    def rules(self) -> tuple[Rule, ...]:
        with self._lock:
            return tuple(self._rules)

    def submit(self, candidates: list[dict]) -> dict:
        rejected = []
        accepted = []
        with self._lock:
            for index, candidate in enumerate(candidates):
                span_id = str(candidate.get("source_span_id", ""))
                span = self._contracts.span(span_id)
                if span is None:
                    rejected.append(
                        {
                            "index": index,
                            "reason": f"unknown source_span_id: {span_id}",
                        }
                    )
                    continue
                statement = str(candidate.get("statement", "")).strip()
                if not statement:
                    rejected.append({"index": index, "reason": "statement is required"})
                    continue
                applies_to = tuple(str(item) for item in candidate.get("applies_to", []))
                digest = hashlib.sha256(f"{span_id}\0{statement}".encode("utf-8")).hexdigest()[:12].upper()
                rule = Rule(
                    rule_id=f"RW-{digest}",
                    source_span_id=span_id,
                    statement=statement,
                    applies_to=applies_to,
                )
                if rule not in self._rules:
                    self._rules.append(rule)
                accepted.append(rule.rule_id)
        return {
            "accepted": len(accepted),
            "rule_ids": accepted,
            "rejected": rejected,
        }


class AssessmentCollector:
    _VERDICTS = {"PASS", "FAIL", "WARN", "UNVERIFIED"}

    def __init__(self, rules: tuple[Rule, ...]):
        self._rule_ids = {rule.rule_id for rule in rules}
        self._assessments: dict[str, Assessment] = {}
        self._lock = threading.Lock()

    @property
    def assessments(self) -> tuple[Assessment, ...]:
        with self._lock:
            return tuple(self._assessments.values())

    def submit(self, candidates: list[dict]) -> dict:
        accepted = []
        rejected = []
        with self._lock:
            for index, candidate in enumerate(candidates):
                rule_id = str(candidate.get("rule_id", ""))
                if rule_id not in self._rule_ids:
                    rejected.append(
                        {
                            "index": index,
                            "reason": f"unknown rule_id: {rule_id}",
                        }
                    )
                    continue
                verdict = str(candidate.get("verdict", "")).upper()
                if verdict not in self._VERDICTS:
                    rejected.append(
                        {
                            "index": index,
                            "reason": f"invalid verdict: {verdict}",
                        }
                    )
                    continue
                rationale = str(candidate.get("rationale", "")).strip()
                next_step = str(candidate.get("next_step", "")).strip()
                if not rationale or not next_step:
                    rejected.append(
                        {
                            "index": index,
                            "reason": "rationale and next_step are required",
                        }
                    )
                    continue
                assessment = Assessment(
                    rule_id=rule_id,
                    verdict=verdict,
                    evidence_handles=tuple(str(handle) for handle in candidate.get("evidence_handles", [])),
                    rationale=rationale,
                    next_step=next_step,
                )
                self._assessments[rule_id] = assessment
                accepted.append(rule_id)
        return {
            "accepted": len(accepted),
            "rule_ids": accepted,
            "rejected": rejected,
        }
