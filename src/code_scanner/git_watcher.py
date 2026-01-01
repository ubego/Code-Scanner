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

        # Get current commit
        try:
            state.current_commit = self._repo.head.commit.hexsha
        except Exception:
            state.current_commit = ""

        # Get changed files
        state.changed_files = self._get_changed_files()

        return state

    def _get_changed_files(self) -> list[ChangedFile]:
        """Get list of files with uncommitted changes.

        Returns:
            List of ChangedFile objects.
        """
        if self._repo is None:
            return []

        changed_files: list[ChangedFile] = []
        seen_paths: set[str] = set()

        # Base for comparison
        if self.commit_hash:
            base = self.commit_hash
        else:
            base = "HEAD"

        try:
            # Get staged changes (diff against index)
            staged_diff = self._repo.index.diff(base)
            for diff_item in staged_diff:
                path = diff_item.b_path or diff_item.a_path
                if path and path not in seen_paths:
                    status = "deleted" if diff_item.deleted_file else "staged"
                    changed_files.append(ChangedFile(path=path, status=status))
                    seen_paths.add(path)

            # Get unstaged changes (diff working tree against index)
            unstaged_diff = self._repo.index.diff(None)
            for diff_item in unstaged_diff:
                path = diff_item.b_path or diff_item.a_path
                if path and path not in seen_paths:
                    status = "deleted" if diff_item.deleted_file else "unstaged"
                    changed_files.append(ChangedFile(path=path, status=status))
                    seen_paths.add(path)

            # Get untracked files
            untracked = self._repo.untracked_files
            for path in untracked:
                if path not in seen_paths and not self._is_ignored(path):
                    changed_files.append(ChangedFile(path=path, status="untracked"))
                    seen_paths.add(path)

        except GitCommandError as e:
            logger.warning(f"Git command error: {e}")

        # Filter out ignored files and sort
        changed_files = [
            f for f in changed_files
            if not self._is_ignored(f.path)
        ]
        changed_files.sort(key=lambda f: f.path)

        return changed_files

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

    def get_file_content(self, file_path: str) -> Optional[str]:
        """Get the content of a file in the working directory.

        Args:
            file_path: Relative path to the file.

        Returns:
            File content as string, or None if file doesn't exist or is binary.
        """
        full_path = self.repo_path / file_path

        if not full_path.exists():
            return None

        try:
            with open(full_path, encoding="utf-8") as f:
                return f.read()
        except (UnicodeDecodeError, IOError):
            return None

    @property
    def is_connected(self) -> bool:
        """Check if connected to repository."""
        return self._repo is not None
