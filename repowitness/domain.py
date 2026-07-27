"""Domain types shared by RepoWitness audit modules."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    old_path: str | None = None
    binary: bool = False


@dataclass(frozen=True)
class SourceSpan:
    span_id: str
    path: str
    revision: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class ContractSource:
    path: str
    revision: str
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True)
class Rule:
    rule_id: str
    source_span_id: str
    statement: str
    applies_to: tuple[str, ...]


@dataclass(frozen=True)
class Evidence:
    handle: str
    kind: str
    path: str | None
    revision: str
    content: str
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True)
class Assessment:
    rule_id: str
    verdict: str
    evidence_handles: tuple[str, ...]
    rationale: str
    next_step: str
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditRequest:
    repository_path: Path
    base_ref: str
    include_untracked: bool = True


@dataclass(frozen=True)
class AuditReport:
    base_revision: str
    head_revision: str
    changes: tuple[ChangedFile, ...]
    contracts: tuple[ContractSource, ...]
    rules: tuple[Rule, ...]
    assessments: tuple[Assessment, ...]
    evidence: tuple[Evidence, ...]
    model: str
    issues: tuple[str, ...] = ()
    schema_version: str = "1"
    mode: str = "advisory"

    @property
    def counts(self) -> dict[str, int]:
        verdicts = ("PASS", "FAIL", "WARN", "UNVERIFIED")
        return {verdict: sum(assessment.verdict == verdict for assessment in self.assessments) for verdict in verdicts}

    @property
    def overall(self) -> str:
        counts = self.counts
        for verdict in ("FAIL", "WARN", "UNVERIFIED"):
            if counts[verdict]:
                return verdict
        if counts["PASS"]:
            return "PASS"
        return "UNVERIFIED"
