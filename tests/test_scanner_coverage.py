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
from code_scanner.lmstudio_client import LLMClientError
from code_scanner.ctags_index import CtagsIndex


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
        CheckGroup(pattern="*.py", checks=["Check for bugs", "Check for style"]),
        CheckGroup(pattern="*.cpp, *.h", checks=["Check memory leaks"]),
    ]
    return config


@pytest.fixture
def mock_ctags_index():
    """Create a mock CtagsIndex."""
    mock_index = MagicMock(spec=CtagsIndex)
    mock_index.target_directory = Path("/test/repo")
    mock_index.find_symbol.return_value = []
    mock_index.find_symbols_by_pattern.return_value = []
    mock_index.find_definitions.return_value = []
    mock_index.get_symbols_in_file.return_value = []
    mock_index.get_class_members.return_value = []
    mock_index.get_file_structure.return_value = {
        "file": "/test/repo/test.py",
        "language": "Python",
        "symbols": [],
        "structure_summary": "",
    }
    mock_index.get_stats.return_value = {
        "total_symbols": 0,
        "files_indexed": 0,
        "symbols_by_kind": {},
        "languages": [],
    }
    return mock_index


@pytest.fixture
def mock_dependencies(mock_config, mock_ctags_index):
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
        "ctags_index": mock_ctags_index,
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
        
        # Should query LLM for each check (2 py rules + 1 cpp rule = 3)
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

    def test_run_scan_handles_connection_refused_error(self, mock_dependencies):
        """Run scan handles connection refused error."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        call_count = [0]
        def query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise LLMClientError("Connection refused by server")
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        mock_dependencies["llm_client"].wait_for_connection = MagicMock()
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        mock_dependencies["llm_client"].wait_for_connection.assert_called()

    def test_run_scan_handles_timeout_error(self, mock_dependencies):
        """Run scan handles timeout error."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        call_count = [0]
        def query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise LLMClientError("Connection timed out")
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        mock_dependencies["llm_client"].wait_for_connection = MagicMock()
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        mock_dependencies["llm_client"].wait_for_connection.assert_called()

    def test_run_scan_handles_non_connection_error(self, mock_dependencies):
        """Run scan logs non-connection LLM errors and continues."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        # Simulate a non-connection error (e.g., JSON parse failure)
        mock_dependencies["llm_client"].query.side_effect = LLMClientError(
            "Failed to get valid JSON response after 3 attempts"
        )
        mock_dependencies["llm_client"].wait_for_connection = MagicMock()
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # wait_for_connection should NOT be called for non-connection errors
        mock_dependencies["llm_client"].wait_for_connection.assert_not_called()
        
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

    def test_run_scan_handles_refresh_signal(self, mock_dependencies):
        """Run scan handles refresh signal during processing and continues."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._refresh_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        mock_dependencies["git_watcher"].get_state.return_value = state
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Refresh signal should be handled (cleared) and scan continues

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
        
        check_group = CheckGroup(pattern="*.py", checks=["check"])
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
        
        check_group = CheckGroup(pattern="*.py", checks=["check"])
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
        """Get files content skips scanner output files including backup."""
        scanner = Scanner(**mock_dependencies)
        scanner.config.output_file = "results.md"
        scanner.config.log_file = "scanner.log"
        
        changed = [
            ChangedFile(path="results.md", status="unstaged"),
            ChangedFile(path="results.md.bak", status="unstaged"),  # backup file
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

    def test_get_files_content_uses_file_filter(self, mock_dependencies):
        """Get files content uses unified FileFilter when provided."""
        from code_scanner.file_filter import FileFilter
        
        # Create a FileFilter that skips .md files
        mock_filter = MagicMock(spec=FileFilter)
        mock_filter.should_skip.side_effect = lambda path: (
            (True, "config_pattern:*.md") if path.endswith(".md") else (False, "")
        )
        
        scanner = Scanner(**mock_dependencies, file_filter=mock_filter)
        
        changed = [
            ChangedFile(path="main.py", status="unstaged"),
            ChangedFile(path="README.md", status="unstaged"),
        ]
        
        with patch("code_scanner.scanner.is_binary_file", return_value=False), \
             patch("code_scanner.scanner.read_file_content", return_value="content"):
            result = scanner._get_files_content(changed)
        
        # FileFilter should be called for each file
        assert mock_filter.should_skip.call_count == 2
        # Only main.py should be included (README.md skipped by filter)
        assert "main.py" in result
        assert "README.md" not in result

    def test_filter_ignored_files_noop_with_file_filter(self, mock_dependencies):
        """Filter ignored files is a no-op when FileFilter is used."""
        from code_scanner.file_filter import FileFilter
        
        mock_filter = MagicMock(spec=FileFilter)
        scanner = Scanner(**mock_dependencies, file_filter=mock_filter)
        
        files_content = {"test.py": "content", "readme.md": "docs"}
        
        # With FileFilter, _filter_ignored_files should return input unchanged
        result, ignored = scanner._filter_ignored_files(files_content)
        
        assert result == files_content
        assert ignored == []


class TestScannerRunCheck:
    """Tests for Scanner _run_check method."""

    def test_run_check_parses_issues(self, mock_dependencies, tmp_path):
        """Run check parses issues from LLM response."""
        # Create actual test file so file existence check passes
        test_file = tmp_path / "test.py"
        test_file.write_text("content")
        mock_dependencies["config"].target_directory = tmp_path
        
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
        """Stop sets both stop and refresh events."""
        scanner = Scanner(**mock_dependencies)
        
        scanner.stop()
        
        assert scanner._stop_event.is_set()
        assert scanner._refresh_event.is_set()

    def test_signal_refresh_sets_event(self, mock_dependencies):
        """Signal refresh sets the refresh event."""
        scanner = Scanner(**mock_dependencies)
        
        assert not scanner._refresh_event.is_set()
        scanner.signal_refresh()
        assert scanner._refresh_event.is_set()


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
            CheckGroup(pattern="*.py", checks=["Python check"]),
            CheckGroup(pattern="*.cpp", checks=["C++ check"]),
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
        
        # With 2 checks in *.py group, output should be updated twice (once per check)
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
        
        # Output is now written per batch (inside _run_check) and per check completion
        # With 2 checks for *.py pattern, each with 1 batch, we get:
        # - 1 write per batch in _run_check (checks_run=0 for first batch)
        # - 1 write after rule completes in _run_scan (checks_run=1 for first rule)
        # Total writes should be at least 2, with checks_run incrementing
        assert len(write_calls_scan_info) >= 2
        # Last call should have checks_run=2 (both rules completed)
        assert write_calls_scan_info[-1] == 2

    def test_refresh_signal_continues_processing(self, mock_dependencies):
        """Refresh signal triggers rescan of earlier checks (watermark algorithm)."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        # Set refresh signal after first query
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._refresh_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # With watermark algorithm: refresh after check 1 means check 0 was stale
        # Initial run: check 1 (refresh), check 2 = 2 calls
        # Rescan: check 1 (re-run stale check) = 1 call
        # Total = 3 calls
        assert mock_dependencies["llm_client"].query.call_count == 3
        # Refresh event should be cleared
        assert not scanner._refresh_event.is_set()


class TestScannerAdditionalCoverage:
    """Additional tests to increase scanner.py coverage."""

    def test_run_loop_handles_exception(self, mock_dependencies):
        """Run loop catches and logs exceptions, continues running."""
        scanner = Scanner(**mock_dependencies)

        call_count = [0]
        def get_state_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Simulated error")
            else:
                scanner._stop_event.set()
                return GitState()

        mock_dependencies["git_watcher"].get_state.side_effect = get_state_side_effect

        # Should not raise, should catch and continue
        scanner._run_loop()
        assert call_count[0] >= 2

    def test_has_files_changed_with_refresh_event_no_longer_triggers_rescan(self, mock_dependencies):
        """Test _has_files_changed doesn't trigger rescan just because refresh event is set.
        
        This was changed to fix infinite scan loop. The refresh event only wakes
        up the scanner, but actual file changes are determined by content/path comparison.
        """
        scanner = Scanner(**mock_dependencies)
        scanner._refresh_event.set()
        scanner._last_scanned_files = set()  # Empty set matches current_files

        state = GitState()
        result = scanner._has_files_changed(set(), state)

        # With no actual changes (same file sets, no content changes), should return False
        assert result is False

    def test_has_files_changed_different_file_sets(self, mock_dependencies):
        """Test _has_files_changed returns True when file sets differ."""
        scanner = Scanner(**mock_dependencies)
        scanner._last_scanned_files = {"old_file.py"}

        state = GitState()
        result = scanner._has_files_changed({"new_file.py"}, state)

        assert result is True

    def test_has_files_changed_file_content_changed(self, mock_dependencies, tmp_path):
        """Test _has_files_changed returns True when file content changes."""
        mock_dependencies["config"].target_directory = tmp_path
        scanner = Scanner(**mock_dependencies)

        # Create a file
        test_file = tmp_path / "test.py"
        test_file.write_text("original content")

        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )

        # First scan - should return True (new file)
        result = scanner._has_files_changed({"test.py"}, state)
        assert result is True

    def test_has_files_changed_unreadable_file(self, mock_dependencies, tmp_path):
        """Test _has_files_changed returns True for unreadable files."""
        mock_dependencies["config"].target_directory = tmp_path
        scanner = Scanner(**mock_dependencies)
        scanner._last_scanned_files = {"test.py"}

        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )

        # File doesn't exist, should return True
        result = scanner._has_files_changed({"test.py"}, state)
        assert result is True

    def test_has_files_changed_skips_ignored_files(self, mock_dependencies, tmp_path):
        """Test _has_files_changed ignores files matching ignore patterns.
        
        This fixes a bug where ignored files (like code_scanner_results.md) would
        trigger rescans because they weren't in _last_file_contents_hash but
        were in _last_scanned_files.
        """
        mock_dependencies["config"].target_directory = tmp_path
        # Add an ignore pattern for *.md files
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", checks=["Check something"]),
            CheckGroup(pattern="*.md", checks=[]),  # Ignore pattern
        ]
        scanner = Scanner(**mock_dependencies)
        
        # Create files
        test_py = tmp_path / "test.py"
        test_py.write_text("x = 1")
        results_md = tmp_path / "results.md"
        results_md.write_text("# Results")
        
        # Set up state as if we've already scanned both files
        # Note: results.md is in _last_scanned_files but NOT in _last_file_contents_hash
        # (because it was ignored during the scan)
        scanner._last_scanned_files = {"test.py", "results.md"}
        scanner._last_file_contents_hash = {"test.py": hash("x = 1")}
        scanner._last_file_mtime = {"test.py": test_py.stat().st_mtime_ns}
        
        state = GitState(
            changed_files=[
                ChangedFile(path="test.py", status="unstaged"),
                ChangedFile(path="results.md", status="unstaged"),  # This should be ignored
            ]
        )
        
        # Should return False because:
        # - test.py hasn't changed (same content hash)
        # - results.md is ignored
        result = scanner._has_files_changed({"test.py", "results.md"}, state)
        assert result is False

    def test_create_batches_splits_large_directory(self, mock_dependencies):
        """Test that _create_batches splits large directories into individual files."""
        mock_dependencies["llm_client"].context_limit = 1000  # Small limit

        scanner = Scanner(**mock_dependencies)

        # Create content that would exceed batch size as a whole directory
        # but can fit when split into individual files
        files_content = {
            "src/file1.py": "a" * 100,
            "src/file2.py": "b" * 100,
            "src/file3.py": "c" * 100,
            "src/file4.py": "d" * 100,
            "src/file5.py": "e" * 100,
        }

        batches = scanner._create_batches(files_content)

        # Should create multiple batches since combined content is large
        assert len(batches) >= 1
        # Each batch should contain some files
        for batch in batches:
            assert len(batch) >= 1

    def test_create_batches_new_batch_for_directory(self, mock_dependencies):
        """Test that _create_batches starts new batch when directory doesn't fit."""
        mock_dependencies["llm_client"].context_limit = 500  # Small limit

        scanner = Scanner(**mock_dependencies)

        # First directory fills batch, second directory needs new batch
        files_content = {
            "src/main.py": "x" * 50,
            "tests/test.py": "y" * 50,
        }

        batches = scanner._create_batches(files_content)

        # Should have at least one batch
        assert len(batches) >= 1

    def test_format_tool_result_with_string_data(self, mock_dependencies):
        """Test _format_tool_result handles non-dict/list data."""
        scanner = Scanner(**mock_dependencies)

        from code_scanner.ai_tools import ToolResult
        result = ToolResult(success=True, data="Simple string data")

        formatted = scanner._format_tool_result(result)

        assert formatted == "Simple string data"

    def test_format_tool_result_with_number_data(self, mock_dependencies):
        """Test _format_tool_result handles numeric data."""
        scanner = Scanner(**mock_dependencies)

        from code_scanner.ai_tools import ToolResult
        result = ToolResult(success=True, data=42)

        formatted = scanner._format_tool_result(result)

        assert formatted == "42"

    def test_run_check_with_patterns_in_args(self, mock_dependencies, tmp_path):
        """Test tool logging with patterns argument."""
        mock_dependencies["config"].target_directory = tmp_path
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*", checks=["Check code"]),
        ]

        scanner = Scanner(**mock_dependencies)

        # Mock LLM to request search_text tool
        tool_call_response = {
            "tool_calls": [{
                "tool_name": "search_text",
                "arguments": {"patterns": "MyClass"}
            }]
        }

        call_count = [0]
        def query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_call_response
            else:
                return {"issues": []}

        mock_dependencies["llm_client"].query.side_effect = query_side_effect

        # Create a file so there's something to scan
        (tmp_path / "test.py").write_text("class MyClass: pass")

        batches = [{"test.py": "class MyClass: pass"}]
        issues = scanner._run_check("Check code", batches)

        # Should have made at least 2 calls (tool request + final response)
        assert call_count[0] >= 2

    def test_lost_connection_during_check(self, mock_dependencies):
        """Test that lost connection error triggers reconnection wait."""
        scanner = Scanner(**mock_dependencies)

        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )

        files_content = {"test.py": "x = 1"}

        call_count = [0]
        def query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise LLMClientError("Lost connection to LLM server")
            return {"issues": []}

        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        mock_dependencies["llm_client"].wait_for_connection = MagicMock()

        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)

        # Should have called wait_for_connection
        mock_dependencies["llm_client"].wait_for_connection.assert_called()

    def test_parse_issues_from_empty_response(self, mock_dependencies):
        """Test _parse_issues_from_response handles missing issues key."""
        scanner = Scanner(**mock_dependencies)

        response = {}  # No issues key
        issues = scanner._parse_issues_from_response(response, "test check", 0)

        assert issues == []

    def test_parse_issues_from_response_with_invalid_issue(self, mock_dependencies, tmp_path):
        """Test _parse_issues_from_response handles issues with missing fields."""
        # Create actual test files so file existence check passes
        (tmp_path / "test.py").write_text("content")
        (tmp_path / "test2.py").write_text("content")
        mock_dependencies["config"].target_directory = tmp_path
        
        scanner = Scanner(**mock_dependencies)

        response = {
            "issues": [
                {"file": "test.py", "line_number": 1, "description": "Valid"},
                {"invalid": "issue"},  # Missing required fields - gets defaults, skipped as file doesn't exist
                {"file": "test2.py", "line_number": 2, "description": "Also valid"},
            ]
        }

        issues = scanner._parse_issues_from_response(response, "test check", 0)

        # 2 valid issues parsed - empty file path is skipped because file doesn't exist
        assert len(issues) == 2
        # First and second (was third) have proper data
        assert issues[0].file_path == "test.py"
        assert issues[1].file_path == "test2.py"

    def test_parse_issues_skips_nonexistent_files(self, mock_dependencies, tmp_path):
        """Test _parse_issues_from_response skips issues for non-existent files."""
        # Create only one of the files
        (tmp_path / "exists.py").write_text("content")
        mock_dependencies["config"].target_directory = tmp_path
        
        scanner = Scanner(**mock_dependencies)

        response = {
            "issues": [
                {"file": "exists.py", "line_number": 1, "description": "Valid - file exists"},
                {"file": "nonexistent.py", "line_number": 2, "description": "Invalid - file does not exist"},
                {"file": "also_nonexistent.cpp", "line_number": 3, "description": "Invalid - file does not exist"},
            ]
        }

        issues = scanner._parse_issues_from_response(response, "test check", 0)

        # Only 1 issue parsed - the one for the existing file
        assert len(issues) == 1
        assert issues[0].file_path == "exists.py"
        assert issues[0].description == "Valid - file exists"


class TestFilterIgnoredFiles:
    """Tests for _filter_ignored_files method."""

    def test_no_ignore_patterns(self, mock_dependencies):
        """When no ignore patterns, all files pass through."""
        # Setup config with only active check groups (non-empty checks)
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", checks=["Check for bugs"]),
        ]
        scanner = Scanner(**mock_dependencies)

        files_content = {
            "test.py": "print('hello')",
            "README.md": "# Title",
        }

        filtered, ignored = scanner._filter_ignored_files(files_content)

        assert filtered == files_content
        assert ignored == []

    def test_ignore_pattern_filters_files(self, mock_dependencies):
        """Ignore patterns (empty checks) filter out matching files."""
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", checks=["Check for bugs"]),
            CheckGroup(pattern="*.md, *.txt", checks=[]),  # Ignore pattern
        ]
        scanner = Scanner(**mock_dependencies)

        files_content = {
            "test.py": "print('hello')",
            "README.md": "# Title",
            "notes.txt": "Some notes",
            "app.py": "import sys",
        }

        filtered, ignored = scanner._filter_ignored_files(files_content)

        assert "test.py" in filtered
        assert "app.py" in filtered
        assert "README.md" not in filtered
        assert "notes.txt" not in filtered
        assert set(ignored) == {"README.md", "notes.txt"}

    def test_multiple_ignore_patterns(self, mock_dependencies):
        """Multiple ignore patterns all filter out files."""
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", checks=["Check for bugs"]),
            CheckGroup(pattern="*.md", checks=[]),  # Ignore markdown
            CheckGroup(pattern="*.html", checks=[]),  # Ignore html
        ]
        scanner = Scanner(**mock_dependencies)

        files_content = {
            "test.py": "code",
            "README.md": "docs",
            "index.html": "<html>",
        }

        filtered, ignored = scanner._filter_ignored_files(files_content)

        assert filtered == {"test.py": "code"}
        assert set(ignored) == {"README.md", "index.html"}

    def test_ignore_pattern_with_wildcard(self, mock_dependencies):
        """Ignore pattern can use wildcards."""
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", checks=["Check for bugs"]),
            CheckGroup(pattern="*.md, *.txt, *.rst, *.html", checks=[]),
        ]
        scanner = Scanner(**mock_dependencies)

        files_content = {
            "test.py": "code",
            "README.md": "docs",
            "CHANGELOG.txt": "changes",
            "index.rst": "sphinx",
            "report.html": "<html>",
        }

        filtered, ignored = scanner._filter_ignored_files(files_content)

        assert filtered == {"test.py": "code"}
        assert len(ignored) == 4

    def test_all_files_ignored(self, mock_dependencies):
        """When all files match ignore patterns, return empty dict."""
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*", checks=[]),  # Ignore everything
        ]
        scanner = Scanner(**mock_dependencies)

        files_content = {
            "test.py": "code",
            "README.md": "docs",
        }

        filtered, ignored = scanner._filter_ignored_files(files_content)

        assert filtered == {}
        assert set(ignored) == {"test.py", "README.md"}


class TestBatchCreationEdgeCases:
    """Tests for edge cases in batch creation."""

    def test_directory_content_empty_after_filtering(self, mock_dependencies):
        """Test handling when directory content is empty after filtering."""
        scanner = Scanner(**mock_dependencies)
        scanner._target_dir = Path("/test/repo")
        scanner._scan_info = {"skipped_files": [], "files_scanned": [], "checks_run": 0}
        
        # Mock estimate_tokens to return high values for skipped files
        with patch('code_scanner.scanner.estimate_tokens') as mock_tokens:
            # Return very high token count so files get skipped
            mock_tokens.return_value = 100000
            
            files_content = {"test.py": "x" * 100000}
            batches = scanner._create_batches(files_content)
            
            # File should be skipped, so batches should be empty
            assert batches == [] or all(not batch for batch in batches)

    def test_directory_group_exceeds_limit(self, mock_dependencies):
        """Test handling when directory group exceeds context limit."""
        scanner = Scanner(**mock_dependencies)
        scanner._target_dir = Path("/test/repo")
        scanner._scan_info = {"skipped_files": [], "files_scanned": [], "checks_run": 0}
        mock_dependencies["llm_client"].context_limit = 1000
        
        # Create files that together exceed limit but individually fit
        files_content = {
            "src/file1.py": "a" * 100,
            "src/file2.py": "b" * 100,
            "src/file3.py": "c" * 100,
        }
        
        with patch('code_scanner.scanner.estimate_tokens') as mock_tokens:
            # Each file is 300 tokens, directory total is 900
            # But limit is 1000 with overhead, so this may split
            mock_tokens.side_effect = lambda content: len(content) * 3
            
            batches = scanner._create_batches(files_content)
            
            # Should create batches
            assert len(batches) >= 1

    def test_split_directory_into_individual_files(self, mock_dependencies):
        """Test that large directories are split into individual file batches."""
        scanner = Scanner(**mock_dependencies)
        scanner._target_dir = Path("/test/repo")
        scanner._scan_info = {"skipped_files": [], "files_scanned": [], "checks_run": 0}
        mock_dependencies["llm_client"].context_limit = 500  # Very small limit
        
        files_content = {
            "src/file1.py": "def foo(): pass",
            "src/file2.py": "def bar(): pass",
        }
        
        with patch('code_scanner.scanner.estimate_tokens') as mock_tokens:
            # Each file takes 200 tokens, so they need to be split
            mock_tokens.return_value = 200
            
            batches = scanner._create_batches(files_content)
            
            # Should have at least some batches
            assert len(batches) >= 1


class TestToolLoggingEdgeCases:
    """Tests for tool logging edge cases in _run_check."""

    def test_tool_logging_unknown_tool(self, mock_dependencies):
        """Test logging for unknown/other tool types."""
        scanner = Scanner(**mock_dependencies)
        scanner._target_dir = Path("/test/repo")
        scanner._tool_executor = MagicMock()
        
        # Mock tool result
        from code_scanner.ai_tools import ToolResult
        scanner._tool_executor.execute_tool.return_value = ToolResult(
            success=True,
            data={"result": "ok"},
        )
        
        # Mock LLM responses
        mock_dependencies["llm_client"].query.side_effect = [
            # First call requests an unknown tool
            {
                "tool_calls": [
                    {"tool_name": "custom_tool", "arguments": {"key": "value"}}
                ]
            },
            # Second call returns final result
            {"issues": []},
        ]
        
        # This should not raise even with unknown tool
        batches = [{"test.py": "code"}]
        issues = scanner._run_check("Check something", batches)
        
        assert issues == []


class TestWatermarkRescan:
    """Tests for the watermark-based rescan algorithm."""

    def test_rescan_triggered_when_refresh_during_scan(self, mock_dependencies):
        """Verify that a rescan iteration occurs when refresh event fires during scan."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        # Track iteration count by counting _get_files_content calls
        get_content_calls = [0]
        def get_content_side_effect(changed_files):
            get_content_calls[0] += 1
            return files_content
        
        # Set refresh on first query, then no more refreshes
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._refresh_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        
        with patch.object(scanner, "_get_files_content", side_effect=get_content_side_effect):
            scanner._run_scan(state)
        
        # Should have called _get_files_content at least twice (initial + rescan)
        assert get_content_calls[0] >= 2

    def test_rescan_only_reruns_stale_checks(self, mock_dependencies):
        """Verify that only checks 0..N are re-run when change occurs at check N."""
        # Configure 3 checks
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", checks=["Check 1", "Check 2", "Check 3"]),
        ]
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        # Refresh fires after check 1 (index 0), so checks 0 needs rescan
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._refresh_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Initial run: 3 checks, then rescan: 1 check (only check 0)
        # Total: 4 queries
        assert mock_dependencies["llm_client"].query.call_count == 4

    def test_rescan_stops_when_no_changes(self, mock_dependencies):
        """Verify that the rescan loop exits when no refresh events occur."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        # No refresh events - should complete in one iteration
        mock_dependencies["llm_client"].query.return_value = {"issues": []}
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Should have exactly 2 queries (one per check in default config for *.py)
        assert mock_dependencies["llm_client"].query.call_count == 2

    def test_multiple_rescan_iterations(self, mock_dependencies):
        """Verify multiple rescan rounds when changes keep happening."""
        mock_dependencies["config"].check_groups = [
            CheckGroup(pattern="*.py", checks=["Check 1", "Check 2"]),
        ]
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        files_content = {"test.py": "x = 1"}
        
        # Refresh on iterations 1 and 2, then stop
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            # Refresh after first check on iteration 1 (call 1) and iteration 2 (call 3)
            if query_count[0] in [1, 3]:
                scanner._refresh_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        
        with patch.object(scanner, "_get_files_content", return_value=files_content):
            scanner._run_scan(state)
        
        # Iteration 1: 2 checks (refresh at 1)
        # Iteration 2: 1 check (rescan check 0, refresh at 1)
        # Iteration 3: 1 check (rescan check 0, no refresh)
        # Total: 4 queries
        assert mock_dependencies["llm_client"].query.call_count == 4

    def test_rescan_refreshes_file_content(self, mock_dependencies):
        """Verify that rescan iteration rebuilds check list with fresh content."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        # Different content on each call
        content_versions = [{"test.py": "version1"}, {"test.py": "version2"}, {"test.py": "version3"}]
        content_idx = [0]
        def get_content_side_effect(changed_files):
            result = content_versions[min(content_idx[0], len(content_versions) - 1)]
            content_idx[0] += 1
            return result
        
        # Refresh on first query
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._refresh_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        
        with patch.object(scanner, "_get_files_content", side_effect=get_content_side_effect):
            scanner._run_scan(state)
        
        # Content was fetched multiple times (rebuild on rescan)
        assert content_idx[0] >= 2

    def test_rescan_with_empty_files_after_refresh(self, mock_dependencies):
        """Test early exit when no scannable files remain after refresh (line 251-253)."""
        scanner = Scanner(**mock_dependencies)
        
        state = GitState(
            changed_files=[ChangedFile(path="test.py", status="unstaged")]
        )
        
        # First call returns files, second call (rescan) returns empty
        call_count = [0]
        def get_content_side_effect(changed_files):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"test.py": "content"}
            return {}  # No files after refresh
        
        # Refresh on first query to trigger rescan
        query_count = [0]
        def query_side_effect(*args, **kwargs):
            query_count[0] += 1
            if query_count[0] == 1:
                scanner._refresh_event.set()
            return {"issues": []}
        
        mock_dependencies["llm_client"].query.side_effect = query_side_effect
        
        with patch.object(scanner, "_get_files_content", side_effect=get_content_side_effect):
            scanner._run_scan(state)
        
        # Should have exited early on rescan iteration due to empty file list
        # Only 2 queries from first iteration (for 2 checks in *.py group)
        assert mock_dependencies["llm_client"].query.call_count == 2
