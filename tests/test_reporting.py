import json

from repowitness.domain import (
    Assessment,
    AuditReport,
    ChangedFile,
    ContractSource,
    Evidence,
    Rule,
    SourceSpan,
)
from repowitness.reporting import render_json, render_markdown


def _report():
    span = SourceSpan(
        span_id="span-rule",
        path="AGENTS.md",
        revision="base",
        start_line=3,
        end_line=3,
        text="Public APIs must stay compatible.",
    )
    rule = Rule(
        rule_id="RW-ABC123",
        source_span_id=span.span_id,
        statement=span.text,
        applies_to=("**/*.py",),
    )
    evidence = Evidence(
        handle="evidence-diff",
        kind="diff",
        path="app.py",
        revision="base...worktree",
        content="-def public_api():\n+def renamed_api():",
    )
    assessment = Assessment(
        rule_id=rule.rule_id,
        verdict="FAIL",
        evidence_handles=(evidence.handle,),
        rationale="The public function was renamed.",
        next_step="Restore a compatibility wrapper.",
    )
    return AuditReport(
        base_revision="base-sha",
        head_revision="head-sha",
        changes=(ChangedFile(path="app.py", status="modified"),),
        contracts=(
            ContractSource(
                path="AGENTS.md",
                revision="base",
                spans=(span,),
            ),
        ),
        rules=(rule,),
        assessments=(assessment,),
        evidence=(evidence,),
        model="test-model",
    )


def test_json_is_canonical_and_markdown_is_rendered_from_the_same_report():
    report = _report()

    payload = json.loads(render_json(report))
    markdown = render_markdown(report)

    assert payload["summary"]["overall"] == "FAIL"
    assert payload["assessments"][0]["rule"]["quote"] == ("Public APIs must stay compatible.")
    assert payload["assessments"][0]["rule"]["source"] == {
        "path": "AGENTS.md",
        "revision": "base",
        "start_line": 3,
        "end_line": 3,
    }
    assert "# RepoWitness 审查报告" in markdown
    assert "FAIL" in markdown
    assert "AGENTS.md:3" in markdown
    assert "Restore a compatibility wrapper." in markdown
