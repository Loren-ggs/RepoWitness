"""Canonical JSON serialization and Markdown rendering."""

from __future__ import annotations

import json

from .domain import AuditReport


def report_to_dict(report: AuditReport) -> dict:
    spans = {span.span_id: span for source in report.contracts for span in source.spans}
    rules = {rule.rule_id: rule for rule in report.rules}
    evidence = {record.handle: record for record in report.evidence}

    assessments = []
    for assessment in report.assessments:
        rule = rules[assessment.rule_id]
        span = spans[rule.source_span_id]
        assessments.append(
            {
                "rule": {
                    "rule_id": rule.rule_id,
                    "statement": rule.statement,
                    "quote": span.text,
                    "applies_to": list(rule.applies_to),
                    "source": {
                        "path": span.path,
                        "revision": span.revision,
                        "start_line": span.start_line,
                        "end_line": span.end_line,
                    },
                },
                "verdict": assessment.verdict,
                "evidence_handles": list(assessment.evidence_handles),
                "evidence": [_evidence_to_dict(evidence[handle]) for handle in assessment.evidence_handles if handle in evidence],
                "rationale": assessment.rationale,
                "next_step": assessment.next_step,
                "limitations": list(assessment.limitations),
            }
        )

    return {
        "schema_version": report.schema_version,
        "run": {
            "base_revision": report.base_revision,
            "head_revision": report.head_revision,
            "model": report.model,
            "mode": report.mode,
        },
        "summary": {
            "overall": report.overall,
            "counts": report.counts,
            "rules_discovered": len(report.rules),
            "rules_evaluated": len(report.assessments),
        },
        "changes": [
            {
                "path": change.path,
                "status": change.status,
                "old_path": change.old_path,
                "binary": change.binary,
            }
            for change in report.changes
        ],
        "contracts": [
            {
                "path": source.path,
                "revision": source.revision,
                "spans": [
                    {
                        "span_id": span.span_id,
                        "start_line": span.start_line,
                        "end_line": span.end_line,
                        "text": span.text,
                    }
                    for span in source.spans
                ],
            }
            for source in report.contracts
        ],
        "assessments": assessments,
        "issues": list(report.issues),
    }


def render_json(report: AuditReport) -> str:
    return json.dumps(
        report_to_dict(report),
        ensure_ascii=False,
        indent=2,
    )


def render_markdown(report: AuditReport) -> str:
    payload = report_to_dict(report)
    summary = payload["summary"]
    counts = summary["counts"]
    lines = [
        "# RepoWitness 审查报告",
        "",
        f"**总体结论：{summary['overall']}**",
        "",
        (f"PASS {counts['PASS']} · FAIL {counts['FAIL']} · WARN {counts['WARN']} · UNVERIFIED {counts['UNVERIFIED']}"),
        "",
        f"- Base：`{payload['run']['base_revision']}`",
        f"- Head：`{payload['run']['head_revision']}`",
        f"- Model：`{payload['run']['model']}`",
        f"- Mode：`{payload['run']['mode']}`",
    ]

    if payload["issues"]:
        lines.extend(["", "## 审查限制", ""])
        lines.extend(f"- {issue}" for issue in payload["issues"])

    lines.extend(["", "## 规则结论", ""])
    if not payload["assessments"]:
        lines.append("没有可评估的规则。")

    for assessment in payload["assessments"]:
        rule = assessment["rule"]
        source = rule["source"]
        location = (
            f"{source['path']}:{source['start_line']}"
            if source["start_line"] == source["end_line"]
            else (f"{source['path']}:{source['start_line']}-{source['end_line']}")
        )
        lines.extend(
            [
                f"### {assessment['verdict']} · {rule['rule_id']}",
                "",
                f"> {rule['quote']}",
                "",
                f"- 规则来源：`{location}`（{source['revision']}）",
                f"- 判断依据：{assessment['rationale']}",
                f"- 下一步：{assessment['next_step']}",
            ]
        )
        if assessment["evidence"]:
            lines.append("- 证据：")
            for record in assessment["evidence"]:
                target = record["path"] or record["kind"]
                lines.append(f"  - `{record['handle']}` · `{target}` · `{record['revision']}`")
        if assessment["limitations"]:
            lines.append("- 限制：" + "；".join(assessment["limitations"]))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _evidence_to_dict(record) -> dict:
    return {
        "handle": record.handle,
        "kind": record.kind,
        "path": record.path,
        "revision": record.revision,
        "start_line": record.start_line,
        "end_line": record.end_line,
        "content": record.content,
    }
