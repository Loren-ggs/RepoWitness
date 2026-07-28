import json
from dataclasses import replace

from repowitness.domain import (
    Assessment,
    AuditReport,
    ChangedFile,
    ContractSource,
    Evidence,
    Rule,
    RuleSelectionDecision,
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
        statement="公共 API 必须保持兼容。",
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
        rationale="公共函数已被重命名。",
        next_step="恢复兼容包装函数。",
    )
    return AuditReport(
        base_revision="base-sha",
        head_revision="head-sha",
        snapshot="head-sha",
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
        compiled_rule_count=2,
        rule_selection=(
            RuleSelectionDecision(
                rule_id="RW-NOT-APPLICABLE",
                status="not_applicable",
                reason=(
                    "Declared applies_to patterns match repository files but "
                    "not the current changes."
                ),
                statement="Documentation changes require review.",
                source_path="AGENTS.md",
                applies_to=("docs/**/*.md",),
            ),
        ),
    )


def test_json_is_canonical_and_markdown_is_rendered_from_the_same_report():
    report = _report()

    payload = json.loads(render_json(report))
    markdown = render_markdown(report)

    assert payload["summary"]["overall"] == "FAIL"
    assert payload["run"]["contracts_ref"] == "base"
    assert payload["contracts"][0]["kind"] == "repository_policy"
    assert payload["rule_selection"][0]["status"] == "not_applicable"
    assert payload["assessments"][0]["rule"]["quote"] == ("Public APIs must stay compatible.")
    assert payload["assessments"][0]["rule"]["source"] == {
        "path": "AGENTS.md",
        "revision": "base",
        "start_line": 3,
        "end_line": 3,
    }
    assert "# RepoWitness 审查报告" in markdown
    assert "## 规范来源" in markdown
    assert "规则：编译 2 · 适用 1 · 已评估 1" in markdown
    assert "## 规则适用性" in markdown
    assert "RW-NOT-APPLICABLE" in markdown
    assert "not_applicable" in markdown
    assert "Documentation changes require review." in markdown
    assert "FAIL" in markdown
    assert "AGENTS.md:3" in markdown
    assert "公共 API 必须保持兼容。" in markdown
    assert "公共函数已被重命名。" in markdown
    assert "恢复兼容包装函数。" in markdown
    assert "Public APIs must stay compatible." not in markdown


def test_worktree_contract_change_notice_names_the_selected_revision():
    report = replace(
        _report(),
        contracts_ref="worktree",
        contract_changes=(
            ChangedFile(path="AGENTS.md", status="modified"),
        ),
    )

    markdown = render_markdown(report)

    assert "本次审查显式使用 `worktree` 版本规范" in markdown
    assert "默认仍以 base 版本规范审查" not in markdown
