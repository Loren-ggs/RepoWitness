"""The single orchestration seam shared by RepoWitness frontends."""

from __future__ import annotations

from .agent import Agent
from .check_results import (
    import_check_results,
    import_native_results,
    repository_result_paths,
)
from .collectors import AssessmentCollector, RuleCollector
from .contracts import ContractCatalog, is_contract_path
from .domain import AuditReport, AuditRequest
from .evidence import EvidenceStore
from .prompt import contract_compiler_prompt, review_prompt
from .repository import RepositoryView
from .rules import select_rules
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
        contracts = ContractCatalog.discover(
            repository,
            revision=request.contracts_ref,
            changed_paths=tuple(change.path for change in changes),
        )
        rule_collector = RuleCollector(contracts)
        issues = list(contracts.issues)

        if contracts.spans:
            contract_agent = Agent(
                llm=self._llm,
                tools=build_contract_tools(contracts, rule_collector),
                system=contract_compiler_prompt(),
                max_rounds=15,
            )
            contract_agent.chat("Compile the authoritative repository contract into rules.")
        else:
            issues.append(
                f"No repository contract sources were found at {request.contracts_ref}."
            )

        compiled_rules = rule_collector.rules
        for conflict in rule_collector.conflicts:
            if not conflict.resolved:
                issues.append(
                    f"Unresolved contract conflict {conflict.conflict_id}: "
                    f"{conflict.description}"
                )
        known_paths = tuple(
            sorted(
                set(repository.list_files(revision="base"))
                | set(repository.list_files(revision="head"))
                | set(repository.list_files(revision="worktree"))
                | {
                    path
                    for change in changes
                    for path in (change.path, change.old_path)
                    if path
                }
            )
        )
        selection = select_rules(
            compiled_rules,
            changes,
            known_paths=known_paths,
        )
        rules = selection.applicable_rules
        issues.extend(selection.notices)
        evidence = EvidenceStore()
        result_paths = (
            request.check_result_paths
            + request.junit_paths
            + request.sarif_paths
        )
        issues.extend(
            import_check_results(
                request.check_result_paths,
                repository,
                evidence,
                include_untracked=request.include_untracked,
                result_paths=result_paths,
            )
        )
        issues.extend(
            import_native_results(
                junit_paths=request.junit_paths,
                sarif_paths=request.sarif_paths,
                evidence_snapshot=request.evidence_snapshot,
                repository=repository,
                evidence=evidence,
                include_untracked=request.include_untracked,
                result_paths=result_paths,
            )
        )
        assessment_collector = AssessmentCollector(rules)

        if rules:
            review_agent = Agent(
                llm=self._llm,
                tools=build_review_tools(
                    repository,
                    evidence,
                    assessment_collector,
                    rules,
                    include_untracked=request.include_untracked,
                ),
                system=review_prompt(rules),
                max_rounds=25,
            )
            review_agent.chat("Review the current repository changes against every assigned rule.")
        elif contracts.spans:
            if compiled_rules:
                issues.append("No compiled repository rules apply to the current changes.")
            else:
                issues.append("The contract compiler did not submit any actionable rules.")

        assessments = validate_assessments(
            rules,
            evidence,
            assessment_collector.assessments,
        )
        return AuditReport(
            base_revision=repository.base_revision,
            head_revision=repository.head_revision,
            snapshot=repository.snapshot_identity(
                include_untracked=request.include_untracked,
                exclude_paths=repository_result_paths(
                    result_paths,
                    repository,
                ),
            ),
            changes=changes,
            contracts=contracts.sources,
            rules=rules,
            assessments=assessments,
            evidence=evidence.records,
            model=getattr(self._llm, "model", "unknown"),
            contracts_ref=request.contracts_ref,
            contract_changes=tuple(
                change for change in changes if is_contract_path(change.path)
            ),
            conflicts=rule_collector.conflicts,
            compiled_rule_count=len(compiled_rules),
            rule_selection=selection.decisions,
            issues=tuple(issues),
        )
