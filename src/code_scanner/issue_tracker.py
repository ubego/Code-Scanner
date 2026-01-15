"""Issue tracking and state management."""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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

    def load_from_file(self, file_path: Path) -> int:
        """Load issues from an existing output file.

        Parses the Markdown output file and restores issue state.
        This allows persisting issues between scanner restarts.

        Args:
            file_path: Path to the output Markdown file.

        Returns:
            Number of issues loaded.
        """
        if not file_path.exists():
            logger.debug(f"No existing output file to load: {file_path}")
            return 0

        try:
            content = file_path.read_text(encoding="utf-8")
        except IOError as e:
            logger.warning(f"Failed to read output file: {e}")
            return 0

        return self.load_from_content(content)

    def load_from_content(self, content: str) -> int:
        """Load issues from Markdown content string.

        Parses the Markdown content and restores issue state.
        This allows loading from backed-up content.

        Args:
            content: Markdown content from output file.

        Returns:
            Number of issues loaded.
        """
        issues = self._parse_issues_from_markdown(content)
        
        for issue in issues:
            self._issues.append(issue)
            self._add_to_index(issue)

        if issues:
            logger.info(f"Loaded {len(issues)} issues from content")
        return len(issues)

    def _parse_issues_from_markdown(self, content: str) -> list[Issue]:
        """Parse issues from Markdown content.

        Args:
            content: Markdown content from output file.

        Returns:
            List of parsed Issue objects.
        """
        issues: list[Issue] = []
        current_file: Optional[str] = None
        
        # Skip if content is just the "Scanning in progress..." placeholder
        if "Scanning in progress..." in content and "## Issues by File" not in content:
            return issues

        lines = content.split("\n")
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Match file header: ### `path/to/file.py`
            file_match = re.match(r"^### `(.+)`$", line)
            if file_match:
                current_file = file_match.group(1)
                i += 1
                continue
            
            # Match issue header: #### Line 123 - 🔴 OPEN or #### Line 123 - ✅ RESOLVED
            issue_match = re.match(r"^#### Line (\d+) - (🔴 OPEN|✅ RESOLVED)$", line)
            if issue_match and current_file:
                line_number = int(issue_match.group(1))
                status_str = issue_match.group(2)
                status = IssueStatus.OPEN if "OPEN" in status_str else IssueStatus.RESOLVED
                
                # Parse the issue body
                timestamp = datetime.now(timezone.utc)
                check_query = ""
                description = ""
                code_snippet = ""
                suggested_fix = ""
                
                i += 1
                while i < len(lines):
                    curr_line = lines[i]
                    
                    # Stop at next issue or file header
                    if curr_line.startswith("#### Line") or curr_line.startswith("### `"):
                        break
                    if curr_line.startswith("---"):  # Footer
                        break
                    
                    # Parse timestamp
                    ts_match = re.match(r"\*\*Detected:\*\* (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", curr_line)
                    if ts_match:
                        try:
                            timestamp = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                            timestamp = timestamp.replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
                        i += 1
                        continue
                    
                    # Parse check query
                    check_match = re.match(r"\*\*Check:\*\* (.+)", curr_line)
                    if check_match:
                        check_query = check_match.group(1)
                        i += 1
                        continue
                    
                    # Parse description
                    if curr_line == "**Issue:**":
                        i += 1
                        desc_lines: list[str] = []
                        while i < len(lines):
                            desc_line = lines[i]
                            # Stop at next section or next issue/file
                            if desc_line.startswith("**") or desc_line.startswith("#### Line") or desc_line.startswith("### `") or desc_line.startswith("---"):
                                break
                            if desc_line.strip():
                                desc_lines.append(desc_line)
                            i += 1
                        description = "\n".join(desc_lines)
                        continue
                    
                    # Parse code snippet
                    if curr_line == "**Problematic Code:**":
                        i += 1
                        if i < len(lines) and lines[i] == "```":
                            i += 1
                            snippet_lines: list[str] = []
                            while i < len(lines) and lines[i] != "```":
                                snippet_lines.append(lines[i])
                                i += 1
                            code_snippet = "\n".join(snippet_lines)
                            i += 1  # Skip closing ```
                        continue
                    
                    # Parse suggested fix
                    if curr_line == "**Suggested Fix:**":
                        i += 1
                        if i < len(lines) and lines[i] == "```":
                            i += 1
                            fix_lines: list[str] = []
                            while i < len(lines) and lines[i] != "```":
                                fix_lines.append(lines[i])
                                i += 1
                            suggested_fix = "\n".join(fix_lines)
                            i += 1  # Skip closing ```
                        continue
                    
                    i += 1
                
                # Create the issue
                issue = Issue(
                    file_path=current_file,
                    line_number=line_number,
                    description=description,
                    suggested_fix=suggested_fix,
                    check_query=check_query,
                    timestamp=timestamp,
                    status=status,
                    code_snippet=code_snippet,
                )
                issues.append(issue)
                continue
            
            i += 1
        
        return issues

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
