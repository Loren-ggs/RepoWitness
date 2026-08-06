import json
import re
import subprocess

from repowitness.audit import AuditEngine
from repowitness.domain import AuditRequest
from repowitness.llm import LLMResponse, ToolCall
from repowitness.repository import RepositoryView


def _git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


class _ScriptedReviewLLM:
    def __init__(
        self,
        applies_to=("**/*.py",),
        statements=("Public APIs must stay compatible.",),
    ):
        self.calls = {"contract": 0, "review": 0}
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.model = "scripted-review-model"
        self.applies_to = applies_to
        self.statements = statements

    @property
    def estimated_cost(self):
        return None

    def chat(self, messages, tools=None, on_token=None):
        tool_names = {schema["function"]["name"] for schema in (tools or [])}
        role = "contract" if "contract_sources" in tool_names else "review"
        call = self.calls[role]
        self.calls[role] += 1

        if role == "contract":
            if call == 0:
                return LLMResponse(tool_calls=[ToolCall("contract-1", "contract_sources", {})])
            if call == 1:
                sources = json.loads(messages[-1]["content"])
                span_id = sources["sources"][0]["spans"][0]["span_id"]
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            "contract-2",
                            "submit_rules",
                            {
                                "rules": [
                                    {
                                        "source_span_id": span_id,
                                        "statement": statement,
                                        "applies_to": list(self.applies_to),
                                    }
                                    for statement in self.statements
                                ]
                            },
                        )
                    ]
                )
            return LLMResponse(content="Contract compilation complete.")

        if call == 0:
            return LLMResponse(tool_calls=[ToolCall("review-1", "changed_files", {})])
        if call == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        "review-2",
                        "read_diff",
                        {"file_path": "app.py"},
                    )
                ]
            )
        if call == 2:
            diff = json.loads(messages[-1]["content"])
            system = messages[0]["content"]
            rule_id = re.search(r"RW-[A-F0-9]+", system).group()
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        "review-3",
                        "submit_assessments",
                        {
                            "assessments": [
                                {
                                    "rule_id": rule_id,
                                    "verdict": "FAIL",
                                    "evidence_handles": [diff["evidence_handle"]],
                                    "rationale": ("The public API function was renamed."),
                                    "next_step": ("Restore the old public name as a wrapper."),
                                }
                            ]
                        },
                    )
                ]
            )
        return LLMResponse(content="Review complete.")


class _CheckResultReviewLLM(_ScriptedReviewLLM):
    def __init__(self, verdict):
        super().__init__()
        self.verdict = verdict

    def chat(self, messages, tools=None, on_token=None):
        tool_names = {schema["function"]["name"] for schema in (tools or [])}
        if "contract_sources" in tool_names:
            return super().chat(messages, tools=tools, on_token=on_token)

        call = self.calls["review"]
        self.calls["review"] += 1
        if call == 0:
            return LLMResponse(
                tool_calls=[ToolCall("review-checks-1", "check_results", {})]
            )
        if call == 1:
            results = json.loads(messages[-1]["content"])["results"]
            rule_id = re.search(r"RW-[A-F0-9]+", messages[0]["content"]).group()
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        "review-checks-2",
                        "submit_assessments",
                        {
                            "assessments": [
                                {
                                    "rule_id": rule_id,
                                    "verdict": self.verdict,
                                    "evidence_handles": [
                                        results[0]["evidence_handle"]
                                    ],
                                    "rationale": (
                                        "The deterministic check result directly "
                                        "covers this rule."
                                    ),
                                    "next_step": "Inspect the deterministic check.",
                                }
                            ]
                        },
                    )
                ]
            )
        return LLMResponse(content="Review complete.")


class _IncompleteThenRepairLLM(_ScriptedReviewLLM):
    def __init__(self, repair=True):
        super().__init__(
            applies_to=(),
            statements=("Rule one.", "Rule two."),
        )
        self.repair = repair

    def chat(self, messages, tools=None, on_token=None):
        tool_names = {
            schema["function"]["name"] for schema in (tools or [])
        }
        if "contract_sources" in tool_names:
            return super().chat(messages, tools=tools, on_token=on_token)

        call = self.calls["review"]
        self.calls["review"] += 1
        rule_ids = re.findall(r"RW-[A-F0-9]+", messages[0]["content"])
        if call == 0 or (call == 2 and self.repair):
            rule_id = rule_ids[0] if call == 0 else rule_ids[1]
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        f"review-{call}",
                        "submit_assessments",
                        {
                            "assessments": [
                                {
                                    "rule_id": rule_id,
                                    "verdict": "UNVERIFIED",
                                    "evidence_handles": [],
                                    "rationale": "没有足够证据。",
                                    "next_step": "人工检查。",
                                }
                            ]
                        },
                    )
                ]
            )
        return LLMResponse(content="Review complete.")


class _BatchLimitedReviewLLM(_ScriptedReviewLLM):
    def __init__(self):
        super().__init__(
            applies_to=(),
            statements=tuple(f"Rule {index}." for index in range(12)),
        )

    def chat(self, messages, tools=None, on_token=None):
        tool_names = {
            schema["function"]["name"] for schema in (tools or [])
        }
        if "contract_sources" in tool_names:
            return super().chat(messages, tools=tools, on_token=on_token)

        self.calls["review"] += 1
        rule_ids = re.findall(r"RW-[A-F0-9]+", messages[0]["content"])
        if len(rule_ids) > 8:
            return LLMResponse(
                tool_calls=[
                    ToolCall(f"review-{self.calls['review']}", "changed_files", {})
                ]
            )
        if messages[-1]["role"] == "tool":
            assert json.loads(messages[-1]["content"])["complete"] is True
            return LLMResponse(content="Review complete.")
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    f"review-{self.calls['review']}",
                    "submit_assessments",
                    {
                        "assessments": [
                            {
                                "rule_id": rule_id,
                                "verdict": "UNVERIFIED",
                                "evidence_handles": [],
                                "rationale": "没有足够证据。",
                                "next_step": "人工检查。",
                            }
                            for rule_id in rule_ids
                        ]
                    },
                )
            ]
        )


class _SecondBatchExhaustsLLM(_BatchLimitedReviewLLM):
    def __init__(self):
        super().__init__()
        self.failed_batch_calls = 0

    def chat(self, messages, tools=None, on_token=None):
        tool_names = {
            schema["function"]["name"] for schema in (tools or [])
        }
        if "contract_sources" not in tool_names and '"Rule 8."' in messages[0]["content"]:
            self.failed_batch_calls += 1
            if self.failed_batch_calls > 12:
                raise AssertionError("review batch exceeded its round budget")
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        f"exhausted-{self.failed_batch_calls}",
                        "changed_files",
                        {},
                    )
                ]
            )
        return super().chat(messages, tools=tools, on_token=on_token)


class _IncompleteThenRepairContractLLM(_ScriptedReviewLLM):
    def chat(self, messages, tools=None, on_token=None):
        tool_names = {
            schema["function"]["name"] for schema in (tools or [])
        }
        if "contract_sources" not in tool_names:
            return super().chat(messages, tools=tools, on_token=on_token)

        call = self.calls["contract"]
        self.calls["contract"] += 1
        if call == 0:
            return LLMResponse(
                tool_calls=[
                    ToolCall("contract-1", "contract_sources", {})
                ]
            )
        if call == 1:
            return LLMResponse()
        if call == 2:
            source_result = next(
                message["content"]
                for message in reversed(messages)
                if message["role"] == "tool"
            )
            span_id = json.loads(source_result)["sources"][0]["spans"][0][
                "span_id"
            ]
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        "contract-2",
                        "submit_rules",
                        {
                            "rules": [
                                {
                                    "source_span_id": span_id,
                                    "statement": "公共 API 必须保持兼容。",
                                }
                            ]
                        },
                    )
                ]
            )
        return LLMResponse(content="Contract compilation complete.")


class _DocSelectingReviewLLM(_ScriptedReviewLLM):
    def chat(self, messages, tools=None, on_token=None):
        tool_names = {
            schema["function"]["name"] for schema in (tools or [])
        }
        if "contract_sources" not in tool_names:
            return super().chat(messages, tools=tools, on_token=on_token)

        call = self.calls["contract"]
        self.calls["contract"] += 1
        if call == 0:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        "contract-docs-1",
                        "contract_sources",
                        {"selected_paths": ["docs/policy.md"]},
                    )
                ]
            )
        if call == 1:
            sources = json.loads(messages[-1]["content"])["sources"]
            source = next(
                item for item in sources
                if item["path"] == "docs/policy.md"
            )
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        "contract-docs-2",
                        "submit_rules",
                        {
                            "rules": [
                                {
                                    "source_span_id": (
                                        source["spans"][0]["span_id"]
                                    ),
                                    "statement": "Bug fixes require tests.",
                                    "applies_to": ["**/*.py"],
                                }
                            ]
                        },
                    )
                ]
            )
        return LLMResponse(content="Contract compilation complete.")


class _SkippingContractSelectionLLM:
    model = "skipping-contract-selection"

    @property
    def estimated_cost(self):
        return None

    def chat(self, messages, tools=None, on_token=None):
        return LLMResponse(content="No tool call.")


def _repository_with_check_result(tmp_path, status):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text("The full test suite must pass.\n")
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    _git(tmp_path, "add", "AGENTS.md", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text("VALUE = 2\n")

    repository = RepositoryView.open(tmp_path, base_ref="HEAD")
    result_path = tmp_path.parent / f"{tmp_path.name}-check-results.json"
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "snapshot": repository.snapshot_identity(),
                "checks": [
                    {
                        "name": "pytest",
                        "status": status,
                        "summary": f"pytest status: {status}",
                    }
                ],
            }
        )
    )
    return result_path


def _repository_with_two_rules(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text(
        "Rule one.\nRule two.\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "AGENTS.md", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")


def test_audit_engine_runs_contract_and_review_agents_end_to_end(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text("Public APIs must stay compatible.\n")
    (tmp_path / "app.py").write_text("def public_api():\n    return 1\n")
    _git(tmp_path, "add", "AGENTS.md", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text("def renamed_api():\n    return 1\n")

    report = AuditEngine(_ScriptedReviewLLM()).audit(AuditRequest(repository_path=tmp_path, base_ref="HEAD"))

    assert report.overall == "FAIL"
    assert report.counts == {
        "PASS": 0,
        "FAIL": 1,
        "WARN": 0,
        "UNVERIFIED": 0,
    }
    assert report.rules[0].statement == "Public APIs must stay compatible."
    assert report.assessments[0].verdict == "FAIL"
    assert report.evidence[0].path == "app.py"


def test_audit_engine_retries_when_review_agent_submits_only_some_rules(
    tmp_path,
):
    _repository_with_two_rules(tmp_path)
    llm = _IncompleteThenRepairLLM()

    report = AuditEngine(llm).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    assert len(report.assessments) == 2
    assert all(
        assessment.limitations == ()
        for assessment in report.assessments
    )
    assert llm.calls["review"] == 4


def test_audit_engine_partitions_large_rule_sets_for_complete_review(tmp_path):
    _repository_with_two_rules(tmp_path)

    report = AuditEngine(_BatchLimitedReviewLLM()).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    assert len(report.rules) == 12
    assert len(report.assessments) == 12
    assert all(assessment.limitations == () for assessment in report.assessments)
    assert not any("coverage remained incomplete" in issue for issue in report.issues)


def test_audit_engine_isolates_and_summarizes_an_exhausted_review_batch(tmp_path):
    _repository_with_two_rules(tmp_path)
    llm = _SecondBatchExhaustsLLM()

    report = AuditEngine(llm).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    completed = [item for item in report.assessments if not item.limitations]
    missing = [item for item in report.assessments if item.limitations]
    issue = next(
        item for item in report.issues if "coverage remained incomplete" in item
    )
    assert len(completed) == 8
    assert len(missing) == 4
    assert llm.failed_batch_calls == 12
    assert "batch 2/2" in issue
    assert "submitted 0/4" in issue
    assert "4 remaining" in issue
    assert issue.count("RW-") == 3


def test_audit_engine_retries_when_contract_agent_skips_rule_submission(
    tmp_path,
):
    _repository_with_two_rules(tmp_path)
    llm = _IncompleteThenRepairContractLLM()

    report = AuditEngine(llm).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    assert len(report.rules) == 1
    assert llm.calls["contract"] == 4
    assert not any(
        "did not submit any actionable rules" in issue
        for issue in report.issues
    )


def test_audit_reports_coverage_when_repair_stays_incomplete(tmp_path):
    _repository_with_two_rules(tmp_path)

    report = AuditEngine(_IncompleteThenRepairLLM(repair=False)).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    missing = next(
        assessment
        for assessment in report.assessments
        if assessment.limitations == ("missing assessment",)
    )
    issue = report.issues[-1]
    assert "submitted 1/2" in issue
    assert missing.rule_id in issue
    assert "stop_reason=model_response" in issue


def test_audit_engine_lets_contract_agent_select_documentation_sources(
    tmp_path,
):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text("Keep changes reviewable.\n")
    policy = tmp_path / "docs" / "policy.md"
    policy.parent.mkdir()
    policy.write_text("Bug fixes require tests.\n")
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text("VALUE = 2\n")

    report = AuditEngine(_DocSelectingReviewLLM()).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    assert [source.path for source in report.contracts] == [
        "AGENTS.md",
        "docs/policy.md",
    ]
    assert report.rules[0].source_path == "docs/policy.md"


def test_audit_engine_falls_back_to_priority_sources_when_tool_is_skipped(
    tmp_path,
):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text("Keep changes reviewable.\n")
    policy = tmp_path / "docs" / "policy.md"
    policy.parent.mkdir()
    policy.write_text("Bug fixes require tests.\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "contracts")

    report = AuditEngine(_SkippingContractSelectionLLM()).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    assert [source.path for source in report.contracts] == ["AGENTS.md"]
    assert any(
        "did not call contract_sources" in issue
        for issue in report.issues
    )


def test_audit_accepts_snapshot_bound_passing_check_as_pass_evidence(tmp_path):
    result_path = _repository_with_check_result(tmp_path, "pass")

    report = AuditEngine(_CheckResultReviewLLM("PASS")).audit(
        AuditRequest(
            repository_path=tmp_path,
            base_ref="HEAD",
            check_result_paths=(result_path,),
        )
    )

    assert report.assessments[0].verdict == "PASS"
    assert report.evidence[0].kind == "check_result"
    assert report.evidence[0].revision == report.snapshot
    assert tuple(change.path for change in report.changes) == ("app.py",)


def test_audit_accepts_snapshot_bound_failing_check_as_fail_evidence(tmp_path):
    result_path = _repository_with_check_result(tmp_path, "fail")

    report = AuditEngine(_CheckResultReviewLLM("FAIL")).audit(
        AuditRequest(
            repository_path=tmp_path,
            base_ref="HEAD",
            check_result_paths=(result_path,),
        )
    )

    assert report.assessments[0].verdict == "FAIL"
    assert report.overall == "FAIL"


def test_audit_accepts_snapshot_bound_junit_evidence(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text("The full test suite must pass.\n")
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    _git(tmp_path, "add", "AGENTS.md", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text("VALUE = 2\n")
    snapshot = RepositoryView.open(
        tmp_path,
        base_ref="HEAD",
    ).snapshot_identity()
    result_path = tmp_path.parent / f"{tmp_path.name}-junit.xml"
    result_path.write_text(
        """
<testsuite name="unit">
  <testcase classname="tests.test_app" name="test_failure">
    <failure message="failed" />
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )

    report = AuditEngine(_CheckResultReviewLLM("FAIL")).audit(
        AuditRequest(
            repository_path=tmp_path,
            base_ref="HEAD",
            junit_paths=(result_path,),
            evidence_snapshot=snapshot,
        )
    )

    assert report.overall == "FAIL"
    assert json.loads(report.evidence[0].content)["name"].startswith("junit:")
    assert report.issues == ()


def test_audit_does_not_silently_drop_rules_with_unusable_model_scopes(
    tmp_path,
):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text(
        "Public APIs must stay compatible.\n"
    )
    (tmp_path / "app.py").write_text(
        "def public_api():\n    return 1\n"
    )
    _git(tmp_path, "add", "AGENTS.md", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text(
        "def renamed_api():\n    return 1\n"
    )

    report = AuditEngine(
        _ScriptedReviewLLM(applies_to=("repo", "agents"))
    ).audit(
        AuditRequest(repository_path=tmp_path, base_ref="HEAD")
    )

    assert report.overall == "FAIL"
    assert len(report.rules) == 1
    assert report.rules[0].applies_to == ()
    assert report.assessments[0].verdict == "FAIL"
    assert any(
        "treated as scope-wide" in issue for issue in report.issues
    )
    assert report.rule_selection[0].status == "applicable_fallback"
