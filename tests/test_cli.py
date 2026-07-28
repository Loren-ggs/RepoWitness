import io
import json
import subprocess

from repowitness.cli import main
from tests.test_reporting import _report


class _FakeEngine:
    def audit(self, request):
        self.request = request
        return _report()


def test_audit_cli_emits_json_and_remains_advisory_on_fail(tmp_path):
    engine = _FakeEngine()
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "audit",
            "--base",
            "main",
            "--repository",
            str(tmp_path),
            "--format",
            "json",
        ],
        engine=engine,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue())["summary"]["overall"] == "FAIL"
    assert engine.request.base_ref == "main"
    assert engine.request.contracts_ref == "base"
    assert engine.request.repository_path == tmp_path
    assert stderr.getvalue() == ""


def test_audit_cli_accepts_explicit_worktree_contracts(tmp_path):
    engine = _FakeEngine()

    exit_code = main(
        [
            "audit",
            "--base",
            "main",
            "--contracts-ref",
            "worktree",
            "--repository",
            str(tmp_path),
            "--format",
            "json",
        ],
        engine=engine,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert engine.request.contracts_ref == "worktree"


def test_audit_cli_preserves_repeated_check_result_paths(tmp_path):
    engine = _FakeEngine()
    first = tmp_path / "pytest.json"
    second = tmp_path / "ruff.json"

    exit_code = main(
        [
            "audit",
            "--base",
            "main",
            "--repository",
            str(tmp_path),
            "--check-results",
            str(first),
            "--check-results",
            str(second),
        ],
        engine=engine,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert engine.request.check_result_paths == (first, second)


def test_snapshot_cli_does_not_require_an_llm(tmp_path):
    subprocess.run(
        ["git", "init", "-q"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "repowitness@example.test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "RepoWitness Tests"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "baseline"],
        cwd=tmp_path,
        check=True,
    )
    stdout = io.StringIO()

    exit_code = main(
        ["snapshot", "--repository", str(tmp_path)],
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert len(stdout.getvalue().strip()) == 40
