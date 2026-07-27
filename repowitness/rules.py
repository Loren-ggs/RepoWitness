"""Deterministic rule applicability for changed repository paths."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from .domain import ChangedFile, Rule


def select_applicable_rules(
    rules: tuple[Rule, ...],
    changes: tuple[ChangedFile, ...],
) -> tuple[Rule, ...]:
    """Select rules whose source scope and declared globs cover a change."""
    selected = []
    for rule in rules:
        if any(_rule_applies_to_change(rule, change) for change in changes):
            selected.append(rule)
    return tuple(selected)


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
