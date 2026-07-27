"""Thread-safe structured result collectors used by RepoWitness tools."""

from __future__ import annotations

import hashlib
import threading

from .contracts import ContractCatalog
from .domain import Assessment, ContractConflict, Rule


class RuleCollector:
    def __init__(self, contracts: ContractCatalog):
        self._contracts = contracts
        self._rules: list[Rule] = []
        self._conflicts: list[ContractConflict] = []
        self._lock = threading.Lock()

    @property
    def rules(self) -> tuple[Rule, ...]:
        with self._lock:
            return tuple(self._rules)

    @property
    def conflicts(self) -> tuple[ContractConflict, ...]:
        with self._lock:
            return tuple(self._conflicts)

    def submit(
        self,
        candidates: list[dict],
        conflict_candidates: list[dict] | None = None,
    ) -> dict:
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
                source = self._contracts.source_for_span(span_id)
                digest = hashlib.sha256(f"{span_id}\0{statement}".encode("utf-8")).hexdigest()[:12].upper()
                rule = Rule(
                    rule_id=f"RW-{digest}",
                    source_span_id=span_id,
                    statement=statement,
                    applies_to=applies_to,
                    source_path=span.path,
                    scope_path=source.scope_path if source else "",
                    priority=source.priority if source else 0,
                )
                if rule not in self._rules:
                    self._rules.append(rule)
                accepted.append(rule.rule_id)
            accepted_conflicts, rejected_conflicts = self._submit_conflicts(
                conflict_candidates or []
            )
        return {
            "accepted": len(accepted),
            "rule_ids": accepted,
            "rejected": rejected,
            "accepted_conflicts": accepted_conflicts,
            "rejected_conflicts": rejected_conflicts,
        }

    def _submit_conflicts(
        self,
        candidates: list[dict],
    ) -> tuple[list[str], list[dict]]:
        accepted = []
        rejected = []
        for index, candidate in enumerate(candidates):
            span_ids = tuple(
                dict.fromkeys(
                    str(span_id)
                    for span_id in candidate.get("source_span_ids", [])
                )
            )
            if len(span_ids) < 2 or any(
                self._contracts.span(span_id) is None for span_id in span_ids
            ):
                rejected.append(
                    {
                        "index": index,
                        "reason": "conflicts require at least two known source_span_ids",
                    }
                )
                continue
            description = str(candidate.get("description", "")).strip()
            if not description:
                rejected.append(
                    {"index": index, "reason": "description is required"}
                )
                continue
            sources = [
                self._contracts.source_for_span(span_id) for span_id in span_ids
            ]
            priorities = [source.priority for source in sources if source]
            highest = max(priorities)
            winners = [
                source
                for source in sources
                if source and source.priority == highest
            ]
            resolved = len(winners) == 1
            if resolved:
                resolution = (
                    f"{winners[0].path} takes precedence at priority {highest} "
                    f"inside scope {winners[0].scope_path or 'repository'}."
                )
            else:
                resolution = (
                    "No unique higher-priority source exists; manual "
                    "contract clarification is required."
                )
            digest = hashlib.sha256(
                ("\0".join(span_ids) + f"\0{description}").encode("utf-8")
            ).hexdigest()[:12].upper()
            conflict = ContractConflict(
                conflict_id=f"RWC-{digest}",
                source_span_ids=span_ids,
                description=description,
                resolution=resolution,
                resolved=resolved,
            )
            if conflict not in self._conflicts:
                self._conflicts.append(conflict)
            accepted.append(conflict.conflict_id)
        return accepted, rejected


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
