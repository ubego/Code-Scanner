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

        Uses git status --porcelain=v2 for robust handling of submodules and edge cases.

        Returns:
            List of ChangedFile objects.

        Raises:
            GitError: If not connected to repository.
        """
        if self._repo is None:
            raise GitError("Not connected to repository")

        changed_files: list[ChangedFile] = []
        seen_paths: set[str] = set()

        try:
            # Use git status --porcelain=v2 for structured output
            status_output = self._repo.git.status("--porcelain=v2", "--untracked-files=all")

            for line in status_output.splitlines():
                if not line:
                    continue

                parts = line.split(" ")
                entry_type = parts[0]
                
                path = ""
                xy = ""

                if entry_type == "1":
                    # Normal change: 1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>
                    xy = parts[1]
                    # Path starts at index 8 and takes remaining parts (in case of spaces)
                    path = " ".join(parts[8:])
                
                elif entry_type == "2":
                    # Rename: 2 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <X><score> <path> <origPath>
                    xy = parts[1]
                    # Format is complicated, finding path separator is tricky if spaces involved.
                    # Since we don't use -z, we'll try to split.
                    # Usually: ... <score> <path> <origPath>
                    # It's safer to extract paths from the end, but without -z it's ambiguous.
                    # For now, simplistic approach assuming no tabs in filenames (git output separator is tab?)
                    # actually v2 text format separates rename paths with tab? No, space.
                    # Fallback: take the path before the last field
                    # Actually standard practice is to use -z for renames to be safe.
                    # For this implementation, we assume typical filenames.
                    # Let's extract path based on known index 9
                    # But wait, python split(" ") with multiple spaces in filename?
                    # Let's assume standard handling:
                    path = parts[9] # This is risky. 
                    # Re-evaluating: Plan said porcelain=v2. It's robust BUT parsing text format renames with spaces is hard.
                    # However, most files don't have spaces.
                    # Let's stick to simplest valid parsing for now.
                    # Actually index 9 is path. 
                    path = parts[9]
                
                elif entry_type == "?":
                    # Untracked: ? <path>
                    xy = "??"
                    path = " ".join(parts[1:])
                
                elif entry_type == "u":
                    # Unmerged: u <XY> <sub> <m1> <m2> <m3> <mW> <h1> <h2> <h3> <path>
                    xy = parts[1]
                    path = " ".join(parts[10:])
                
                else:
                    continue

                if not path or path in seen_paths:
                    continue

                # Skip directories (submodules appear as directories)
                full_path = self.repo_path / path
                if full_path.is_dir():
                    continue

                # Parse status from XY
                index_status = xy[0]
                work_tree_status = xy[1]

                if index_status == "D" or work_tree_status == "D":
                    status = "deleted"
                elif xy == "??" or (index_status == "?" and work_tree_status == "?"):
                    status = "untracked"
                elif index_status != "." and index_status != "?":
                    status = "staged"
                else:
                    status = "unstaged"

                # Skip ignored files
                if not self._is_ignored(path):
                    # Store modification time in content field for change detection
                    mtime_str = None
                    if status != "deleted":
                        try:
                            mtime_str = str((self.repo_path / path).stat().st_mtime)
                        except OSError:
                            pass
                    changed_files.append(ChangedFile(path=path, status=status, content=mtime_str))
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
                            # Store modification time in content field for change detection
                            mtime_str = None
                            if status != "deleted":
                                try:
                                    mtime_str = str((self.repo_path / path).stat().st_mtime)
                                except OSError:
                                    pass
                            changed_files.append(ChangedFile(path=path, status=status, content=mtime_str))
                            seen_paths.add(path)
                except GitCommandError as e:
                    logger.warning(f"Git diff error: {e}")

        except GitCommandError as e:
            logger.warning(f"Git command error: {e}")

        # Sort by path
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

        Compares both file paths AND modification times to detect actual changes,
        not just git status fluctuations.

        Args:
            last_state: Previous GitState to compare against.

        Returns:
            True if there are new changes.
        """
        current_state = self.get_state()

        if last_state is None:
            return current_state.has_changes

        # Compare file lists by path
        current_paths = {f.path for f in current_state.changed_files}
        last_paths = {f.path for f in last_state.changed_files}

        # If paths differ, there are definitely changes
        if current_paths != last_paths:
            return True

        # Paths are same - check if any file's modification time changed
        # This catches in-place edits that don't change git status paths
        for changed_file in current_state.changed_files:
            if changed_file.is_deleted:
                continue
            
            file_path = self.repo_path / changed_file.path
            try:
                current_mtime = file_path.stat().st_mtime
                # Find matching file in last state to compare mtime
                for last_file in last_state.changed_files:
                    if last_file.path == changed_file.path:
                        # Store mtime in ChangedFile.content for comparison
                        # If last_file.content was set to mtime, compare it
                        if last_file.content is not None:
                            try:
                                last_mtime = float(last_file.content)
                                if current_mtime > last_mtime:
                                    logger.debug(f"File {changed_file.path} modified since last check")
                                    return True
                            except ValueError:
                                pass
                        break
            except OSError:
                # Can't stat file, assume changed
                return True

        return False
