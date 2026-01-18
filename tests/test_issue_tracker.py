"""Tests for issue tracker module."""

import pytest
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.models import Issue, IssueStatus
from code_scanner.issue_tracker import IssueTracker


class TestIssueMatching:
    """Tests for issue matching/deduplication."""

    def test_identical_issues_match(self):
        """Test that identical issues match."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Test issue",
            suggested_fix="Fix it",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code here",
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Test issue",
            suggested_fix="Fix it",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code here",
        )
        
        assert issue1.matches(issue2)

    def test_different_line_same_code_matches(self):
        """Test that issues with different lines but same code match."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Test issue",
            suggested_fix="Fix it",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code here",
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=15,  # Different line
            description="Test issue",
            suggested_fix="Fix it",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code here",  # Same code
        )
        
        assert issue1.matches(issue2)

    def test_different_files_dont_match(self):
        """Test that issues in different files don't match."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Test issue",
            suggested_fix="Fix it",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code here",
        )
        issue2 = Issue(
            file_path="src/other.cpp",  # Different file
            line_number=10,
            description="Test issue",
            suggested_fix="Fix it",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code here",
        )
        
        assert not issue1.matches(issue2)

    def test_whitespace_normalized_matching(self):
        """Test that whitespace is normalized for matching."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Test   issue   here",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="",
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Test issue here",  # Normalized whitespace
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="",
        )
        
        assert issue1.matches(issue2)

    def test_fuzzy_match_similar_code_snippets(self):
        """Test fuzzy matching of similar code snippets (above threshold)."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Different description A",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="int result = calculateValue(x, y);",
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=15,
            description="Different description B",  # Different description
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="int result = calculateValue(x, y );",  # Minor change (space before paren)
        )
        
        # Should match via fuzzy code snippet comparison
        assert issue1.matches(issue2)

    def test_fuzzy_match_similar_descriptions(self):
        """Test fuzzy matching of similar descriptions (above threshold)."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Memory leak detected in function processData",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="",  # Empty code snippet
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=15,
            description="Memory leak detected in function process_data",  # Minor variation
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="",  # Empty code snippet
        )
        
        # Should match via fuzzy description comparison
        assert issue1.matches(issue2)

    def test_fuzzy_match_below_threshold_no_match(self):
        """Test that dissimilar issues don't match (below threshold)."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Completely different issue",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="int x = 1;",
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=15,
            description="Totally unrelated problem",  # Different
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="string name = 'hello';",  # Different
        )
        
        # Should NOT match - both code and descriptions are too different
        assert not issue1.matches(issue2)

    def test_fuzzy_match_dissimilar_code_but_similar_descriptions(self):
        """Test matching when code snippets differ but descriptions are similar.
        
        This specifically tests line 70 - fuzzy description match when code doesn't match.
        """
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Unused variable 'counter' detected in function processData",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="int counter = 0;",  # Different code
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=15,
            description="Unused variable 'counter' found in function processData",  # Similar desc
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="string name = getData();",  # Very different code
        )
        
        # Code snippets are too different (below threshold)
        # But descriptions are similar enough (above threshold)
        # Should match via description fuzzy comparison
        assert issue1.matches(issue2)

    def test_fuzzy_match_empty_code_only_descriptions_compared(self):
        """Test matching when code snippets are empty - only descriptions matter."""
        issue1 = Issue(
            file_path="src/main.cpp",
            line_number=10,
            description="Unused variable detected",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="",  # Empty
        )
        issue2 = Issue(
            file_path="src/main.cpp",
            line_number=15,
            description="Unused variable found",  # Similar but not identical
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="",  # Empty
        )
        
        # Should match via fuzzy description comparison
        assert issue1.matches(issue2)


class TestIssueTracker:
    """Tests for IssueTracker class."""

    def test_add_new_issue(self):
        """Test adding a new issue."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="test.cpp",
            line_number=1,
            description="Test",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
        )
        
        added = tracker.add_issue(issue)
        
        assert added is True
        assert len(tracker.issues) == 1

    def test_add_duplicate_returns_false(self):
        """Test that adding duplicate issue returns False."""
        tracker = IssueTracker()
        issue1 = Issue(
            file_path="test.cpp",
            line_number=1,
            description="Test",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code",
        )
        issue2 = Issue(
            file_path="test.cpp",
            line_number=1,
            description="Test",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code",
        )
        
        tracker.add_issue(issue1)
        added = tracker.add_issue(issue2)
        
        assert added is False
        assert len(tracker.issues) == 1

    def test_line_number_updated_for_moved_issue(self):
        """Test that line number is updated for moved issues."""
        tracker = IssueTracker()
        issue1 = Issue(
            file_path="test.cpp",
            line_number=10,
            description="Test",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code",
        )
        issue2 = Issue(
            file_path="test.cpp",
            line_number=15,  # Moved
            description="Test",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code",  # Same code
        )
        
        tracker.add_issue(issue1)
        tracker.add_issue(issue2)
        
        assert len(tracker.issues) == 1
        assert tracker.issues[0].line_number == 15  # Updated

    def test_resolve_issues_for_file(self):
        """Test resolving all issues for a file."""
        tracker = IssueTracker()
        issue1 = Issue(
            file_path="test.cpp",
            line_number=1,
            description="Memory leak detected in malloc call without corresponding free",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="void* ptr = malloc(100);",  # Different snippets to avoid dedup
        )
        issue2 = Issue(
            file_path="test.cpp",
            line_number=2,
            description="Null pointer dereference risk in function parameter",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="if (*ptr == 0)",  # Different snippet
        )
        
        tracker.add_issue(issue1)
        tracker.add_issue(issue2)
        
        resolved = tracker.resolve_issues_for_file("test.cpp")
        
        assert resolved == 2
        assert all(i.status == IssueStatus.RESOLVED for i in tracker.issues)

    def test_reopen_resolved_issue(self):
        """Test that resolved issues can be reopened."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="test.cpp",
            line_number=1,
            description="Test",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code",
        )
        
        tracker.add_issue(issue)
        tracker.resolve_issues_for_file("test.cpp")
        
        # Add same issue again
        new_issue = Issue(
            file_path="test.cpp",
            line_number=1,
            description="Test",
            suggested_fix="Fix",
            check_query="Check",
            timestamp=datetime.now(),
            code_snippet="code",
        )
        tracker.add_issue(new_issue)
        
        assert len(tracker.issues) == 1
        assert tracker.issues[0].status == IssueStatus.OPEN

    def test_get_issues_by_file(self):
        """Test grouping issues by file."""
        tracker = IssueTracker()
        tracker.add_issue(Issue(
            file_path="a.cpp",
            line_number=1,
            description="Memory leak found in constructor initialization",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="char* buffer = new char[256];",  # Unique snippet
        ))
        tracker.add_issue(Issue(
            file_path="b.cpp",
            line_number=1,
            description="Unchecked return value from system call",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="system(command);",  # Unique snippet
        ))
        tracker.add_issue(Issue(
            file_path="a.cpp",
            line_number=2,
            description="Buffer overflow risk in string concatenation",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="strcat(dest, source);",  # Unique snippet
        ))
        
        by_file = tracker.get_issues_by_file()
        
        assert len(by_file) == 2
        assert len(by_file["a.cpp"]) == 2
        assert len(by_file["b.cpp"]) == 1

    def test_get_stats(self):
        """Test getting issue statistics."""
        tracker = IssueTracker()
        tracker.add_issue(Issue(
            file_path="a.cpp",
            line_number=1,
            description="Open 1",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
        ))
        tracker.add_issue(Issue(
            file_path="b.cpp",
            line_number=1,
            description="To resolve",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
        ))
        tracker.resolve_issues_for_file("b.cpp")
        
        stats = tracker.get_stats()
        
        assert stats["open"] == 1
        assert stats["resolved"] == 1
        assert stats["total"] == 2

    def test_update_from_scan(self):
        """Test updating tracker from scan results."""
        tracker = IssueTracker()
        
        # Add initial issue
        tracker.add_issue(Issue(
            file_path="a.cpp",
            line_number=1,
            description="Initial",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="code",
        ))
        
        # Scan finds new issue, old issue gone
        new_issues = [
            Issue(
                file_path="a.cpp",
                line_number=5,
                description="New issue",
                suggested_fix="",
                check_query="",
                timestamp=datetime.now(),
                code_snippet="different code",
            )
        ]
        
        new_count, resolved = tracker.update_from_scan(new_issues, ["a.cpp"])
        
        assert new_count == 1
        assert resolved == 1
        assert len(tracker.open_issues) == 1
        assert len(tracker.resolved_issues) == 1

    def test_update_from_scan_unchanged_file_keeps_issues(self):
        """Test that issues are NOT resolved when file is not in scanned_files list.
        
        This tests the fix for the bug where LLM non-determinism could cause
        issues to be resolved even when the file content hadn't changed.
        The scanner should only pass files with changed content to update_from_scan.
        """
        tracker = IssueTracker()
        
        # Add initial issue for file
        tracker.add_issue(Issue(
            file_path="unchanged.cpp",
            line_number=10,
            description="Memory leak",
            suggested_fix="Free memory",
            check_query="Check memory",
            timestamp=datetime.now(),
            code_snippet="malloc()",
        ))
        
        # Simulate scan where file content hasn't changed
        # The scanner should NOT include unchanged files in the scanned_files list
        # So we pass an empty list (file wasn't actually changed)
        new_count, resolved = tracker.update_from_scan([], [])
        
        # Issue should still be open (not resolved)
        assert new_count == 0
        assert resolved == 0
        assert len(tracker.open_issues) == 1
        assert len(tracker.resolved_issues) == 0
        assert tracker.open_issues[0].file_path == "unchanged.cpp"

    def test_update_from_scan_only_resolves_changed_files(self):
        """Test that issues are only resolved for files that are in scanned_files."""
        tracker = IssueTracker()
        
        # Add issues for two files
        tracker.add_issue(Issue(
            file_path="changed.cpp",
            line_number=10,
            description="Issue in changed file",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="code1",
        ))
        tracker.add_issue(Issue(
            file_path="unchanged.cpp",
            line_number=20,
            description="Issue in unchanged file",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="code2",
        ))
        
        # Scan only reports issues for changed.cpp (unchanged.cpp not in list)
        # This simulates the case where unchanged.cpp content didn't change
        new_count, resolved = tracker.update_from_scan([], ["changed.cpp"])
        
        # Issue in changed.cpp should be resolved (was scanned, no new issue)
        # Issue in unchanged.cpp should remain open (not in scanned_files)
        assert new_count == 0
        assert resolved == 1
        assert len(tracker.open_issues) == 1
        assert len(tracker.resolved_issues) == 1
        assert tracker.open_issues[0].file_path == "unchanged.cpp"
        assert tracker.resolved_issues[0].file_path == "changed.cpp"

    def test_update_from_scan_does_not_resolve_for_files_not_in_scanned_files(self):
        """Test that _resolve_non_matching is NOT called for files not in scanned_files.
        
        This prevents LLM non-determinism from incorrectly resolving issues
        when file content hasn't actually changed but LLM returns different issues.
        """
        tracker = IssueTracker()
        
        # Add an existing issue
        tracker.add_issue(Issue(
            file_path="file.cpp",
            line_number=10,
            description="Existing issue",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="old_code",
        ))
        
        # LLM finds a DIFFERENT issue for the same file, but file.cpp is NOT in scanned_files
        # (simulating LLM non-determinism when file content hasn't changed)
        new_issues = [Issue(
            file_path="file.cpp",
            line_number=20,
            description="Different issue from LLM",
            suggested_fix="",
            check_query="",
            timestamp=datetime.now(),
            code_snippet="different_code",
        )]
        
        # file.cpp is NOT in scanned_files (content didn't change)
        new_count, resolved = tracker.update_from_scan(new_issues, [])
        
        # New issue should be added
        assert new_count == 1
        # But original issue should NOT be resolved (file wasn't in scanned_files)
        assert resolved == 0
        # Both issues should be open
        assert len(tracker.open_issues) == 2
        assert len(tracker.resolved_issues) == 0



class TestIndexHelpers:
    """Tests for internal index helper methods."""

    def test_add_to_index_open_issue(self):
        """Test _add_to_index adds open issue to open index."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="src/main.py",
            line_number=10,
            description="Test issue",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.OPEN,
        )
        
        tracker._add_to_index(issue)
        
        assert "src/main.py" in tracker._open_by_file
        assert issue in tracker._open_by_file["src/main.py"]
        assert "src/main.py" not in tracker._resolved_by_file

    def test_add_to_index_resolved_issue(self):
        """Test _add_to_index adds resolved issue to resolved index."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="src/main.py",
            line_number=10,
            description="Test issue",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.RESOLVED,
        )
        
        tracker._add_to_index(issue)
        
        assert "src/main.py" in tracker._resolved_by_file
        assert issue in tracker._resolved_by_file["src/main.py"]
        assert "src/main.py" not in tracker._open_by_file

    def test_remove_from_index_removes_issue(self):
        """Test _remove_from_index removes issue from correct index."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="src/main.py",
            line_number=10,
            description="Test issue",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.OPEN,
        )
        tracker._open_by_file["src/main.py"] = [issue]
        
        tracker._remove_from_index(issue, IssueStatus.OPEN)
        
        assert issue not in tracker._open_by_file.get("src/main.py", [])

    def test_remove_from_index_nonexistent_file(self):
        """Test _remove_from_index handles nonexistent file gracefully."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="src/nonexistent.py",
            line_number=10,
            description="Test issue",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.OPEN,
        )
        
        # Should not raise exception
        tracker._remove_from_index(issue, IssueStatus.OPEN)

    def test_remove_from_index_issue_not_in_list(self):
        """Test _remove_from_index handles issue not in list gracefully."""
        tracker = IssueTracker()
        issue1 = Issue(
            file_path="src/main.py",
            line_number=10,
            description="Issue 1",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.OPEN,
        )
        issue2 = Issue(
            file_path="src/main.py",
            line_number=20,
            description="Issue 2",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.OPEN,
        )
        tracker._open_by_file["src/main.py"] = [issue1]
        
        # Should not raise exception
        tracker._remove_from_index(issue2, IssueStatus.OPEN)
        
        # issue1 should still be there
        assert issue1 in tracker._open_by_file["src/main.py"]

    def test_move_issue_status_open_to_resolved(self):
        """Test _move_issue_status moves issue from open to resolved."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="src/main.py",
            line_number=10,
            description="Test issue",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.OPEN,
        )
        tracker._open_by_file["src/main.py"] = [issue]
        
        tracker._move_issue_status(issue, IssueStatus.OPEN, IssueStatus.RESOLVED)
        
        assert issue.status == IssueStatus.RESOLVED
        assert issue not in tracker._open_by_file.get("src/main.py", [])
        assert issue in tracker._resolved_by_file.get("src/main.py", [])
        assert tracker._changed

    def test_move_issue_status_resolved_to_open(self):
        """Test _move_issue_status moves issue from resolved to open (reopen)."""
        tracker = IssueTracker()
        issue = Issue(
            file_path="src/main.py",
            line_number=10,
            description="Test issue",
            suggested_fix="",
            check_query="Test",
            timestamp=datetime.now(),
            status=IssueStatus.RESOLVED,
        )
        tracker._resolved_by_file["src/main.py"] = [issue]
        
        tracker._move_issue_status(issue, IssueStatus.RESOLVED, IssueStatus.OPEN)
        
        assert issue.status == IssueStatus.OPEN
        assert issue not in tracker._resolved_by_file.get("src/main.py", [])
        assert issue in tracker._open_by_file.get("src/main.py", [])


