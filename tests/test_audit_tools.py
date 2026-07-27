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
from repowitness.tools.repository_search import GlobRepositoryTool, GrepRepositoryTool
from repowitness.tools.submit_rules import SubmitRulesTool
from repowitness.tools.submit_assessments import SubmitAssessmentsTool
from repowitness.tools import build_contract_tools, build_review_tools
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


def test_audit_tool_sets_never_register_mutating_or_subagent_tools(tmp_path):
    catalog = _catalog(tmp_path)
    repository = RepositoryView.open(tmp_path, base_ref="HEAD")
    rules = RuleCollector(catalog)
    evidence = EvidenceStore()
    assessments = AssessmentCollector(())

    contract_names = {
        tool.name for tool in build_contract_tools(catalog, rules)
    }
    review_names = {
        tool.name
        for tool in build_review_tools(
            repository,
            evidence,
            assessments,
            (),
        )
    }

    forbidden = {"bash", "write_file", "edit_file", "agent"}
    assert contract_names == {"contract_sources", "submit_rules"}
    assert forbidden.isdisjoint(review_names)
    assert review_names == {
        "changed_files",
        "rules",
        "check_results",
        "read_diff",
        "read_repository_file",
        "glob_repository",
        "grep_repository",
        "submit_assessments",
    }


def test_contract_conflicts_require_real_spans_and_use_source_priority(tmp_path):
    catalog = _catalog(tmp_path)
    collector = RuleCollector(catalog)
    span_id = catalog.spans[0].span_id

    result = collector.submit(
        [],
        [
            {
                "source_span_ids": [span_id, "span-invented"],
                "description": "Compatibility is both required and forbidden.",
            }
        ],
    )

    assert result["accepted_conflicts"] == []
    assert result["rejected_conflicts"][0]["index"] == 0
    assert collector.conflicts == ()


def test_submit_rules_schema_exposes_conflicts_as_an_object_property(tmp_path):
    catalog = _catalog(tmp_path)
    tool = SubmitRulesTool(RuleCollector(catalog))

    assert "conflicts" in tool.parameters["properties"]


def test_submit_rules_schema_defaults_unspecified_paths_to_source_scope(tmp_path):
    catalog = _catalog(tmp_path)
    collector = RuleCollector(catalog)
    tool = SubmitRulesTool(collector)
    rule_schema = tool.parameters["properties"]["rules"]["items"]

    assert "applies_to" not in rule_schema["required"]
    assert "repository-relative glob" in (
        rule_schema["properties"]["applies_to"]["description"]
    )

    result = json.loads(
        tool.execute(
            rules=[
                {
                    "source_span_id": catalog.spans[0].span_id,
                    "statement": "Public APIs must stay compatible.",
                }
            ]
        )
    )

    assert result["accepted"] == 1
    assert collector.rules[0].applies_to == ()


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


def test_repository_search_tools_are_snapshot_bounded_and_issue_evidence(tmp_path):
    _catalog(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def public_api():\n    return 1\n")
    (tmp_path / "src" / "app.txt").write_text("public_api\n")
    _git(tmp_path, "add", "src")
    _git(tmp_path, "commit", "-qm", "search fixtures")
    repository = RepositoryView.open(tmp_path, base_ref="HEAD")
    evidence = EvidenceStore()

    files = json.loads(
        GlobRepositoryTool(repository, evidence).execute(
            "**/*.py",
            revision="head",
        )
    )
    matches = json.loads(
        GrepRepositoryTool(repository, evidence).execute(
            r"def\s+public_api",
            include="**/*.py",
            revision="head",
        )
    )

    assert files["matches"] == ["src/app.py"]
    assert matches["matches"] == [
        {"path": "src/app.py", "line": 1, "text": "def public_api():"}
    ]
    assert evidence.get(files["evidence_handle"]).kind == "repository_glob"
    assert evidence.get(matches["evidence_handle"]).kind == "repository_grep"


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


def test_pass_cannot_cite_a_failing_deterministic_check(tmp_path):
    catalog = _catalog(tmp_path)
    rules = RuleCollector(catalog)
    rules.submit(
        [
            {
                "source_span_id": catalog.spans[0].span_id,
                "statement": "Public APIs must stay compatible.",
                "applies_to": ["**/*.py"],
            }
        ]
    )
    evidence = EvidenceStore()
    failed = evidence.add(
        kind="check_result",
        revision="snapshot",
        content=json.dumps(
            {
                "name": "pytest",
                "status": "fail",
                "summary": "1 test failed",
                "details": "",
            }
        ),
    )
    assessments = AssessmentCollector(rules.rules)
    assessments.submit(
        [
            {
                "rule_id": rules.rules[0].rule_id,
                "verdict": "PASS",
                "evidence_handles": [failed.handle],
                "rationale": "Tests cover compatibility.",
                "next_step": "No action.",
            }
        ]
    )

    validated = validate_assessments(
        rules.rules,
        evidence,
        assessments.assessments,
    )

    assert validated[0].verdict == "UNVERIFIED"
    assert "PASS cannot cite a fail check result" in validated[0].limitations[0]
