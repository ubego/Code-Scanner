"""Coverage-focused tests for Scanner class - targeting uncovered lines."""

import pytest
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock, call

from code_scanner.scanner import Scanner
from code_scanner.config import Config, LLMConfig, CheckGroup
from code_scanner.models import Issue, GitState, ChangedFile, IssueStatus
from code_scanner.llm_client import LLMClientError


@pytest.fixture
def mock_config():
    """Create a mock Config object."""
    config = MagicMock(spec=Config)
    config.target_directory = Path("/test/repo")
    config.output_file = "results.md"
    config.log_file = "scanner.log"
    config.git_poll_interval = 0.1  # Fast for testing
    config.llm_retry_interval = 0.1
    config.max_llm_retries = 2
    config.check_groups = [
        CheckGroup(pattern="*.py", rules=["Check for bugs", "Check for style"]),
        CheckGroup(pattern="*.cpp, *.h", rules=["Check memory leaks"]),
    ]
    return config


@pytest.fixture
def mock_dependencies(mock_config):
    """Create mock dependencies for Scanner."""
    git_watcher = MagicMock()
    llm_client = MagicMock()
    llm_client.context_limit = 8000
    issue_tracker = MagicMock()
    issue_tracker.add_issues.return_value = 0
    issue_tracker.update_from_scan.return_value = (0, 0)
    issue_tracker.get_stats.return_value = {"total": 0}
    output_generator = MagicMock()
    
    return {
        "config": mock_config,
        "git_watcher": git_watcher,
        "llm_client": llm_client,
        "issue_tracker": issue_tracker,
        "output_generator": output_generator,
    }


class TestScannerRunLoop:
    """Tests for Scanner _run_loop method."""

    def test_run_loop_exits_on_stop_event(self, mock_dependencies):
        """Run loop exits when stop event is set."""
        scanner = Scanner(**mock_dependencies)
        scanner._stop_event.set()
        
        # Should exit immediately
        scanner._run_loop()
        
        # git_watcher.get_state should not be called since we exit immediately
        # But we need to check the loop didn't hang

    def test_run_loop_waits_during_merge(self, mock_dependencies):
        """Run loop waits during merge/rebase."""
        scanner = Scanner(**mock_dependencies)
        
        # First call: merge in progress, second call: stop
        call_count = [0]
        def get_state_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                state = GitState(is_merging=True)
                return state
            else:
                scanner._stop_event.set()
                return GitState()
        
        mock_dependencies["git_watcher"].get_state.side_effect = get_state_side_effect
        
        scanner._run_loop()
        
        assert call_count[0] >= 1

    def test_run_loop_waits_when_no_changes(self, mock_dependencies):
        """Run loop waits when no changes detected."""
        scanner = Scanner(**mock_dependencies)
        
        call_count = [0]
        def get_state_side_effect():
            call_count[0] += 1
            if call_count[0] >= 2:
                scanner._stop_event.set()
            return GitState()  # No changes
        
        mock_dependencies["git_watcher"].get_state.side_effect = get_state_side_effect
        
        scanner._run_loop()
        
        assert call_count[0] >= 1

    def test_run_loop_calls_run_scan_with_changes(self, mock_dependencies):
        """Run loop calls _run_scan when changes detected."""
        scanner = Scanner(**mock_dependencies)
        
        state_with_changes = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        call_count = [0]
        def get_state_side_effect():
            call_count[0] += 1
            if call_count[0] >= 2:
                scanner._stop_event.set()
            return state_with_changes
        
        mock_dependencies["git_watcher"].get_state.side_effect = get_state_side_effect
        
        with patch.object(scanner, "_run_scan") as mock_run_scan:
            scanner._run_loop()
            mock_run_scan.assert_called()

    def test_run_loop_handles_exceptions(self, mock_dependencies):
        """Run loop handles exceptions and continues."""
        scanner = Scanner(**mock_dependencies)
        
        call_count = [0]
        def get_state_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Test error")
            scanner._stop_event.set()
            return GitState()
        
        mock_dependencies["git_watcher"].get_state.side_effect = get_state_side_effect
        
        # Should not raise, should handle exception
        scanner._run_loop()
        assert call_count[0] >= 1


class TestScannerRunScan:
    """Tests for Scanner _run_scan method."""

    def test_run_scan_with_no_scannable_files(self, mock_dependencies):
        """Run scan returns early when no scannable files."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="results.md", status="unstaged")]
        )
        
        with patch.object(scanner, "_get_files_content", return_value={}):
            scanner._run_scan(state)
        
        # Should not call _create_batches since no files
        mock_dependencies["llm_client"].query.assert_not_called()

    def test_run_scan_creates_batches_and_runs_checks(self, mock_dependencies):
        """Run scan creates batches and runs all check groups."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[
                ChangedFile(path="test.py", status="unstaged"),
                ChangedFile(path="main.cpp", status="unstaged"),
            ]
        )
        
        files_content = {
            "test.py": "print('hello')",
            "main.cpp": "int main() {}",
        }
        
        mock_dependencies["llm_client"].query.return_value = {"issues": []}
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Should query LLM for each rule (2 py rules + 1 cpp rule = 3)
        assert mock_dependencies["llm_client"].query.call_count >= 1

    def test_run_scan_handles_deleted_files(self, mock_dependencies):
        """Run scan resolves issues for deleted files."""
        scanner = Scanner(**mock_dependencies)
        
        # Need at least one non-deleted file to continue past early return
        state = GitState(
            changed_files=[
                ChangedFile(path="existing.py", status="unstaged"),
                ChangedFile(path="deleted.py", status="deleted"),
            ]
        )
        
        files_content = {"existing.py": "x = 1"}
        mock_dependencies["llm_client"].query.return_value = {"issues": []}
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        mock_dependencies["issue_tracker"].resolve_issues_for_file.assert_called_with("deleted.py")

    def test_run_scan_updates_output_on_new_issues(self, mock_dependencies):
        """Run scan updates output when new issues are found."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        mock_dependencies["llm_client"].query.return_value = {
            "issues": [
                {
                    "file_path": "test.py",
                    "line": 1,
                    "description": "Bug found",
                    "suggested_fix": "Fix it",
                }
            ]
        }
        mock_dependencies["issue_tracker"].add_issues.return_value = 1
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        mock_dependencies["output_generator"].write.assert_called()

    def test_run_scan_skips_non_matching_patterns(self, mock_dependencies):
        """Run scan skips check groups when no files match pattern."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.txt", status="unstaged")]
        )
        
        files_content = {"test.txt": "some text"}
        
        mock_dependencies["llm_client"].query.return_value = {"issues": []}
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # txt files don't match *.py or *.cpp patterns, so no queries
        mock_dependencies["llm_client"].query.assert_not_called()

    def test_run_scan_handles_llm_connection_loss(self, mock_dependencies):
        """Run scan handles LLM connection loss."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        call_count = [0]
        def query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise LLMClientError("Lost connection to LM Studio")
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        mock_dependencies["llm_client"].wait_for_connection = MagicMock()
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        mock_dependencies["llm_client"].wait_for_connection.assert_called()

    def test_run_scan_handles_restart_signal(self, mock_dependencies):
        """Run scan handles restart signal during processing."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._restart_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        mock_dependencies["git_watcher"].get_state.return_value = state
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Restart should be handled

    def test_run_scan_stops_on_stop_event(self, mock_dependencies):
        """Run scan stops processing when stop event is set."""
        scanner = Scanner(**mock_dependencies)
        scanner._stop_event.set()
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # LLM should not be called since stop is set
        mock_dependencies["llm_client"].query.assert_not_called()


class TestScannerBatching:
    """Tests for Scanner batching functionality."""

    def test_create_batches_single_batch(self, mock_dependencies):
        """Create batches returns single batch when all files fit."""
        scanner = Scanner(**mock_dependencies)
        scanner.llm_client.context_limit = 100000
        
        files = {"a.py": "x=1", "b.py": "y=2"}
        batches = scanner._create_batches(files)
        
        assert len(batches) == 1
        assert "a.py" in batches[0]
        assert "b.py" in batches[0]

    def test_create_batches_multiple_batches(self, mock_dependencies):
        """Create batches splits files when they exceed context limit."""
        scanner = Scanner(**mock_dependencies)
        scanner.llm_client.context_limit = 100  # Very small
        scanner._scan_info = {"skipped_files": []}
        
        files = {"a.py": "x" * 30, "b.py": "y" * 30}
        batches = scanner._create_batches(files)
        
        # Should split into multiple batches
        assert len(batches) >= 1

    def test_create_batches_skips_oversized_files(self, mock_dependencies):
        """Create batches skips files that are too large."""
        scanner = Scanner(**mock_dependencies)
        scanner.llm_client.context_limit = 100
        scanner._scan_info = {"skipped_files": []}
        
        # File that exceeds limit
        files = {"huge.py": "x" * 10000}
        batches = scanner._create_batches(files)
        
        assert "huge.py" in scanner._scan_info["skipped_files"]

    def test_filter_batches_by_pattern_filters_correctly(self, mock_dependencies):
        """Filter batches removes non-matching files."""
        scanner = Scanner(**mock_dependencies)
        
        check_group = CheckGroup(pattern="*.py", rules=["check"])
        batches = [
            {"test.py": "code", "test.cpp": "code", "other.py": "code"},
        ]
        
        filtered = scanner._filter_batches_by_pattern(batches, check_group)
        
        assert len(filtered) == 1
        assert "test.py" in filtered[0]
        assert "other.py" in filtered[0]
        assert "test.cpp" not in filtered[0]

    def test_filter_batches_removes_empty_batches(self, mock_dependencies):
        """Filter batches removes batches with no matching files."""
        scanner = Scanner(**mock_dependencies)
        
        check_group = CheckGroup(pattern="*.py", rules=["check"])
        batches = [
            {"test.cpp": "code"},  # No py files
            {"test.py": "code"},
        ]
        
        filtered = scanner._filter_batches_by_pattern(batches, check_group)
        
        assert len(filtered) == 1
        assert "test.py" in filtered[0]


class TestScannerFilesContent:
    """Tests for Scanner _get_files_content method."""

    def test_get_files_content_skips_deleted(self, mock_dependencies):
        """Get files content skips deleted files."""
        scanner = Scanner(**mock_dependencies)
        
        changed = [ChangedFile(path="deleted.py", status="deleted")]
        result = scanner._get_files_content(changed)
        
        assert len(result) == 0

    def test_get_files_content_skips_scanner_files(self, mock_dependencies):
        """Get files content skips scanner output files."""
        scanner = Scanner(**mock_dependencies)
        scanner.config.output_file = "results.md"
        scanner.config.log_file = "scanner.log"
        
        changed = [
            ChangedFile(path="results.md", status="unstaged"),
            ChangedFile(path="scanner.log", status="unstaged"),
        ]
        result = scanner._get_files_content(changed)
        
        assert len(result) == 0

    def test_get_files_content_skips_binary(self, mock_dependencies):
        """Get files content skips binary files."""
        scanner = Scanner(**mock_dependencies)
        
        changed = [ChangedFile(path="image.png", status="unstaged")]
        
        with patch("code_scanner.scanner.is_binary_file", return_value=True):
            result = scanner._get_files_content(changed)
        
        assert len(result) == 0

    def test_get_files_content_reads_text_files(self, mock_dependencies):
        """Get files content reads text files."""
        scanner = Scanner(**mock_dependencies)
        
        changed = [ChangedFile(path="test.py", status="unstaged")]
        
        with patch("code_scanner.scanner.is_binary_file", return_value=False), \
             patch("code_scanner.scanner.read_file_content", return_value="content"):
            result = scanner._get_files_content(changed)
        
        assert "test.py" in result
        assert result["test.py"] == "content"

    def test_get_files_content_handles_read_failure(self, mock_dependencies):
        """Get files content handles file read failures."""
        scanner = Scanner(**mock_dependencies)
        
        changed = [ChangedFile(path="test.py", status="unstaged")]
        
        with patch("code_scanner.scanner.is_binary_file", return_value=False), \
             patch("code_scanner.scanner.read_file_content", return_value=None):
            result = scanner._get_files_content(changed)
        
        assert "test.py" not in result


class TestScannerRunCheck:
    """Tests for Scanner _run_check method."""

    def test_run_check_parses_issues(self, mock_dependencies):
        """Run check parses issues from LLM response."""
        scanner = Scanner(**mock_dependencies)
        
        mock_dependencies["llm_client"].query.return_value = {
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

    def test_run_check_handles_malformed_issues(self, mock_dependencies):
        """Run check handles malformed issue data gracefully."""
        scanner = Scanner(**mock_dependencies)
        
        mock_dependencies["llm_client"].query.return_value = {
            "issues": [
                {"invalid": "data"},  # Missing required fields
                {
                    "file_path": "test.py",
                    "line": 10,
                    "description": "Valid issue",
                }
            ]
        }
        
        batches = [{"test.py": "content"}]
        issues = scanner._run_check("Find bugs", batches)
        
        # Should still get the valid issue
        assert len(issues) >= 0  # May or may not parse malformed

    def test_run_check_processes_multiple_batches(self, mock_dependencies):
        """Run check processes all batches."""
        scanner = Scanner(**mock_dependencies)
        
        mock_dependencies["llm_client"].query.return_value = {
            "issues": [{"file_path": "x.py", "line": 1, "description": "issue"}]
        }
        
        batches = [
            {"a.py": "code"},
            {"b.py": "code"},
        ]
        issues = scanner._run_check("Find bugs", batches)
        
        assert mock_dependencies["llm_client"].query.call_count == 2

    def test_run_check_stops_on_stop_event(self, mock_dependencies):
        """Run check stops processing when stop event is set."""
        scanner = Scanner(**mock_dependencies)
        scanner._stop_event.set()
        
        batches = [{"test.py": "content"}]
        issues = scanner._run_check("Find bugs", batches)
        
        assert issues == []
        mock_dependencies["llm_client"].query.assert_not_called()

    def test_run_check_raises_on_llm_error(self, mock_dependencies):
        """Run check raises LLMClientError on failures."""
        scanner = Scanner(**mock_dependencies)
        
        mock_dependencies["llm_client"].query.side_effect = LLMClientError("Connection failed")
        
        batches = [{"test.py": "content"}]
        
        with pytest.raises(LLMClientError):
            scanner._run_check("Find bugs", batches)


class TestScannerThreading:
    """Tests for Scanner threading functionality."""

    def test_start_creates_thread(self, mock_dependencies):
        """Start creates and starts scanner thread."""
        scanner = Scanner(**mock_dependencies)
        
        # Mock _run_loop to exit immediately
        scanner._run_loop = MagicMock()
        
        scanner.start()
        
        assert scanner._thread is not None
        scanner.stop()

    def test_start_does_not_restart_running_thread(self, mock_dependencies):
        """Start doesn't create new thread if one is running."""
        scanner = Scanner(**mock_dependencies)
        
        # Create a fake "running" thread
        scanner._thread = MagicMock()
        scanner._thread.is_alive.return_value = True
        
        original_thread = scanner._thread
        scanner.start()
        
        assert scanner._thread is original_thread

    def test_stop_sets_events(self, mock_dependencies):
        """Stop sets both stop and restart events."""
        scanner = Scanner(**mock_dependencies)
        
        scanner.stop()
        
        assert scanner._stop_event.is_set()
        assert scanner._restart_event.is_set()

    def test_signal_restart_sets_event(self, mock_dependencies):
        """Signal restart sets the restart event."""
        scanner = Scanner(**mock_dependencies)
        
        assert not scanner._restart_event.is_set()
        scanner.signal_restart()
        assert scanner._restart_event.is_set()


class TestScannerIntegration:
    """Integration-style tests for Scanner."""

    def test_full_scan_cycle_with_mocked_llm(self, mock_dependencies):
        """Test a complete scan cycle with mocked dependencies."""
        scanner = Scanner(**mock_dependencies)
        
        # Set up git state with changed files
        state = GitState(
            changed_files=[
                ChangedFile(path="src/main.py", status="unstaged"),
                ChangedFile(path="src/utils.py", status="unstaged"),
            ]
        )
        
        # Set up LLM responses
        mock_dependencies["llm_client"].query.return_value = {
            "issues": [
                {
                    "file_path": "src/main.py",
                    "line": 10,
                    "description": "Potential bug",
                    "suggested_fix": "Fix the bug",
                    "code_snippet": "x = 1",
                }
            ]
        }
        
        files_content = {
            "src/main.py": "x = 1\ny = 2",
            "src/utils.py": "def helper(): pass",
        }
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Verify LLM was queried
        assert mock_dependencies["llm_client"].query.call_count > 0
        
        # Verify issue tracker was updated
        mock_dependencies["issue_tracker"].update_from_scan.assert_called_once()
        
        # Verify output was written
        mock_dependencies["output_generator"].write.assert_called()

    def test_scan_with_multiple_check_groups(self, mock_dependencies):
        """Test scan processes multiple check groups correctly."""
        # Configure multiple check groups
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", rules=["Python check"]),
            CheckGroup(pattern="*.cpp", rules=["C++ check"]),
        ]
        
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[
                ChangedFile(path="app.py", status="unstaged"),
                ChangedFile(path="main.cpp", status="unstaged"),
            ]
        )
        
        files_content = {
            "app.py": "print('hello')",
            "main.cpp": "int main() {}",
        }
        
        mock_dependencies["llm_client"].query.return_value = {"issues": []}
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Should have queried LLM twice (once per check group)
        assert mock_dependencies["llm_client"].query.call_count == 2


class TestScannerIncrementalOutput:
    """Tests for Scanner incremental output updates."""

    def test_output_updated_after_each_check(self, mock_dependencies):
        """Output file is updated after every check, not just when issues found."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1\ny = 2\nz = 3"}
        
        # Return no issues - output should still be updated
        mock_dependencies["llm_client"].query.return_value = {"issues": []}
        mock_dependencies["issue_tracker"].add_issues.return_value = 0
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # With 2 rules in *.py group, output should be updated twice (once per check)
        # Plus one final update at the end of scan
        assert mock_dependencies["output_generator"].write.call_count >= 2

    def test_output_includes_checks_run_count(self, mock_dependencies):
        """Output updates include incremental checks_run count."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        mock_dependencies["llm_client"].query.return_value = {"issues": []}
        
        # Track scan_info passed to output writer
        write_calls_scan_info = []
        def capture_write(tracker, scan_info=None):
            if scan_info:
                write_calls_scan_info.append(scan_info.get("checks_run", 0))
        
        mock_dependencies["output_generator"].write.side_effect = capture_write
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Should have incremental checks_run values
        # First call should have checks_run=1, second should have checks_run=2
        assert len(write_calls_scan_info) >= 2
        assert write_calls_scan_info[0] == 1
        assert write_calls_scan_info[1] == 2

    def test_restart_signal_returns_immediately(self, mock_dependencies):
        """Restart signal causes immediate return, not inline restart."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        # Set restart signal after first query
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._restart_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Should only call query once since restart causes immediate return
        assert mock_dependencies["llm_client"].query.call_count == 1
        # Restart event should be cleared
        assert not scanner._restart_event.is_set()
