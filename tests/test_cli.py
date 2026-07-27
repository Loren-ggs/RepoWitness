import io
import json

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
    assert engine.request.repository_path == tmp_path
    assert stderr.getvalue() == ""
