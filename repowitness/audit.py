"""The single orchestration seam shared by RepoWitness frontends."""

from __future__ import annotations

from .agent import Agent
from .collectors import AssessmentCollector, RuleCollector
from .contracts import ContractCatalog
from .domain import AuditReport, AuditRequest
from .evidence import EvidenceStore
from .prompt import contract_compiler_prompt, review_prompt
from .repository import RepositoryView
from .tools import build_contract_tools, build_review_tools
from .validation import validate_assessments


class AuditEngine:
    def __init__(self, llm):
        self._llm = llm

    def audit(self, request: AuditRequest) -> AuditReport:
        repository = RepositoryView.open(
            request.repository_path,
            base_ref=request.base_ref,
        )
        changes = tuple(repository.changed_files(include_untracked=request.include_untracked))
        contracts = ContractCatalog.discover(repository)
        rule_collector = RuleCollector(contracts)
        issues = []

        if contracts.spans:
            contract_agent = Agent(
                llm=self._llm,
                tools=build_contract_tools(contracts, rule_collector),
                system=contract_compiler_prompt(),
                max_rounds=15,
            )
            contract_agent.chat("Compile the authoritative repository contract into rules.")
        else:
            issues.append("No authoritative root AGENTS.md contract was found.")

        rules = rule_collector.rules
        evidence = EvidenceStore()
        assessment_collector = AssessmentCollector(rules)

        if rules:
            review_agent = Agent(
                llm=self._llm,
                tools=build_review_tools(
                    repository,
                    evidence,
                    assessment_collector,
                    include_untracked=request.include_untracked,
                ),
                system=review_prompt(rules),
                max_rounds=25,
            )
            review_agent.chat("Review the current repository changes against every assigned rule.")
        elif contracts.spans:
            issues.append("The contract compiler did not submit any actionable rules.")

        assessments = validate_assessments(
            rules,
            evidence,
            assessment_collector.assessments,
        )
        return AuditReport(
            base_revision=repository.base_revision,
            head_revision=repository.head_revision,
            changes=changes,
            contracts=contracts.sources,
            rules=rules,
            assessments=assessments,
            evidence=evidence.records,
            model=getattr(self._llm, "model", "unknown"),
            issues=tuple(issues),
        )
