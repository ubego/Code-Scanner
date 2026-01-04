"""Git integration for monitoring file changes."""

import logging
import os
from pathlib import Path
from typing import Optional

import git
from git import Repo, InvalidGitRepositoryError, GitCommandError

from .models import ChangedFile, GitState

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Git-related error."""

    pass


class GitWatcher:
    """Monitors a Git repository for uncommitted changes."""

    def __init__(self, repo_path: Path, commit_hash: Optional[str] = None):
        """Initialize the Git watcher.

        Args:
            repo_path: Path to the Git repository.
            commit_hash: Optional commit hash to compare against.
                        If None, compares against HEAD.

        Raises:
            GitError: If path is not a valid Git repository.
        """
        self.repo_path = repo_path.resolve()
        self.commit_hash = commit_hash
        self._repo: Optional[Repo] = None
        self._last_state: Optional[GitState] = None

    def connect(self) -> None:
        """Connect to the Git repository.

        Raises:
            GitError: If repository is invalid.
        """
        try:
            self._repo = Repo(self.repo_path)
            logger.info(f"Connected to Git repository: {self.repo_path}")

            # Validate commit hash if provided
            if self.commit_hash:
                try:
                    self._repo.commit(self.commit_hash)
                    logger.info(f"Using base commit: {self.commit_hash}")
                except Exception:
                    raise GitError(f"Invalid commit hash: {self.commit_hash}")

        except InvalidGitRepositoryError:
            raise GitError(
                f"Not a Git repository: {self.repo_path}\n"
                "Please run 'git init' or choose a directory that is a Git repository."
            )

    def get_state(self) -> GitState:
        """Get the current Git state.

        Returns:
            Current GitState with changed files and merge/rebase status.

        Raises:
            GitError: If repository is not connected.
        """
        if self._repo is None:
            raise GitError("Not connected to repository")

        state = GitState()

        # Check for merge/rebase in progress
        git_dir = Path(self._repo.git_dir)
        state.is_merging = (git_dir / "MERGE_HEAD").exists()
        state.is_rebasing = (
            (git_dir / "REBASE_HEAD").exists()
            or (git_dir / "rebase-merge").exists()
            or (git_dir / "rebase-apply").exists()
        )

        if state.is_conflict_resolution_in_progress:
            logger.info("Merge/rebase in progress, skipping change detection")
            return state

        # Get changed files
        state.changed_files = self._get_changed_files()

        return state

    def _get_changed_files(self) -> list[ChangedFile]:
        """Get list of files with uncommitted changes.

        Uses git status --porcelain for robust handling of submodules and edge cases.

        Returns:
            List of ChangedFile objects.
        """
        if self._repo is None:
            return []

        changed_files: list[ChangedFile] = []
        seen_paths: set[str] = set()

        try:
            # Use git status --porcelain for reliable output
            # This handles submodules correctly and provides consistent output
            status_output = self._repo.git.status("--porcelain", "--untracked-files=all")

            for line in status_output.splitlines():
                if not line or len(line) < 3:
                    continue

                # Format: XY filename
                # X = index status, Y = working tree status
                index_status = line[0]
                work_tree_status = line[1]
                path = line[3:]

                # Handle renamed files (format: "R  old -> new" or "R  old" -> "new")
                if " -> " in path:
                    # Split and take the new path (after rename)
                    parts = path.split(" -> ", 1)
                    path = parts[1] if len(parts) > 1 else parts[0]

                # Handle quoted paths (git quotes paths with special chars)
                path = self._unquote_path(path)

                if not path or path in seen_paths:
                    continue

                # Skip directories (submodules appear as directories)
                full_path = self.repo_path / path
                if full_path.is_dir():
                    continue

                # Determine status
                if index_status == "D" or work_tree_status == "D":
                    status = "deleted"
                elif index_status == "?" and work_tree_status == "?":
                    status = "untracked"
                elif index_status != " " and index_status != "?":
                    status = "staged"
                else:
                    status = "unstaged"

                # Skip ignored files
                if not self._is_ignored(path):
                    changed_files.append(ChangedFile(path=path, status=status))
                    seen_paths.add(path)

            # If comparing against a specific commit, also get files changed since that commit
            if self.commit_hash:
                try:
                    diff_output = self._repo.git.diff(
                        "--name-status", self.commit_hash, "--"
                    )
                    for line in diff_output.splitlines():
                        if not line:
                            continue
                        parts = line.split("\t", 1)
                        if len(parts) < 2:
                            continue
                        status_char, path = parts[0], parts[1]

                        # Handle renamed files
                        if "\t" in path:
                            path = path.split("\t")[1]

                        if path in seen_paths:
                            continue

                        if status_char == "D":
                            status = "deleted"
                        else:
                            status = "staged"

                        if not self._is_ignored(path):
                            changed_files.append(ChangedFile(path=path, status=status))
                            seen_paths.add(path)
                except GitCommandError as e:
                    logger.warning(f"Git diff error: {e}")

        except GitCommandError as e:
            logger.warning(f"Git command error: {e}")

        # Sort by path
        changed_files.sort(key=lambda f: f.path)

        return changed_files

    def _unquote_path(self, path: str) -> str:
        """Unquote a path from git status output.

        Git quotes paths with special characters (spaces, non-ASCII, etc.)
        using C-style escaping surrounded by double quotes.

        Args:
            path: Path string from git status.

        Returns:
            Unquoted path.
        """
        path = path.strip()

        # Check if path is quoted
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
            # Unescape common escape sequences
            path = path.replace("\\\\", "\x00")  # Temporarily escape backslashes
            path = path.replace("\\n", "\n")
            path = path.replace("\\t", "\t")
            path = path.replace('\\"', '"')
            path = path.replace("\x00", "\\")  # Restore backslashes

            # Handle octal escape sequences like \320\240 (UTF-8 bytes)
            # These need to be decoded as a group of bytes
            import re

            def decode_octal_sequences(s: str) -> str:
                """Decode consecutive octal escape sequences as UTF-8."""
                result = []
                i = 0
                while i < len(s):
                    if s[i] == '\\' and i + 3 < len(s) and s[i+1:i+4].isdigit():
                        # Collect consecutive octal sequences
                        byte_list = []
                        while i < len(s) and s[i] == '\\' and i + 3 < len(s):
                            octal_match = re.match(r'\\([0-7]{3})', s[i:])
                            if octal_match:
                                byte_list.append(int(octal_match.group(1), 8))
                                i += 4
                            else:
                                break
                        # Decode bytes as UTF-8
                        if byte_list:
                            try:
                                result.append(bytes(byte_list).decode('utf-8'))
                            except UnicodeDecodeError:
                                # Fallback to latin-1 for single-byte chars
                                result.append(bytes(byte_list).decode('latin-1'))
                    else:
                        result.append(s[i])
                        i += 1
                return ''.join(result)

            path = decode_octal_sequences(path)

        return path

    def _is_ignored(self, path: str) -> bool:
        """Check if a path is ignored by .gitignore.

        Args:
            path: Relative path to check.

        Returns:
            True if path should be ignored.
        """
        if self._repo is None:
            return False

        try:
            # Use git check-ignore command
            self._repo.git.check_ignore(path)
            return True
        except GitCommandError:
            # Non-zero exit means not ignored
            return False

    def has_changes_since(self, last_state: Optional[GitState]) -> bool:
        """Check if there are changes since the last state.

        Args:
            last_state: Previous GitState to compare against.

        Returns:
            True if there are new changes.
        """
        current_state = self.get_state()

        if last_state is None:
            return current_state.has_changes

        # Compare file lists
        current_paths = {f.path for f in current_state.changed_files}
        last_paths = {f.path for f in last_state.changed_files}

        return current_paths != last_paths


