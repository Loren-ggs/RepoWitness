"""Deterministic rule applicability for changed repository paths."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from .domain import ChangedFile, Rule, RuleSelectionDecision


@dataclass(frozen=True)
class RuleSelection:
    applicable_rules: tuple[Rule, ...]
    notices: tuple[str, ...]
    decisions: tuple["RuleSelectionDecision", ...]


def select_applicable_rules(
    rules: tuple[Rule, ...],
    changes: tuple[ChangedFile, ...],
) -> tuple[Rule, ...]:
    """Select rules whose source scope and declared globs cover a change."""
    return select_rules(rules, changes).applicable_rules


def select_rules(
    rules: tuple[Rule, ...],
    changes: tuple[ChangedFile, ...],
    *,
    known_paths: tuple[str, ...] = (),
) -> RuleSelection:
    """Select rules and conservatively recover unusable model path scopes."""
    selected = []
    notices = []
    decisions = []
    for rule in rules:
        scoped_changes = tuple(
            change
            for change in changes
            if any(
                _in_scope(path, rule.scope_path)
                for path in (change.path, change.old_path)
                if path
            )
        )
        if not scoped_changes:
            decisions.append(
                _decision(
                    rule,
                    status="not_applicable",
                    reason=(
                        "No current change is inside the contract source scope."
                    ),
                )
            )
            continue
        if any(
            _rule_applies_to_change(rule, change)
            for change in scoped_changes
        ):
            selected.append(rule)
            decisions.append(
                _decision(
                    rule,
                    status="applicable",
                    reason=(
                        "The rule scope and applies_to patterns cover a "
                        "current change."
                    ),
                )
            )
            continue
        scoped_known_paths = tuple(
            path
            for path in known_paths
            if _in_scope(path, rule.scope_path)
        )
        if rule.applies_to and scoped_known_paths and not any(
            _matches(path, pattern)
            for path in scoped_known_paths
            for pattern in rule.applies_to
        ):
            selected.append(replace(rule, applies_to=()))
            patterns = ", ".join(rule.applies_to)
            notices.append(
                f"Rule {rule.rule_id} applies_to patterns ({patterns}) match "
                "no known repository path and were treated as scope-wide."
            )
            decisions.append(
                _decision(
                    rule,
                    status="applicable_fallback",
                    reason=(
                        "Declared applies_to patterns match no known "
                        "repository path; the source scope was used "
                        "conservatively."
                    ),
                )
            )
            continue
        decisions.append(
            _decision(
                rule,
                status="not_applicable",
                reason=(
                    "Declared applies_to patterns match repository files but "
                    "not the current changes."
                ),
            )
        )
    return RuleSelection(
        applicable_rules=tuple(selected),
        notices=tuple(notices),
        decisions=tuple(decisions),
    )


def _decision(
    rule: Rule,
    *,
    status: str,
    reason: str,
) -> RuleSelectionDecision:
    return RuleSelectionDecision(
        rule_id=rule.rule_id,
        status=status,
        reason=reason,
        statement=rule.statement,
        source_path=rule.source_path,
        applies_to=rule.applies_to,
    )


def _rule_applies_to_change(rule: Rule, change: ChangedFile) -> bool:
    paths = tuple(path for path in (change.path, change.old_path) if path)
    scoped = tuple(path for path in paths if _in_scope(path, rule.scope_path))
    if not scoped:
        return False
    if not rule.applies_to:
        return True
    return any(
        _matches(path, pattern)
        for path in scoped
        for pattern in rule.applies_to
    )


def _in_scope(path: str, scope_path: str) -> bool:
    return not scope_path or path == scope_path or path.startswith(f"{scope_path}/")


def _matches(path: str, pattern: str) -> bool:
    normalized = pattern.strip().replace("\\", "/")
    if not normalized or normalized in {"*", "**", "**/*"}:
        return True
    relative = PurePosixPath(path)
    if relative.match(normalized) or fnmatch.fnmatchcase(path, normalized):
        return True
    if normalized.startswith("**/"):
        return relative.match(normalized[3:])
    return False
