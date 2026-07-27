"""Read-only access to immutable Git snapshots and the current worktree."""

from __future__ import annotations

import os
import subprocess
import hashlib
from difflib import unified_diff
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .domain import ChangedFile


class RepositoryError(RuntimeError):
    """Raised when a trustworthy repository snapshot cannot be produced."""


class UnsafeRepositoryPath(ValueError):
    """Raised when a requested path can escape the audited repository."""


_GIT_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",
}


@dataclass(frozen=True)
class RepositoryView:
    """A read-only view of base, head, and worktree repository revisions."""

    root: Path
    base_revision: str
    head_revision: str

    @classmethod
    def open(cls, path: str | Path, base_ref: str) -> "RepositoryView":
        requested = Path(path).expanduser().resolve()
        top = cls._run_git(requested, "rev-parse", "--show-toplevel").strip()
        root = Path(top).resolve()
        base = cls._run_git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}").strip()
        head = cls._run_git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
        return cls(root=root, base_revision=base, head_revision=head)

    def read_text(
        self,
        file_path: str,
        *,
        revision: str = "head",
        max_bytes: int = 1_000_000,
    ) -> str:
        relative = self._safe_relative_path(file_path)
        if revision == "worktree":
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root):
                raise UnsafeRepositoryPath(f"path escapes repository: {file_path}")
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise RepositoryError(f"cannot read {file_path}: {exc}") from exc
        else:
            ref = self._revision(revision)
            spec = f"{ref}:{relative.as_posix()}"
            data = self._run_git_bytes(self.root, "cat-file", "blob", spec)

        if len(data) > max_bytes:
            raise RepositoryError(f"{file_path} exceeds the {max_bytes}-byte read limit")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryError(f"{file_path} is not UTF-8 text") from exc
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def changed_files(self, *, include_untracked: bool = True) -> list[ChangedFile]:
        raw = self._run_git_bytes(
            self.root,
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            self.base_revision,
            "--",
        )
        fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
        changes: list[ChangedFile] = []
        index = 0
        status_names = {
            "A": "added",
            "D": "deleted",
            "M": "modified",
            "T": "modified",
            "U": "modified",
        }
        while index < len(fields) and fields[index]:
            raw_status = fields[index]
            index += 1
            code = raw_status[:1]
            if code in {"R", "C"}:
                old_path, new_path = fields[index], fields[index + 1]
                index += 2
                changes.append(
                    ChangedFile(
                        path=new_path,
                        old_path=old_path,
                        status="renamed" if code == "R" else "added",
                    )
                )
            else:
                path = fields[index]
                index += 1
                changes.append(ChangedFile(path=path, status=status_names.get(code, "modified")))

        if include_untracked:
            untracked = self._run_git_bytes(
                self.root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            )
            for path in untracked.decode("utf-8", errors="surrogateescape").split("\0"):
                if path:
                    changes.append(ChangedFile(path=path, status="added"))

        return sorted(changes, key=lambda change: change.path)

    def list_files(self, *, revision: str = "head") -> tuple[str, ...]:
        """List repository files without traversing outside the selected snapshot."""
        if revision == "worktree":
            raw = self._run_git_bytes(
                self.root,
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            )
        else:
            ref = self._revision(revision)
            raw = self._run_git_bytes(
                self.root,
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                ref,
                "--",
            )
        paths = raw.decode("utf-8", errors="surrogateescape").split("\0")
        if revision != "worktree":
            return tuple(sorted(path for path in paths if path))

        existing = []
        for path in paths:
            if not path:
                continue
            relative = self._safe_relative_path(path)
            resolved = (self.root / relative).resolve()
            if resolved.is_relative_to(self.root) and resolved.is_file():
                existing.append(path)
        return tuple(sorted(existing))

    def snapshot_identity(
        self,
        *,
        include_untracked: bool = True,
        exclude_paths: tuple[str, ...] = (),
    ) -> str:
        """Identify the exact reviewed worktree, or HEAD when it is clean."""
        safe_exclusions = tuple(
            self._safe_relative_path(path).as_posix() for path in exclude_paths
        )
        pathspecs = [".", *(f":(exclude){path}" for path in safe_exclusions)]
        diff = self._run_git_bytes(
            self.root,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--ignore-submodules=all",
            "HEAD",
            "--",
            *pathspecs,
        )

        paths = []
        if include_untracked:
            untracked = self._run_git_bytes(
                self.root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            )
            paths = sorted(
                path
                for path in untracked.decode(
                    "utf-8",
                    errors="surrogateescape",
                ).split("\0")
                if path and path not in safe_exclusions
            )
        if not diff and not paths:
            return self.head_revision

        digest = hashlib.sha256()
        digest.update(self.head_revision.encode("ascii"))
        digest.update(b"\0")
        digest.update(diff)
        if include_untracked:
            for path in paths:
                relative = self._safe_relative_path(path)
                resolved = (self.root / relative).resolve()
                if not resolved.is_relative_to(self.root) or not resolved.is_file():
                    raise RepositoryError(
                        f"cannot fingerprint unsafe untracked path: {path}"
                    )
                try:
                    data = resolved.read_bytes()
                except OSError as exc:
                    raise RepositoryError(
                        f"cannot fingerprint untracked path {path}: {exc}"
                    ) from exc
                digest.update(path.encode("utf-8", errors="surrogateescape"))
                digest.update(b"\0")
                digest.update(hashlib.sha256(data).digest())
        return f"worktree:{digest.hexdigest()}"

    def diff(self, file_path: str, *, context_lines: int = 20) -> str:
        relative = self._safe_relative_path(file_path)
        tracked = self._run_git(
            self.root,
            "ls-files",
            "--error-unmatch",
            "--",
            relative.as_posix(),
            allow_failure=True,
        )
        if tracked is None:
            text = self.read_text(relative.as_posix(), revision="worktree")
            lines = text.splitlines(keepends=True)
            return "".join(
                unified_diff(
                    [],
                    lines,
                    fromfile="/dev/null",
                    tofile=f"b/{relative.as_posix()}",
                    n=context_lines,
                )
            )
        return (
            self._run_git(
                self.root,
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=all",
                f"--unified={context_lines}",
                self.base_revision,
                "--",
                relative.as_posix(),
            )
            or ""
        )

    def _revision(self, revision: str) -> str:
        if revision == "base":
            return self.base_revision
        if revision == "head":
            return self.head_revision
        raise RepositoryError(f"unsupported revision: {revision}")

    @staticmethod
    def _safe_relative_path(file_path: str) -> PurePosixPath:
        if "\x00" in file_path:
            raise UnsafeRepositoryPath("path contains a NUL byte")
        path = PurePosixPath(file_path.replace("\\", "/"))
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise UnsafeRepositoryPath(f"path must stay inside repository: {file_path}")
        return path

    @staticmethod
    def _run_git(cwd: Path, *args: str, allow_failure: bool = False) -> str | None:
        data = RepositoryView._run_git_bytes(cwd, *args, allow_failure=allow_failure)
        if data is None:
            return None
        return data.decode("utf-8", errors="strict")

    @staticmethod
    def _run_git_bytes(cwd: Path, *args: str, allow_failure: bool = False) -> bytes | None:
        env = os.environ.copy()
        env.update(_GIT_ENV)
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=cwd,
                env=env,
                check=not allow_failure,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = ""
            if isinstance(exc, subprocess.CalledProcessError):
                detail = exc.stderr.decode("utf-8", errors="replace").strip()
            message = f"git {' '.join(args)} failed"
            if detail:
                message += f": {detail}"
            raise RepositoryError(message) from exc
        if allow_failure and completed.returncode:
            return None
        return completed.stdout
