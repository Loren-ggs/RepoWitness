"""Import externally produced deterministic checks as provenance-bound evidence."""

from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePosixPath

from .evidence import EvidenceStore
from .repository import RepositoryView

_STATUSES = {"pass", "fail", "error", "skipped"}


def import_check_results(
    paths: tuple[Path, ...],
    repository: RepositoryView,
    evidence: EvidenceStore,
    *,
    include_untracked: bool,
) -> tuple[str, ...]:
    issues = []
    expected_snapshot = repository.snapshot_identity(
        include_untracked=include_untracked,
        exclude_paths=repository_result_paths(paths, repository),
    )
    for path in paths:
        try:
            raw = path.expanduser().resolve().read_bytes()
            if len(raw) > 5_000_000:
                raise ValueError("file exceeds the 5 MB limit")
            payload = json.loads(raw.decode("utf-8"))
            if payload.get("schema_version") != "1":
                raise ValueError("schema_version must be '1'")
            snapshot = str(payload.get("snapshot", ""))
            if snapshot != expected_snapshot:
                raise ValueError(
                    "snapshot mismatch "
                    f"(expected {expected_snapshot}, got {snapshot or 'missing'})"
                )
            checks = payload.get("checks")
            if not isinstance(checks, list) or not checks:
                raise ValueError("checks must be a non-empty array")
            validated = []
            for index, check in enumerate(checks):
                if not isinstance(check, dict):
                    raise ValueError(f"checks[{index}] must be an object")
                name = str(check.get("name", "")).strip()
                status = str(check.get("status", "")).lower()
                summary = str(check.get("summary", "")).strip()
                if not name or status not in _STATUSES or not summary:
                    raise ValueError(
                        f"checks[{index}] requires name, summary, and a valid status"
                    )
                check_path = str(check.get("path") or "")
                if check_path:
                    pure = PurePosixPath(check_path.replace("\\", "/"))
                    if (
                        "\x00" in check_path
                        or pure.is_absolute()
                        or ".." in pure.parts
                    ):
                        raise ValueError(
                            f"checks[{index}].path must be repository-relative"
                        )
                content = json.dumps(
                    {
                        "name": name,
                        "status": status,
                        "summary": summary,
                        "details": str(check.get("details", "")),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                validated.append((check_path or None, content))
            for check_path, content in validated:
                evidence.add(
                    kind="check_result",
                    revision=snapshot,
                    path=check_path,
                    content=content,
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            issues.append(f"Check result {path}: {exc}")
    return tuple(issues)


def repository_result_paths(
    paths: tuple[Path, ...],
    repository: RepositoryView,
) -> tuple[str, ...]:
    relative = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved.is_relative_to(repository.root):
            relative.append(resolved.relative_to(repository.root).as_posix())
    return tuple(relative)
