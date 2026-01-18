"""Issue tracking and state management."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import Issue, IssueStatus

logger = logging.getLogger(__name__)


class IssueTracker:
    """Manages detected issues in memory with deduplication and resolution tracking."""

    def __init__(self):
        """Initialize the issue tracker."""
        self._issues: list[Issue] = []
        self._changed: bool = False
        # File-based indices for O(1) lookup instead of O(n) iteration
        self._open_by_file: dict[str, list[Issue]] = {}
        self._resolved_by_file: dict[str, list[Issue]] = {}

    def _add_to_index(self, issue: Issue) -> None:
        """Add an issue to the appropriate index based on its status.
        
        Args:
            issue: The issue to index.
        """
        index = self._open_by_file if issue.status == IssueStatus.OPEN else self._resolved_by_file
        index.setdefault(issue.file_path, []).append(issue)

    def _remove_from_index(self, issue: Issue, from_status: IssueStatus) -> None:
        """Remove an issue from an index.
        
        Args:
            issue: The issue to remove.
            from_status: The status index to remove from.
        """
        index = self._open_by_file if from_status == IssueStatus.OPEN else self._resolved_by_file
        if issue.file_path in index and issue in index[issue.file_path]:
            index[issue.file_path].remove(issue)

    def _move_issue_status(self, issue: Issue, from_status: IssueStatus, to_status: IssueStatus) -> None:
        """Move an issue between status indices.
        
        Args:
            issue: The issue to move.
            from_status: The current status (index to remove from).
            to_status: The new status (index to add to).
        """
        self._remove_from_index(issue, from_status)
        issue.status = to_status
        self._add_to_index(issue)
        self._changed = True

    @property
    def issues(self) -> list[Issue]:
        """Get all tracked issues."""
        return self._issues.copy()

    @property
    def open_issues(self) -> list[Issue]:
        """Get all open issues."""
        return [i for i in self._issues if i.status == IssueStatus.OPEN]

    @property
    def resolved_issues(self) -> list[Issue]:
        """Get all resolved issues."""
        return [i for i in self._issues if i.status == IssueStatus.RESOLVED]

    def add_issue(self, issue: Issue) -> bool:
        """Add a new issue, handling deduplication.

        If an identical issue exists (same file, similar code/description),
        updates the line number instead of creating a duplicate.

        Args:
            issue: The issue to add.

        Returns:
            True if a new issue was added, False if deduplicated.
        """
        file_path = issue.file_path
        
        # Check for existing matching OPEN issue (O(1) file lookup)
        for existing in self._open_by_file.get(file_path, []):
            if existing.matches(issue):
                # Update line number if different
                if existing.line_number != issue.line_number:
                    logger.debug(
                        f"Issue moved: {existing.file_path} "
                        f"L{existing.line_number} -> L{issue.line_number}"
                    )
                    existing.line_number = issue.line_number
                    existing.timestamp = issue.timestamp
                    self._changed = True
                return False

        # Check for existing matching RESOLVED issue (O(1) file lookup)
        for existing in self._resolved_by_file.get(file_path, []):
            if existing.matches(issue):
                # Reopen the issue - move from resolved to open index
                logger.info(f"Reopening resolved issue: {existing.file_path}")
                existing.line_number = issue.line_number
                existing.timestamp = issue.timestamp
                self._move_issue_status(existing, IssueStatus.RESOLVED, IssueStatus.OPEN)
                return False

        # Add new issue
        logger.info(f"New issue: {issue.file_path}:{issue.line_number}")
        self._issues.append(issue)
        self._add_to_index(issue)
        self._changed = True
        return True

    def add_issues(self, issues: list[Issue]) -> int:
        """Add multiple issues.

        Args:
            issues: List of issues to add.

        Returns:
            Number of new issues added (not deduplicated).
        """
        new_count = 0
        for issue in issues:
            if self.add_issue(issue):
                new_count += 1
        return new_count

    def resolve_issues_for_file(self, file_path: str) -> int:
        """Mark all open issues for a file as resolved.

        Used when a file is deleted or when issues are no longer detected.

        Args:
            file_path: Path to the file.

        Returns:
            Number of issues resolved.
        """
        # O(1) file lookup instead of O(n) full list iteration
        open_issues = self._open_by_file.get(file_path, [])
        resolved_count = len(open_issues)
        
        for issue in open_issues:
            issue.status = IssueStatus.RESOLVED
            self._changed = True
            logger.info(f"Resolved issue: {file_path}:{issue.line_number}")
        
        # Move all issues from open to resolved index
        if resolved_count > 0:
            if file_path not in self._resolved_by_file:
                self._resolved_by_file[file_path] = []
            self._resolved_by_file[file_path].extend(open_issues)
            self._open_by_file[file_path] = []
        
        return resolved_count

    def update_from_scan(
        self,
        new_issues: list[Issue],
        scanned_files: list[str],
    ) -> tuple[int, int]:
        """Update tracker from a scan result.

        Adds new issues and resolves issues that are no longer detected
        in the scanned files.
        
        IMPORTANT: Only resolves issues for files in scanned_files.
        This prevents LLM non-determinism from incorrectly resolving issues
        when file content hasn't actually changed.

        Args:
            new_issues: Issues detected in this scan.
            scanned_files: List of files that were actually scanned/changed.
                          Only these files will have issues resolved.

        Returns:
            Tuple of (new_issues_count, resolved_count).
        """
        # Convert to set for O(1) lookup
        scanned_files_set = set(scanned_files)
        
        # Group new issues by file
        new_by_file: dict[str, list[Issue]] = {}
        for issue in new_issues:
            if issue.file_path not in new_by_file:
                new_by_file[issue.file_path] = []
            new_by_file[issue.file_path].append(issue)

        # Resolve issues for scanned files that have no new issues
        resolved_count = 0
        for file_path in scanned_files:
            if file_path not in new_by_file:
                resolved_count += self.resolve_issues_for_file(file_path)

        # For files with new issues that were actually scanned, resolve old issues that don't match
        # IMPORTANT: Only resolve for files in scanned_files to avoid LLM non-determinism issues
        for file_path, file_issues in new_by_file.items():
            if file_path in scanned_files_set:
                resolved_count += self._resolve_non_matching(file_path, file_issues)

        # Add new issues (all issues, not just for scanned files - new issues are always valid)
        new_count = self.add_issues(new_issues)

        return new_count, resolved_count

    def _resolve_non_matching(
        self,
        file_path: str,
        current_issues: list[Issue],
    ) -> int:
        """Resolve open issues that don't match any current issues.

        Args:
            file_path: Path to the file.
            current_issues: Currently detected issues for this file.

        Returns:
            Number of issues resolved.
        """
        resolved_count = 0
        to_resolve: list[Issue] = []
        
        # O(1) file lookup instead of O(n) full list iteration
        for existing in self._open_by_file.get(file_path, []):
            # Check if any current issue matches
            matches = any(existing.matches(curr) for curr in current_issues)
            if not matches:
                to_resolve.append(existing)
        
        # Resolve and move to resolved index using helper
        for issue in to_resolve:
            self._move_issue_status(issue, IssueStatus.OPEN, IssueStatus.RESOLVED)
            resolved_count += 1
            logger.info(f"Resolved (fixed): {file_path}:{issue.line_number}")
        
        return resolved_count

    def get_issues_by_file(self) -> dict[str, list[Issue]]:
        """Get issues grouped by file.

        Returns:
            Dictionary mapping file paths to their issues.
        """
        by_file: dict[str, list[Issue]] = {}
        for issue in self._issues:
            if issue.file_path not in by_file:
                by_file[issue.file_path] = []
            by_file[issue.file_path].append(issue)

        # Sort issues within each file by line number
        for issues in by_file.values():
            issues.sort(key=lambda i: i.line_number)

        # Sort files alphabetically
        return dict(sorted(by_file.items()))

    def get_stats(self) -> dict[str, int]:
        """Get issue statistics.

        Returns:
            Dictionary with counts of open, resolved, and total issues.
        """
        open_count = len(self.open_issues)
        resolved_count = len(self.resolved_issues)
        return {
            "open": open_count,
            "resolved": resolved_count,
            "total": open_count + resolved_count,
        }
