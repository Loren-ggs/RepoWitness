"""Import externally produced deterministic checks as provenance-bound evidence."""

from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from .evidence import EvidenceStore
from .repository import RepositoryView

_STATUSES = {"pass", "fail", "error", "skipped"}


def import_check_results(
    paths: tuple[Path, ...],
    repository: RepositoryView,
    evidence: EvidenceStore,
    *,
    include_untracked: bool,
    result_paths: tuple[Path, ...] | None = None,
) -> tuple[str, ...]:
    issues = []
    expected_snapshot = repository.snapshot_identity(
        include_untracked=include_untracked,
        exclude_paths=repository_result_paths(result_paths or paths, repository),
    )
    for path in paths:
        try:
            raw = path.expanduser().resolve().read_bytes()
            if len(raw) > 5_000_000:
                raise ValueError("file exceeds the 5 MB limit")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("root must be an object")
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


def import_native_results(
    *,
    junit_paths: tuple[Path, ...],
    sarif_paths: tuple[Path, ...],
    evidence_snapshot: str | None,
    repository: RepositoryView,
    evidence: EvidenceStore,
    include_untracked: bool,
    result_paths: tuple[Path, ...] | None = None,
) -> tuple[str, ...]:
    paths = junit_paths + sarif_paths
    if not paths:
        return ()
    expected_snapshot = repository.snapshot_identity(
        include_untracked=include_untracked,
        exclude_paths=repository_result_paths(result_paths or paths, repository),
    )
    if evidence_snapshot != expected_snapshot:
        return (
            "Native check evidence snapshot mismatch "
            f"(expected {expected_snapshot}, got {evidence_snapshot or 'missing'})",
        )

    issues = []
    for path in junit_paths:
        try:
            raw = _read_result(path)
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("DTD and entity declarations are not allowed")
            root = ElementTree.fromstring(raw)
            if _local_name(root.tag) not in {"testsuite", "testsuites"}:
                raise ValueError("root element must be testsuite or testsuites")
            testcases = [
                element
                for element in root.iter()
                if _local_name(element.tag) == "testcase"
            ]
            failures = []
            errors = []
            skipped = 0
            for testcase in testcases:
                name = ".".join(
                    part
                    for part in (
                        testcase.get("classname", "").strip(),
                        testcase.get("name", "").strip(),
                    )
                    if part
                ) or "unnamed"
                outcomes = {_local_name(child.tag) for child in testcase}
                if "error" in outcomes:
                    errors.append(name)
                elif "failure" in outcomes:
                    failures.append(name)
                elif "skipped" in outcomes:
                    skipped += 1
            status = (
                "error"
                if errors
                else "fail"
                if failures
                else "skipped"
                if testcases and skipped == len(testcases)
                else "pass"
            )
            failed = failures + errors
            _add_check(
                evidence,
                snapshot=expected_snapshot,
                name=f"junit:{path.name}",
                status=status,
                summary=(
                    f"JUnit: {len(testcases)} tests, {len(failures)} failure"
                    f"{'' if len(failures) == 1 else 's'}, {len(errors)} errors, "
                    f"{skipped} skipped"
                ),
                details=(
                    "Failed: " + ", ".join(failed[:100])
                    if failed
                    else "All discovered test cases passed."
                ),
            )
        except (
            OSError,
            UnicodeDecodeError,
            ElementTree.ParseError,
            ValueError,
        ) as exc:
            issues.append(f"JUnit result {path}: {exc}")
    for path in sarif_paths:
        try:
            payload = json.loads(_read_result(path).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != "2.1.0":
                raise ValueError("version must be '2.1.0'")
            runs = payload.get("runs")
            if not isinstance(runs, list) or not runs:
                raise ValueError("runs must be a non-empty array")
            if sum(
                len(run.get("results", ()))
                for run in runs
                if isinstance(run, dict)
                and isinstance(run.get("results", ()), list)
            ) > 10_000:
                raise ValueError("file exceeds the 10,000 result limit")
            validated = []
            for index, run in enumerate(runs):
                if not isinstance(run, dict):
                    raise ValueError(f"runs[{index}] must be an object")
                results = run.get("results", [])
                if not isinstance(results, list):
                    raise ValueError(f"runs[{index}].results must be an array")
                tool = run.get("tool") if isinstance(run.get("tool"), dict) else {}
                driver = (
                    tool.get("driver")
                    if isinstance(tool.get("driver"), dict)
                    else {}
                )
                tool_name = (
                    str(driver.get("name") or "").strip() or f"run-{index + 1}"
                )
                levels = {"error": 0, "warning": 0, "note": 0}
                details = []
                locations = []
                for result_index, result in enumerate(results):
                    if not isinstance(result, dict):
                        raise ValueError(
                            f"runs[{index}].results[{result_index}] must be an object"
                        )
                    level = str(result.get("level") or "warning").lower()
                    level = level if level in levels else "note"
                    if str(result.get("kind") or "fail") in {
                        "pass",
                        "notApplicable",
                        "informational",
                    }:
                        level = "note"
                    levels[level] += 1
                    location, line = _sarif_location(result)
                    if location:
                        locations.append(location)
                    rule_id = str(result.get("ruleId") or "unidentified")
                    message_payload = (
                        result.get("message")
                        if isinstance(result.get("message"), dict)
                        else {}
                    )
                    message = str(message_payload.get("text") or "").strip()
                    target = location or "unknown location"
                    if line is not None:
                        target += f":{line}"
                    details.append(
                        f"{rule_id} at {target}: {message[:300] or 'No message'}"
                    )
                execution_failed = any(
                    invocation.get("executionSuccessful") is False
                    for invocation in run.get("invocations", [])
                    if isinstance(invocation, dict)
                )
                status = (
                    "error"
                    if execution_failed
                    else "fail"
                    if levels["error"] or levels["warning"]
                    else "pass"
                )
                if execution_failed and not details:
                    details.append("Tool execution failed.")
                unique_locations = set(locations)
                validated.append(
                    {
                        "name": f"sarif:{tool_name}",
                        "status": status,
                        "summary": (
                            f"SARIF: {len(results)} result"
                            f"{'' if len(results) == 1 else 's'}, "
                            f"{levels['error']} error"
                            f"{'' if levels['error'] == 1 else 's'}, "
                            f"{levels['warning']} warnings, "
                            f"{levels['note']} notes"
                        ),
                        "details": "\n".join(details)[:20_000],
                        "path": (
                            next(iter(unique_locations))
                            if len(unique_locations) == 1
                            else None
                        ),
                    }
                )
            for check in validated:
                _add_check(evidence, snapshot=expected_snapshot, **check)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            issues.append(f"SARIF result {path}: {exc}")
    return tuple(issues)


def _read_result(path: Path) -> bytes:
    raw = path.expanduser().resolve().read_bytes()
    if len(raw) > 5_000_000:
        raise ValueError("file exceeds the 5 MB limit")
    return raw


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sarif_location(result: dict) -> tuple[str | None, int | None]:
    locations = result.get("locations")
    if not isinstance(locations, list) or not locations:
        return None, None
    location = locations[0] if isinstance(locations[0], dict) else {}
    physical = (
        location.get("physicalLocation")
        if isinstance(location.get("physicalLocation"), dict)
        else {}
    )
    artifact = (
        physical.get("artifactLocation")
        if isinstance(physical.get("artifactLocation"), dict)
        else {}
    )
    uri = str(artifact.get("uri") or "")
    parsed = urlsplit(uri)
    candidate = unquote(parsed.path).replace("\\", "/")
    pure = PurePosixPath(candidate)
    path = (
        pure.as_posix()
        if candidate
        and not parsed.scheme
        and not parsed.netloc
        and not pure.is_absolute()
        and ".." not in pure.parts
        and "\x00" not in candidate
        else None
    )
    region = (
        physical.get("region")
        if isinstance(physical.get("region"), dict)
        else {}
    )
    line = region.get("startLine")
    return path, line if isinstance(line, int) and line > 0 else None


def _add_check(
    evidence: EvidenceStore,
    *,
    snapshot: str,
    name: str,
    status: str,
    summary: str,
    details: str = "",
    path: str | None = None,
) -> None:
    evidence.add(
        kind="check_result",
        revision=snapshot,
        path=path,
        content=json.dumps(
            {
                "name": name,
                "status": status,
                "summary": summary,
                "details": details,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )


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
