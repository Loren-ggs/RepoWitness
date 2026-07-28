import json
import subprocess

from repowitness.check_results import import_check_results, import_native_results
from repowitness.evidence import EvidenceStore
from repowitness.repository import RepositoryView


def _git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    return RepositoryView.open(tmp_path, base_ref="HEAD")


def test_check_result_import_requires_the_exact_snapshot(tmp_path):
    repository = _repository(tmp_path)
    result_path = tmp_path / "checks.json"
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "snapshot": repository.snapshot_identity(),
                "checks": [
                    {
                        "name": "pytest",
                        "status": "pass",
                        "summary": "12 tests passed",
                    }
                ],
            }
        )
    )
    evidence = EvidenceStore()

    issues = import_check_results(
        (result_path,),
        repository,
        evidence,
        include_untracked=True,
    )

    assert issues == ()
    assert evidence.records[0].kind == "check_result"
    assert '"status": "pass"' in evidence.records[0].content


def test_check_result_with_stale_snapshot_is_rejected(tmp_path):
    repository = _repository(tmp_path)
    result_path = tmp_path / "checks.json"
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "snapshot": "stale",
                "checks": [
                    {
                        "name": "pytest",
                        "status": "pass",
                        "summary": "12 tests passed",
                    }
                ],
            }
        )
    )
    evidence = EvidenceStore()

    issues = import_check_results(
        (result_path,),
        repository,
        evidence,
        include_untracked=False,
    )

    assert "snapshot mismatch" in issues[0]
    assert evidence.records == ()


def test_non_object_check_result_is_reported_without_importing_evidence(tmp_path):
    repository = _repository(tmp_path)
    result_path = tmp_path / "checks.json"
    result_path.write_text("[]", encoding="utf-8")
    evidence = EvidenceStore()

    issues = import_check_results(
        (result_path,),
        repository,
        evidence,
        include_untracked=True,
    )

    assert "root must be an object" in issues[0]
    assert evidence.records == ()


def test_junit_is_imported_as_snapshot_bound_check_result(tmp_path):
    repository = _repository(tmp_path)
    snapshot = repository.snapshot_identity()
    result_path = tmp_path / "junit.xml"
    result_path.write_text(
        """
<testsuite name="unit">
  <testcase classname="tests.test_app" name="test_ok" />
  <testcase classname="tests.test_app" name="test_failure">
    <failure message="expected 1, got 2" />
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )
    evidence = EvidenceStore()

    issues = import_native_results(
        junit_paths=(result_path,),
        sarif_paths=(),
        evidence_snapshot=snapshot,
        repository=repository,
        evidence=evidence,
        include_untracked=True,
    )

    assert issues == ()
    content = json.loads(evidence.records[0].content)
    assert evidence.records[0].kind == "check_result"
    assert evidence.records[0].revision == snapshot
    assert content == {
        "details": "Failed: tests.test_app.test_failure",
        "name": "junit:junit.xml",
        "status": "fail",
        "summary": "JUnit: 2 tests, 1 failure, 0 errors, 0 skipped",
    }


def test_sarif_is_imported_with_repository_relative_location(tmp_path):
    repository = _repository(tmp_path)
    snapshot = repository.snapshot_identity()
    result_path = tmp_path / "results.sarif"
    result_path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {"driver": {"name": "ExampleLint"}},
                        "results": [
                            {
                                "ruleId": "PY001",
                                "level": "error",
                                "message": {"text": "Unsafe call"},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {
                                                "uri": "src/app.py"
                                            },
                                            "region": {"startLine": 3},
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence = EvidenceStore()

    issues = import_native_results(
        junit_paths=(),
        sarif_paths=(result_path,),
        evidence_snapshot=snapshot,
        repository=repository,
        evidence=evidence,
        include_untracked=True,
    )

    assert issues == ()
    assert evidence.records[0].path == "src/app.py"
    assert json.loads(evidence.records[0].content) == {
        "details": "PY001 at src/app.py:3: Unsafe call",
        "name": "sarif:ExampleLint",
        "status": "fail",
        "summary": "SARIF: 1 result, 1 error, 0 warnings, 0 notes",
    }


def test_native_results_without_matching_snapshot_are_rejected(tmp_path):
    repository = _repository(tmp_path)
    result_path = tmp_path / "junit.xml"
    result_path.write_text(
        '<testsuite><testcase name="test_ok" /></testsuite>',
        encoding="utf-8",
    )
    evidence = EvidenceStore()

    issues = import_native_results(
        junit_paths=(result_path,),
        sarif_paths=(),
        evidence_snapshot=None,
        repository=repository,
        evidence=evidence,
        include_untracked=True,
    )

    assert "got missing" in issues[0]
    assert evidence.records == ()


def test_sarif_file_is_rejected_atomically_when_a_later_run_is_invalid(tmp_path):
    repository = _repository(tmp_path)
    snapshot = repository.snapshot_identity()
    result_path = tmp_path / "results.sarif"
    result_path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {"tool": {"driver": {"name": "Valid"}}, "results": []},
                    {"results": "invalid"},
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence = EvidenceStore()

    issues = import_native_results(
        junit_paths=(),
        sarif_paths=(result_path,),
        evidence_snapshot=snapshot,
        repository=repository,
        evidence=evidence,
        include_untracked=True,
    )

    assert "runs[1].results must be an array" in issues[0]
    assert evidence.records == ()
