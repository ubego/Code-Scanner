"""Tests for output module."""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.output import OutputGenerator
from code_scanner.models import Issue, IssueStatus
from code_scanner.issue_tracker import IssueTracker


class TestOutputGenerator:
    """Tests for OutputGenerator class."""

    @pytest.fixture
    def output_path(self, temp_dir: Path) -> Path:
        """Create output file path."""
        return temp_dir / "code_scanner_results.md"

    @pytest.fixture
    def tracker_with_issues(self) -> IssueTracker:
        """Create issue tracker with sample issues."""
        tracker = IssueTracker()
        
        tracker.add_issue(Issue(
            file_path="widget.cpp",
            line_number=15,
            description="Heap allocation without smart pointer",
            suggested_fix="Use std::unique_ptr",
            check_query="heap-allocation",
            timestamp=datetime.now(),
            code_snippet="int* ptr = new int;",
        ))
        
        tracker.add_issue(Issue(
            file_path="widget.cpp",
            line_number=42,
            description="Consider using constant for repeated string",
            suggested_fix="static constexpr auto MSG = \"msg\";",
            check_query="repeated-literals",
            timestamp=datetime.now(),
            code_snippet='"Please enter your name"',
        ))
        
        tracker.add_issue(Issue(
            file_path="main.cpp",
            line_number=10,
            description="Function in header should be inline",
            suggested_fix="Add inline keyword",
            check_query="functions-in-headers",
            timestamp=datetime.now(),
            code_snippet="void helper() { ... }",
        ))
        
        return tracker

    def test_write_creates_file(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that write creates the output file."""
        generator = OutputGenerator(output_path)
        
        generator.write(tracker_with_issues)
        
        assert output_path.exists()

    def test_write_contains_issues(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that output contains all issues."""
        generator = OutputGenerator(output_path)
        
        generator.write(tracker_with_issues)
        
        content = output_path.read_text()
        
        assert "widget.cpp" in content
        assert "main.cpp" in content
        assert "Heap allocation without smart pointer" in content
        assert "repeated string" in content
        assert "inline" in content.lower()

    def test_write_groups_by_file(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that issues are grouped by file."""
        generator = OutputGenerator(output_path)
        
        generator.write(tracker_with_issues)
        
        content = output_path.read_text()
        
        # widget.cpp should appear before its issues
        widget_header = content.find("`widget.cpp`")
        heap_alloc_pos = content.find("Heap allocation")
        
        assert widget_header != -1
        assert heap_alloc_pos != -1
        assert widget_header < heap_alloc_pos

    def test_write_includes_line_numbers(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that line numbers are included."""
        generator = OutputGenerator(output_path)
        
        generator.write(tracker_with_issues)
        
        content = output_path.read_text()
        
        assert "15" in content
        assert "42" in content

    def test_write_includes_code_snippets(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that code snippets are included."""
        generator = OutputGenerator(output_path)
        
        generator.write(tracker_with_issues)
        
        content = output_path.read_text()
        
        assert "int* ptr = new int" in content

    def test_write_includes_timestamp(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that timestamp is included."""
        generator = OutputGenerator(output_path)
        
        generator.write(tracker_with_issues)
        
        content = output_path.read_text()
        
        # Should have some form of timestamp
        current_year = str(datetime.now().year)
        assert current_year in content

    def test_write_empty_issues(self, output_path: Path):
        """Test output with no issues."""
        tracker = IssueTracker()
        generator = OutputGenerator(output_path)
        
        generator.write(tracker)
        
        content = output_path.read_text()
        
        assert "No issues" in content or "0" in content

    def test_write_summary_section(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that summary section exists."""
        generator = OutputGenerator(output_path)
        
        generator.write(tracker_with_issues)
        
        content = output_path.read_text()
        
        # Should have a summary with counts
        assert "Summary" in content
        assert "Open" in content

    def test_write_overwrites_existing(self, output_path: Path, tracker_with_issues: IssueTracker):
        """Test that existing output is overwritten."""
        output_path.write_text("Old content")
        
        generator = OutputGenerator(output_path)
        generator.write(tracker_with_issues)
        
        content = output_path.read_text()
        
        assert "Old content" not in content
        assert "widget.cpp" in content

    def test_exists_check(self, output_path: Path):
        """Test exists() method."""
        generator = OutputGenerator(output_path)
        
        assert not generator.exists()
        
        output_path.write_text("content")
        
        assert generator.exists()

    def test_delete_removes_file(self, output_path: Path):
        """Test delete() method."""
        output_path.write_text("content")
        generator = OutputGenerator(output_path)
        
        generator.delete()
        
        assert not output_path.exists()


class TestMarkdownFormatting:
    """Tests for Markdown formatting specifics."""

    @pytest.fixture
    def output_path(self, temp_dir: Path) -> Path:
        """Create output path."""
        return temp_dir / "code_scanner_results.md"

    def test_valid_markdown_headers(self, output_path: Path):
        """Test that output has valid Markdown headers."""
        tracker = IssueTracker()
        tracker.add_issue(Issue(
            file_path="test.cpp",
            line_number=1,
            description="Test issue",
            suggested_fix="Fix it",
            check_query="test-check",
            timestamp=datetime.now(),
            code_snippet="test",
        ))
        
        generator = OutputGenerator(output_path)
        generator.write(tracker)
        
        content = output_path.read_text()
        
        # Should have proper Markdown headers
        assert "# " in content

    def test_code_blocks_formatted(self, output_path: Path):
        """Test that code snippets are in code blocks."""
        tracker = IssueTracker()
        tracker.add_issue(Issue(
            file_path="test.cpp",
            line_number=1,
            description="Test issue",
            suggested_fix="int y = 0;",
            check_query="test-check",
            timestamp=datetime.now(),
            code_snippet="int x = 42;",
        ))
        
        generator = OutputGenerator(output_path)
        generator.write(tracker)
        
        content = output_path.read_text()
        
        # Should have code block markers
        assert "```" in content
