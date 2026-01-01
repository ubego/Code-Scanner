"""Issue tracking and state management."""

import logging
from datetime import datetime
from typing import Optional

from .models import Issue, IssueStatus

logger = logging.getLogger(__name__)


class IssueTracker:
    """Manages detected issues in memory with deduplication and resolution tracking."""

    def __init__(self):
        """Initialize the issue tracker."""
        self._issues: list[Issue] = []
        self._changed: bool = False

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

    @property
    def has_changed(self) -> bool:
        """Check if issues have changed since last reset."""
        return self._changed

    def reset_changed_flag(self) -> None:
        """Reset the changed flag after processing."""
        self._changed = False

    def add_issue(self, issue: Issue) -> bool:
        """Add a new issue, handling deduplication.

        If an identical issue exists (same file, similar code/description),
        updates the line number instead of creating a duplicate.

        Args:
            issue: The issue to add.

        Returns:
            True if a new issue was added, False if deduplicated.
        """
        # Check for existing matching issue
        for existing in self._issues:
            if existing.status == IssueStatus.OPEN and existing.matches(issue):
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

        # Check if this was a previously resolved issue that reappeared
        for existing in self._issues:
            if existing.status == IssueStatus.RESOLVED and existing.matches(issue):
                # Reopen the issue
                logger.info(f"Reopening resolved issue: {existing.file_path}")
                existing.status = IssueStatus.OPEN
                existing.line_number = issue.line_number
                existing.timestamp = issue.timestamp
                self._changed = True
                return False

        # Add new issue
        logger.info(f"New issue: {issue.file_path}:{issue.line_number}")
        self._issues.append(issue)
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
        resolved_count = 0
        for issue in self._issues:
            if issue.file_path == file_path and issue.status == IssueStatus.OPEN:
                issue.status = IssueStatus.RESOLVED
                resolved_count += 1
                self._changed = True
                logger.info(f"Resolved issue: {file_path}:{issue.line_number}")
        return resolved_count

    def update_from_scan(
        self,
        new_issues: list[Issue],
        scanned_files: list[str],
    ) -> tuple[int, int]:
        """Update tracker from a scan result.

        Adds new issues and resolves issues that are no longer detected
        in the scanned files.

        Args:
            new_issues: Issues detected in this scan.
            scanned_files: List of files that were scanned.

        Returns:
            Tuple of (new_issues_count, resolved_count).
        """
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

        # For files with new issues, resolve old issues that don't match
        for file_path, file_issues in new_by_file.items():
            resolved_count += self._resolve_non_matching(file_path, file_issues)

        # Add new issues
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
        for existing in self._issues:
            if (
                existing.file_path == file_path
                and existing.status == IssueStatus.OPEN
            ):
                # Check if any current issue matches
                matches = any(existing.matches(curr) for curr in current_issues)
                if not matches:
                    existing.status = IssueStatus.RESOLVED
                    resolved_count += 1
                    self._changed = True
                    logger.info(
                        f"Resolved (fixed): {file_path}:{existing.line_number}"
                    )
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

    def clear(self) -> None:
        """Clear all tracked issues."""
        self._issues.clear()
        self._changed = True

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
