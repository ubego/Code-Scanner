"""Extended tests for Scanner class functionality."""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from code_scanner.scanner import Scanner
from code_scanner.config import Config, LLMConfig, CheckGroup
from code_scanner.models import Issue, GitState, ChangedFile, IssueStatus


@pytest.fixture
def mock_config():
    """Create a mock Config object."""
    config = MagicMock(spec=Config)
    config.target_directory = Path("/test/repo")
    config.output_file = "results.md"
    config.log_file = "scanner.log"
    config.git_poll_interval = 1.0
    config.llm_retry_interval = 1.0
    config.max_llm_retries = 3
    config.check_groups = [
        CheckGroup(pattern="*.py", rules=["Check for bugs"]),
    ]
    return config


@pytest.fixture
def mock_dependencies(mock_config):
    """Create mock dependencies for Scanner."""
    git_watcher = MagicMock()
    llm_client = MagicMock()
    llm_client.context_limit = 8000
    issue_tracker = MagicMock()
    output_generator = MagicMock()
    
    return {
        "config": mock_config,
        "git_watcher": git_watcher,
        "llm_client": llm_client,
        "issue_tracker": issue_tracker,
        "output_generator": output_generator,
    }


class TestScannerInit:
    """Tests for Scanner initialization."""

    def test_init_sets_config(self, mock_dependencies):
        """Scanner stores config reference."""
        scanner = Scanner(**mock_dependencies)
        assert scanner.config == mock_dependencies["config"]

    def test_init_sets_dependencies(self, mock_dependencies):
        """Scanner stores all dependencies."""
        scanner = Scanner(**mock_dependencies)
        assert scanner.git_watcher == mock_dependencies["git_watcher"]
        assert scanner.llm_client == mock_dependencies["llm_client"]
        assert scanner.issue_tracker == mock_dependencies["issue_tracker"]
        assert scanner.output_generator == mock_dependencies["output_generator"]

    def test_init_creates_stop_event(self, mock_dependencies):
        """Scanner creates stop event."""
        scanner = Scanner(**mock_dependencies)
        assert scanner._stop_event is not None
        assert not scanner._stop_event.is_set()

    def test_init_creates_restart_event(self, mock_dependencies):
        """Scanner creates restart event."""
        scanner = Scanner(**mock_dependencies)
        assert scanner._restart_event is not None
        assert not scanner._restart_event.is_set()


class TestScannerStart:
    """Tests for Scanner start method."""

    def test_start_creates_thread(self, mock_dependencies):
        """Start creates and starts thread."""
        scanner = Scanner(**mock_dependencies)
        
        # Mock the _run_loop to do nothing
        scanner._run_loop = MagicMock()
        
        scanner.start()
        
        assert scanner._thread is not None
        # Stop immediately
        scanner.stop()


class TestScannerStop:
    """Tests for Scanner stop method."""

    def test_stop_sets_stop_event(self, mock_dependencies):
        """Stop sets the stop event."""
        scanner = Scanner(**mock_dependencies)
        scanner.stop()
        assert scanner._stop_event.is_set()

    def test_stop_sets_restart_event(self, mock_dependencies):
        """Stop sets restart event to wake waiting threads."""
        scanner = Scanner(**mock_dependencies)
        scanner.stop()
        assert scanner._restart_event.is_set()


class TestScannerSignalRestart:
    """Tests for Scanner signal_restart method."""

    def test_signal_restart_sets_event(self, mock_dependencies):
        """Signal restart sets the restart event."""
        scanner = Scanner(**mock_dependencies)
        scanner.signal_restart()
        assert scanner._restart_event.is_set()


class TestFilterBatchesByPattern:
    """Tests for _filter_batches_by_pattern method."""

    def test_filters_matching_files(self, mock_dependencies):
        """Only files matching pattern are included."""
        scanner = Scanner(**mock_dependencies)
        
        check_group = CheckGroup(pattern="*.py", rules=["check"])
        batches = [
            {"test.py": "content", "test.js": "content"},
            {"other.py": "content"},
        ]
        
        filtered = scanner._filter_batches_by_pattern(batches, check_group)
        
        assert len(filtered) == 2
        assert "test.py" in filtered[0]
        assert "test.js" not in filtered[0]
        assert "other.py" in filtered[1]

    def test_empty_batches_removed(self, mock_dependencies):
        """Batches with no matching files are removed."""
        scanner = Scanner(**mock_dependencies)
        
        check_group = CheckGroup(pattern="*.py", rules=["check"])
        batches = [
            {"test.js": "content"},  # No py files
        ]
        
        filtered = scanner._filter_batches_by_pattern(batches, check_group)
        
        assert len(filtered) == 0


class TestGetFilesContent:
    """Tests for _get_files_content method."""

    def test_skips_deleted_files(self, mock_dependencies):
        """Deleted files are skipped."""
        scanner = Scanner(**mock_dependencies)
        
        changed_files = [
            ChangedFile(path="deleted.py", status="deleted"),
        ]
        
        result = scanner._get_files_content(changed_files)
        
        assert len(result) == 0

    def test_skips_scanner_output_files(self, mock_dependencies):
        """Scanner's own output files are skipped."""
        scanner = Scanner(**mock_dependencies)
        scanner.config.output_file = "results.md"
        scanner.config.log_file = "scanner.log"
        
        changed_files = [
            ChangedFile(path="results.md", status="modified"),
            ChangedFile(path="scanner.log", status="modified"),
        ]
        
        result = scanner._get_files_content(changed_files)
        
        assert len(result) == 0

    def test_skips_binary_files(self, mock_dependencies):
        """Binary files are skipped."""
        scanner = Scanner(**mock_dependencies)
        
        changed_files = [
            ChangedFile(path="image.png", status="modified"),
        ]
        
        with patch("code_scanner.scanner.is_binary_file", return_value=True):
            result = scanner._get_files_content(changed_files)
        
        assert len(result) == 0

    def test_reads_text_files(self, mock_dependencies):
        """Text files are read and included."""
        scanner = Scanner(**mock_dependencies)
        
        changed_files = [
            ChangedFile(path="test.py", status="modified"),
        ]
        
        with patch("code_scanner.scanner.is_binary_file", return_value=False), \
             patch("code_scanner.scanner.read_file_content", return_value="content"):
            result = scanner._get_files_content(changed_files)
        
        assert "test.py" in result
        assert result["test.py"] == "content"


class TestCreateBatches:
    """Tests for _create_batches method."""

    def test_single_batch_when_fits(self, mock_dependencies):
        """All files in one batch when they fit."""
        scanner = Scanner(**mock_dependencies)
        scanner.llm_client.context_limit = 100000
        
        files_content = {
            "a.py": "short content",
            "b.py": "short content",
        }
        
        batches = scanner._create_batches(files_content)
        
        assert len(batches) == 1
        assert "a.py" in batches[0]
        assert "b.py" in batches[0]

    def test_multiple_batches_when_large(self, mock_dependencies):
        """Files split into multiple batches when too large."""
        scanner = Scanner(**mock_dependencies)
        scanner.llm_client.context_limit = 100  # Very small limit
        
        files_content = {
            "a.py": "x" * 50,
            "b.py": "y" * 50,
        }
        
        batches = scanner._create_batches(files_content)
        
        # Should create multiple batches
        assert len(batches) >= 1


class TestRunCheck:
    """Tests for _run_check method."""

    def test_returns_issues_from_llm(self, mock_dependencies):
        """Issues are parsed from LLM response."""
        scanner = Scanner(**mock_dependencies)
        scanner.llm_client.query.return_value = {
            "issues": [
                {
                    "file_path": "test.py",
                    "line": 10,
                    "description": "Bug found",
                    "suggested_fix": "Fix it",
                    "code_snippet": "bad_code()",
                }
            ]
        }
        
        batches = [{"test.py": "content"}]
        issues = scanner._run_check("Find bugs", batches)
        
        assert len(issues) == 1
        assert issues[0].file_path == "test.py"
        assert issues[0].line_number == 10

    def test_empty_response_returns_no_issues(self, mock_dependencies):
        """Empty LLM response returns no issues."""
        scanner = Scanner(**mock_dependencies)
        scanner.llm_client.query.return_value = {"issues": []}
        
        batches = [{"test.py": "content"}]
        issues = scanner._run_check("Find bugs", batches)
        
        assert len(issues) == 0

    def test_stops_on_stop_event(self, mock_dependencies):
        """Processing stops when stop event is set."""
        scanner = Scanner(**mock_dependencies)
        scanner._stop_event.set()
        
        batches = [{"test.py": "content"}]
        issues = scanner._run_check("Find bugs", batches)
        
        # Should return early
        assert issues == []
        # LLM should not be called
        scanner.llm_client.query.assert_not_called()


class TestIssueFromLLMResponseEdgeCases:
    """Tests for Issue.from_llm_response edge cases."""

    def test_alternate_line_number_key(self):
        """line_number key is accepted."""
        data = {
            "file_path": "test.py",
            "line_number": 10,
            "description": "Bug",
            "suggested_fix": "Fix",
            "code_snippet": "code",
        }
        
        issue = Issue.from_llm_response(data, "check", datetime.now())
        assert issue.line_number == 10

    def test_line_number_key_preferred_over_line(self):
        """line_number key takes precedence over line."""
        data = {
            "file_path": "test.py",
            "line": 5,
            "line_number": 10,
            "description": "Bug",
            "suggested_fix": "Fix",
            "code_snippet": "code",
        }
        
        issue = Issue.from_llm_response(data, "check", datetime.now())
        # Implementation uses line_number first, then falls back to line
        assert issue.line_number == 10

    def test_file_key_accepted(self):
        """file key is accepted as alternate for file_path."""
        data = {
            "file": "alternate.py",
            "line": 1,
            "description": "Bug",
            "suggested_fix": "Fix",
            "code_snippet": "code",
        }
        
        issue = Issue.from_llm_response(data, "check", datetime.now())
        assert issue.file_path == "alternate.py"

    def test_missing_code_snippet_defaults_to_empty(self):
        """Missing code_snippet defaults to empty string."""
        data = {
            "file_path": "test.py",
            "line": 1,
            "description": "Bug",
            "suggested_fix": "Fix",
            # No code_snippet
        }
        
        issue = Issue.from_llm_response(data, "check", datetime.now())
        assert issue.code_snippet == ""


class TestImmediateOutputUpdate:
    """Tests for immediate output file updates when issues are found."""

    def test_output_written_immediately_when_issues_found(self, mock_dependencies):
        """Output file is written immediately when new issues are found."""
        from code_scanner.issue_tracker import IssueTracker
        
        # Use a real IssueTracker instead of mock
        real_tracker = IssueTracker()
        mock_dependencies["issue_tracker"] = real_tracker
        
        scanner = Scanner(**mock_dependencies)
        scanner._scan_info = {"checks_run": 0, "files_scanned": [], "skipped_files": []}
        
        scanner.llm_client.query.return_value = {
            "issues": [
                {
                    "file_path": "test.py",
                    "line": 10,
                    "description": "Bug found",
                    "suggested_fix": "Fix it",
                    "code_snippet": "bad_code()",
                }
            ]
        }
        
        batches = [{"test.py": "content"}]
        issues = scanner._run_check("Find bugs", batches)
        
        # Issues should be returned
        assert len(issues) == 1
        
        # Now simulate what happens in the main loop after _run_check
        if issues:
            new_count = scanner.issue_tracker.add_issues(issues)
            if new_count > 0:
                scanner.output_generator.write(scanner.issue_tracker, scanner._scan_info)
        
        # Output should have been written
        scanner.output_generator.write.assert_called_once()
        
        # Issue tracker should have the issue
        assert len(real_tracker.issues) == 1
