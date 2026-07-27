import json
import subprocess

from repowitness.collectors import AssessmentCollector, RuleCollector
from repowitness.contracts import ContractCatalog
from repowitness.evidence import EvidenceStore
from repowitness.repository import RepositoryView
from repowitness.tools.changed_files import ChangedFilesTool
from repowitness.tools.contract_sources import ContractSourcesTool
from repowitness.tools.diff import DiffTool
from repowitness.tools.read import ReadRepositoryFileTool
from repowitness.tools.submit_rules import SubmitRulesTool
from repowitness.tools.submit_assessments import SubmitAssessmentsTool
from repowitness.validation import validate_assessments


def _git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _catalog(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text("Public APIs must stay compatible.\n")
    _git(tmp_path, "add", "AGENTS.md")
    _git(tmp_path, "commit", "-qm", "rules")
    repository = RepositoryView.open(tmp_path, base_ref="HEAD")
    return ContractCatalog.discover(repository)


def test_contract_tools_only_accept_rules_backed_by_real_source_spans(tmp_path):
    catalog = _catalog(tmp_path)
    collector = RuleCollector(catalog)
    source_tool = ContractSourcesTool(catalog)
    submit_tool = SubmitRulesTool(collector)

    sources = json.loads(source_tool.execute())
    span_id = sources["sources"][0]["spans"][0]["span_id"]
    accepted = json.loads(
        submit_tool.execute(
            rules=[
                {
                    "source_span_id": span_id,
                    "statement": "Public APIs must stay compatible.",
                    "applies_to": ["**/*.py"],
                },
                {
                    "source_span_id": "span-invented",
                    "statement": "Invented rule",
                    "applies_to": ["**/*"],
                },
            ]
        )
    )

    assert accepted["accepted"] == 1
    assert accepted["rejected"] == [{"index": 1, "reason": "unknown source_span_id: span-invented"}]
    assert collector.rules[0].source_span_id == span_id
    assert collector.rules[0].statement == "Public APIs must stay compatible."


def test_review_read_tools_issue_verifiable_evidence_handles(tmp_path):
    _catalog(tmp_path)
    (tmp_path / "app.py").write_text("def public_api():\n    return 1\n")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "app")
    (tmp_path / "app.py").write_text("def public_api():\n    return 2\n")
    repository = RepositoryView.open(tmp_path, base_ref="HEAD")
    evidence = EvidenceStore()

    changes = json.loads(ChangedFilesTool(repository).execute())
    diff = json.loads(DiffTool(repository, evidence).execute("app.py"))
    code = json.loads(ReadRepositoryFileTool(repository, evidence).execute("app.py", revision="worktree", offset=1, limit=2))

    assert changes["changes"] == [
        {
            "path": "app.py",
            "status": "modified",
            "old_path": None,
            "binary": False,
        }
    ]
    assert "+    return 2" in diff["content"]
    assert code["content"] == "1\tdef public_api():\n2\t    return 2"
    assert evidence.get(diff["evidence_handle"]).content == diff["content"]
    assert evidence.get(code["evidence_handle"]).path == "app.py"


def test_invalid_assessment_evidence_is_downgraded_to_unverified(tmp_path):
    catalog = _catalog(tmp_path)
    rules = RuleCollector(catalog)
    span_id = catalog.spans[0].span_id
    rules.submit(
        [
            {
                "source_span_id": span_id,
                "statement": "Public APIs must stay compatible.",
                "applies_to": ["**/*.py"],
            }
        ]
    )
    assessments = AssessmentCollector(rules.rules)
    submitted = json.loads(
        SubmitAssessmentsTool(assessments).execute(
            assessments=[
                {
                    "rule_id": rules.rules[0].rule_id,
                    "verdict": "FAIL",
                    "evidence_handles": ["evidence-invented"],
                    "rationale": "The public API was renamed.",
                    "next_step": "Restore a compatibility wrapper.",
                }
            ]
        )
    )

    validated = validate_assessments(
        rules.rules,
        EvidenceStore(),
        assessments.assessments,
    )

    assert submitted["accepted"] == 1
    assert validated[0].verdict == "UNVERIFIED"
    assert validated[0].limitations == ("unknown evidence handle: evidence-invented",)
