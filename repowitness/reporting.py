"""Canonical JSON serialization and Markdown rendering."""

from __future__ import annotations

import json
import re

from .domain import AuditReport

_VERDICT_DISPLAY_ORDER = ("FAIL", "WARN", "UNVERIFIED", "PASS")
_VERDICT_PRESENTATION = {
    "FAIL": ("❌", "不符合", True),
    "WARN": ("⚠️", "需关注", True),
    "UNVERIFIED": ("❔", "未验证", False),
    "PASS": ("✅", "符合", False),
}
_DIFF_HUNK = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(?P<line>\d+)(?:,\d+)? @@"
)


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
            "snapshot": report.snapshot,
            "contracts_ref": report.contracts_ref,
            "model": report.model,
            "mode": report.mode,
        },
        "summary": {
            "overall": report.overall,
            "counts": report.counts,
            "rules_discovered": (
                report.compiled_rule_count
                if report.compiled_rule_count is not None
                else len(report.rules)
            ),
            "rules_applicable": len(report.rules),
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
                "kind": source.kind,
                "scope_path": source.scope_path,
                "priority": source.priority,
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
        "contract_changes": [
            {
                "path": change.path,
                "status": change.status,
                "old_path": change.old_path,
            }
            for change in report.contract_changes
        ],
        "conflicts": [
            {
                "conflict_id": conflict.conflict_id,
                "source_span_ids": list(conflict.source_span_ids),
                "description": conflict.description,
                "resolution": conflict.resolution,
                "resolved": conflict.resolved,
            }
            for conflict in report.conflicts
        ],
        "rule_selection": [
            {
                "rule_id": decision.rule_id,
                "status": decision.status,
                "reason": decision.reason,
                "statement": decision.statement,
                "source_path": decision.source_path,
                "applies_to": list(decision.applies_to),
            }
            for decision in report.rule_selection
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
    overall_icon = _VERDICT_PRESENTATION[summary["overall"]][0]
    lines = [
        "# 🛡️ RepoWitness 审查报告",
        "",
        f"## {overall_icon} 总体结论：{summary['overall']}",
        "",
        " · ".join(
            f"{_VERDICT_PRESENTATION[verdict][0]} {verdict} {counts[verdict]}"
            for verdict in _VERDICT_DISPLAY_ORDER
        ),
        (
            f"📏 规则：编译 {summary['rules_discovered']} · "
            f"适用 {summary['rules_applicable']} · "
            f"已评估 {summary['rules_evaluated']}"
        ),
        "",
        "<details>",
        "<summary>⚙️ <strong>审查上下文</strong></summary>",
        "",
        f"- Base：`{payload['run']['base_revision']}`",
        f"- Head：`{payload['run']['head_revision']}`",
        f"- Snapshot：`{payload['run']['snapshot']}`",
        f"- 规范版本：`{payload['run']['contracts_ref']}`",
        f"- Model：`{payload['run']['model']}`",
        f"- Mode：`{payload['run']['mode']}`",
        "",
        "</details>",
    ]

    lines.extend(
        [
            "",
            "<details>",
            f"<summary>📚 <strong>规范来源 · {len(payload['contracts'])} 份</strong></summary>",
            "",
        ]
    )
    if payload["contracts"]:
        for source in payload["contracts"]:
            scope = source["scope_path"] or "全仓库"
            lines.append(
                f"- `{source['path']}` · {source['kind']} · "
                f"`{source['revision']}` · 作用域 `{scope}`"
            )
    else:
        lines.append("未发现可用的仓库规范文档。")
    lines.extend(["", "</details>"])

    if payload["contract_changes"]:
        lines.extend(["", "## 📝 本次规范文档变更", ""])
        if payload["run"]["contracts_ref"] == "base":
            lines.append(
                "以下变更会单独提示；本次仍以 base 版本规范审查代码变更。"
            )
        else:
            lines.append(
                "本次审查显式使用 "
                f"`{payload['run']['contracts_ref']}` 版本规范；"
                "其中可能包含本次变更新增或修改的规则。"
            )
        lines.extend(
            f"- `{change['path']}`（{change['status']}）"
            for change in payload["contract_changes"]
        )

    if payload["conflicts"]:
        lines.extend(["", "## 🚨 规范冲突", ""])
        for conflict in payload["conflicts"]:
            state = "已按优先级解析" if conflict["resolved"] else "需要人工确认"
            lines.extend(
                [
                    f"- **{conflict['conflict_id']} · {state}**",
                    f"  - 冲突：{conflict['description']}",
                    f"  - 处理：{conflict['resolution']}",
                ]
            )

    noteworthy_selection = [
        decision
        for decision in payload["rule_selection"]
        if decision["status"] != "applicable"
    ]
    if noteworthy_selection:
        lines.extend(
            [
                "",
                "<details>",
                (
                    "<summary>🧭 <strong>规则适用性 · "
                    f"{len(noteworthy_selection)} 项</strong></summary>"
                ),
                "",
            ]
        )
        lines.extend(
            f"- `{decision['rule_id']}` · `{decision['status']}` · "
            f"{decision['statement']}（`{decision['source_path']}`）"
            f"\n  - {decision['reason']}"
            for decision in noteworthy_selection
        )
        lines.extend(["", "</details>"])

    if payload["issues"]:
        lines.extend(["", "## 🚧 审查限制", ""])
        lines.extend(f"- {issue}" for issue in payload["issues"])

    lines.extend(["", "## 🔎 规则结论", ""])
    if not payload["assessments"]:
        lines.append("没有可评估的规则。")

    for verdict in _VERDICT_DISPLAY_ORDER:
        verdict_assessments = [
            item for item in payload["assessments"] if item["verdict"] == verdict
        ]
        if not verdict_assessments:
            continue
        icon, label, expanded = _VERDICT_PRESENTATION[verdict]
        lines.extend(
            [
                f"<details{' open' if expanded else ''}>",
                (
                    f"<summary>{icon} <strong>{label}（{verdict}）· "
                    f"{len(verdict_assessments)} 项</strong></summary>"
                ),
                "",
            ]
        )
        for assessment in verdict_assessments:
            rule = assessment["rule"]
            source = rule["source"]
            rule_location = (
                f"{source['path']}:{source['start_line']}"
                if source["start_line"] == source["end_line"]
                else (f"{source['path']}:{source['start_line']}-{source['end_line']}")
            )
            finding_location = _finding_location(assessment["evidence"])
            lines.extend(
                [
                    f"### {icon} {verdict} · `{finding_location}`",
                    "",
                    f"> {rule['statement']}",
                    "",
                    f"- 📌 规则来源：`{rule_location}`（{source['revision']}）",
                    f"- 💡 判断依据：{assessment['rationale']}",
                    f"- 🛠️ 下一步：{assessment['next_step']}",
                    "- 🔗 证据：",
                ]
            )
            if assessment["evidence"]:
                for record in assessment["evidence"]:
                    target = (
                        _evidence_location(record)
                        or record["path"]
                        or record["kind"]
                    )
                    lines.append(
                        f"  - `{record['handle']}` · `{target}` · `{record['revision']}`"
                    )
            else:
                lines.append("  - 无可用证据")
            lines.append(f"- 🆔 规则编号：`{rule['rule_id']}`")
            if assessment["limitations"]:
                lines.append("- ⚠️ 限制：" + "；".join(assessment["limitations"]))
            lines.append("")
        lines.extend(["</details>", ""])

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


def _finding_location(evidence: list[dict]) -> str:
    for record in evidence:
        if record["kind"] == "diff" and (
            location := _evidence_location(record)
        ):
            return location
    for record in evidence:
        if location := _evidence_location(record):
            return location
    for record in evidence:
        if record["path"]:
            return f"{record['path']}（未定位行号）"
    return "未定位到具体代码行"


def _evidence_location(record: dict) -> str | None:
    path = record["path"]
    if not path:
        return None
    if record["start_line"] is not None:
        end_line = record["end_line"]
        if end_line is not None and end_line != record["start_line"]:
            return f"{path}:{record['start_line']}-{end_line}"
        return f"{path}:{record['start_line']}"
    if record["kind"] == "diff":
        if line := _first_changed_line(record["content"]):
            return f"{path}:{line}"
    return None


def _first_changed_line(content: str) -> int | None:
    new_line = None
    for line in content.splitlines():
        if match := _DIFF_HUNK.match(line):
            new_line = int(match.group("line"))
        elif new_line is not None:
            if line.startswith(("+", "-")):
                return new_line
            if not line.startswith("\\"):
                new_line += 1
    return None
