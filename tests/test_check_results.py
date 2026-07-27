import json
import subprocess

from repowitness.check_results import import_check_results
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
