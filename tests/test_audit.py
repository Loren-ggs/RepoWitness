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
    def __init__(self, applies_to=("**/*.py",)):
        self.calls = {"contract": 0, "review": 0}
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.model = "scripted-review-model"
        self.applies_to = applies_to

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
                                        "statement": ("Public APIs must stay compatible."),
                                        "applies_to": list(self.applies_to),
                                    }
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
