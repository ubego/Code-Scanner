"""Additional tests for issue tracker functionality."""

import pytest
from datetime import datetime

from code_scanner.issue_tracker import IssueTracker
from code_scanner.models import Issue, IssueStatus


class TestIssueTrackerResolveNonMatching:
    """Tests for _resolve_non_matching method."""

    def test_resolves_old_issues_not_in_current(self):
        """Old issues not in current scan are resolved."""
        tracker = IssueTracker()
        now = datetime.now()
        
        old_issue = Issue(
            file_path="test.py",
            line_number=10,
            description="Old issue",
            suggested_fix="old fix",
            code_snippet="old code",
            check_query="check",
            timestamp=now,
        )
        tracker.add_issue(old_issue)
        
        # New scan finds different issue in same file
        new_issue = Issue(
            file_path="test.py",
            line_number=20,
            description="New issue",
            suggested_fix="new fix",
            code_snippet="new code",
            check_query="check",
            timestamp=now,
        )
        
        resolved = tracker._resolve_non_matching("test.py", [new_issue])
        
        assert resolved == 1
        assert old_issue.status == IssueStatus.RESOLVED


class TestIssueTrackerUpdateFromScan:
    """Tests for update_from_scan method."""

    def test_resolves_all_issues_for_scanned_file_with_no_new_issues(self):
        """All issues resolved for scanned file with no new issues."""
        tracker = IssueTracker()
        now = datetime.now()
        
        issue = Issue(
            file_path="test.py",
            line_number=10,
            description="Issue",
            suggested_fix="fix",
            code_snippet="code",
            check_query="check",
            timestamp=now,
        )
        tracker.add_issue(issue)
        
        # Scan same file but find no issues
        new_count, resolved_count = tracker.update_from_scan([], ["test.py"])
        
        assert new_count == 0
        assert resolved_count == 1
        assert issue.status == IssueStatus.RESOLVED

    def test_keeps_issues_for_non_scanned_files(self):
        """Issues in non-scanned files remain open."""
        tracker = IssueTracker()
        now = datetime.now()
        
        issue = Issue(
            file_path="other.py",
            line_number=10,
            description="Issue",
            suggested_fix="fix",
            code_snippet="code",
            check_query="check",
            timestamp=now,
        )
        tracker.add_issue(issue)
        
        # Scan different file
        new_count, resolved_count = tracker.update_from_scan([], ["test.py"])
        
        assert issue.status == IssueStatus.OPEN


class TestIssueTrackerAddIssues:
    """Tests for add_issues method."""

    def test_add_multiple_issues_returns_new_count(self):
        """add_issues returns count of truly new issues."""
        tracker = IssueTracker()
        now = datetime.now()
        
        issue1 = Issue(
            file_path="a.py",
            line_number=1,
            description="Issue 1",
            suggested_fix="Fix",
            code_snippet="code 1",
            check_query="check",
            timestamp=now,
        )
        issue2 = Issue(
            file_path="b.py",
            line_number=1,
            description="Issue 2",
            suggested_fix="Fix",
            code_snippet="code 2",
            check_query="check",
            timestamp=now,
        )
        
        # Add first issue
        tracker.add_issue(issue1)
        
        # Add both (first is duplicate)
        duplicate = Issue(
            file_path="a.py",
            line_number=1,
            description="Issue 1",
            suggested_fix="Fix",
            code_snippet="code 1",
            check_query="check",
            timestamp=now,
        )
        
        count = tracker.add_issues([duplicate, issue2])
        
        assert count == 1  # Only issue2 is new


class TestIssueTrackerProperties:
    """Tests for IssueTracker property methods."""

    def test_open_issues_returns_only_open(self):
        """open_issues returns only OPEN status issues."""
        tracker = IssueTracker()
        now = datetime.now()
        
        open_issue = Issue(
            file_path="open.py",
            line_number=1,
            description="Open",
            suggested_fix="Fix",
            code_snippet="code",
            check_query="check",
            timestamp=now,
        )
        tracker.add_issue(open_issue)
        
        # Add and resolve another
        resolved_issue = Issue(
            file_path="resolved.py",
            line_number=1,
            description="Resolved",
            suggested_fix="Fix",
            code_snippet="code",
            check_query="check",
            timestamp=now,
        )
        tracker.add_issue(resolved_issue)
        tracker.resolve_issues_for_file("resolved.py")
        
        open_issues = tracker.open_issues
        
        assert len(open_issues) == 1
        assert open_issues[0].file_path == "open.py"

    def test_resolved_issues_returns_only_resolved(self):
        """resolved_issues returns only RESOLVED status issues."""
        tracker = IssueTracker()
        now = datetime.now()
        
        issue = Issue(
            file_path="test.py",
            line_number=1,
            description="Test",
            suggested_fix="Fix",
            code_snippet="code",
            check_query="check",
            timestamp=now,
        )
        tracker.add_issue(issue)
        tracker.resolve_issues_for_file("test.py")
        
        resolved = tracker.resolved_issues
        
        assert len(resolved) == 1
        assert resolved[0].status == IssueStatus.RESOLVED


class TestIssueMatches:
    """Tests for Issue.matches method edge cases."""

    def test_matches_different_check_query_same_description(self):
        """Issues match even with different check queries if description same."""
        now = datetime.now()
        issue1 = Issue(
            file_path="test.py",
            line_number=10,
            description="Same issue",
            suggested_fix="Fix",
            code_snippet="same code",
            check_query="check1",
            timestamp=now,
        )
        issue2 = Issue(
            file_path="test.py",
            line_number=10,
            description="Same issue",
            suggested_fix="Fix",
            code_snippet="same code",
            check_query="check2",
            timestamp=now,
        )
        
        assert issue1.matches(issue2) is True

    def test_matches_different_descriptions_same_code(self):
        """Issues with different descriptions but same code still match."""
        now = datetime.now()
        issue1 = Issue(
            file_path="test.py",
            line_number=10,
            description="Desc 1",
            suggested_fix="Fix",
            code_snippet="identical code snippet",
            check_query="check",
            timestamp=now,
        )
        issue2 = Issue(
            file_path="test.py",
            line_number=10,
            description="Desc 2",
            suggested_fix="Fix",
            code_snippet="identical code snippet",
            check_query="check",
            timestamp=now,
        )
        
        # They match because code_snippet is the same
        assert issue1.matches(issue2) is True
