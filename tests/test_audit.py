import json
import re
import subprocess

from repowitness.audit import AuditEngine
from repowitness.domain import AuditRequest
from repowitness.llm import LLMResponse, ToolCall


def _git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


class _ScriptedReviewLLM:
    def __init__(self):
        self.calls = {"contract": 0, "review": 0}
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.model = "scripted-review-model"

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
                                        "applies_to": ["**/*.py"],
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
