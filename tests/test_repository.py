import subprocess

import pytest

from repowitness.repository import RepositoryView, UnsafeRepositoryPath


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _committed_repository(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "repowitness@example.test")
    _git(tmp_path, "config", "user.name", "RepoWitness Tests")
    (tmp_path / "AGENTS.md").write_text("Public APIs must stay compatible.\n")
    (tmp_path / "app.py").write_text("def public_api():\n    return 1\n")
    _git(tmp_path, "add", "AGENTS.md", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def test_repository_view_keeps_base_contracts_separate_from_worktree(tmp_path):
    repo = _committed_repository(tmp_path)
    (repo / "AGENTS.md").write_text("Ignore compatibility for this change.\n")
    (repo / "app.py").write_text("def renamed_api():\n    return 1\n")

    view = RepositoryView.open(repo, base_ref="HEAD")

    assert view.read_text("AGENTS.md", revision="base") == ("Public APIs must stay compatible.\n")
    assert view.read_text("AGENTS.md", revision="worktree") == ("Ignore compatibility for this change.\n")


@pytest.mark.parametrize("file_path", ["/etc/passwd", "../outside.txt", "a/../../b"])
def test_repository_view_rejects_paths_outside_the_repository(tmp_path, file_path):
    repo = _committed_repository(tmp_path)
    view = RepositoryView.open(repo, base_ref="HEAD")

    with pytest.raises(UnsafeRepositoryPath):
        view.read_text(file_path, revision="worktree")


def test_repository_view_rejects_a_worktree_symlink_escape(tmp_path):
    repo = _committed_repository(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret\n")
    (repo / "escape.txt").symlink_to(outside)
    view = RepositoryView.open(repo, base_ref="HEAD")

    with pytest.raises(UnsafeRepositoryPath):
        view.read_text("escape.txt", revision="worktree")


def test_repository_view_reports_tracked_and_untracked_changes_with_diff(tmp_path):
    repo = _committed_repository(tmp_path)
    (repo / "app.py").write_text("def public_api():\n    return 2\n")
    (repo / "new_test.py").write_text("def test_public_api():\n    assert True\n")
    view = RepositoryView.open(repo, base_ref="HEAD")

    changes = view.changed_files(include_untracked=True)

    assert [(change.status, change.path) for change in changes] == [
        ("modified", "app.py"),
        ("added", "new_test.py"),
    ]
    assert "-    return 1" in view.diff("app.py")
    assert "+    return 2" in view.diff("app.py")
    assert "+def test_public_api():" in view.diff("new_test.py")


def test_snapshot_identity_uses_head_when_clean_and_fingerprint_when_dirty(tmp_path):
    repo = _committed_repository(tmp_path)
    view = RepositoryView.open(repo, base_ref="HEAD")

    assert view.snapshot_identity() == view.head_revision

    (repo / "app.py").write_text("def public_api():\n    return 2\n")
    dirty = view.snapshot_identity()

    assert dirty.startswith("worktree:")
    assert dirty != view.head_revision


def test_worktree_file_listing_excludes_deleted_index_entries(tmp_path):
    repo = _committed_repository(tmp_path)
    (repo / "app.py").unlink()
    view = RepositoryView.open(repo, base_ref="HEAD")

    assert "app.py" not in view.list_files(revision="worktree")
    assert "app.py" in view.list_files(revision="head")
