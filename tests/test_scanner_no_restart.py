"""Test that scanner doesn't restart when no files have actually changed."""

import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.scanner import Scanner
from code_scanner.models import GitState, ChangedFile, Issue, LLMConfig
from code_scanner.config import Config
from code_scanner.ctags_index import CtagsIndex
from code_scanner.issue_tracker import IssueTracker
from code_scanner.output import OutputGenerator


class TestScannerNoRestart:
    """Test that scanner correctly detects when files haven't actually changed."""

    @pytest.fixture
    def temp_config(self, temp_dir: Path) -> Config:
        """Create config for testing."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
[[checks]]
pattern = "*.cpp"
checks = [
    "Find heap allocations without smart pointers"
]

[[checks]]
pattern = "*.md"
# Ignore markdown files

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
context_limit = 16384
""")
        from code_scanner.config import load_config
        return load_config(temp_dir, config_file)

    @pytest.fixture
    def mock_ctags_index(self, temp_dir: Path):
        """Create a mock CtagsIndex."""
        mock_index = MagicMock(spec=CtagsIndex)
        mock_index.target_directory = temp_dir
        mock_index.find_symbol.return_value = []
        mock_index.find_symbols_by_pattern.return_value = []
        mock_index.find_definitions.return_value = []
        mock_index.get_symbols_in_file.return_value = []
        mock_index.get_class_members.return_value = []
        mock_index.get_file_structure.return_value = {
            "file": str(temp_dir / "test.py"),
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
    def mock_git_watcher(self, temp_dir: Path):
        """Create a mock GitWatcher."""
        mock_watcher = MagicMock()
        mock_watcher.repo_path = temp_dir
        
        # Create some test files
        test_file1 = temp_dir / "test.cpp"
        test_file1.write_text("int main() { return 0; }")
        
        test_file2 = temp_dir / "test.md"
        test_file2.write_text("# Documentation")
        
        # Mock git state with changed files
        def mock_get_state(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="test.cpp", status="unstaged"),
                ChangedFile(path="test.md", status="unstaged"),  # This should be ignored
            ]
            return state
        
        mock_watcher.get_state = mock_get_state
        return mock_watcher

    @pytest.fixture
    def mock_llm_client(self):
        """Create a mock LLM client."""
        mock_client = MagicMock()
        mock_client.context_limit = 8192
        mock_client.wait_for_connection = MagicMock()
        return mock_client

    @pytest.fixture
    def mock_issue_tracker(self):
        """Create a mock issue tracker."""
        mock_tracker = MagicMock(spec=IssueTracker)
        mock_tracker.add_issues.return_value = 0
        mock_tracker.update_from_scan.return_value = (0, 0)
        mock_tracker.get_stats.return_value = {"total": 0}
        return mock_tracker

    @pytest.fixture
    def mock_output_generator(self, temp_dir: Path):
        """Create a mock output generator."""
        mock_gen = MagicMock(spec=OutputGenerator)
        mock_gen.write = MagicMock()
        return mock_gen

    def test_has_files_changed_returns_false_when_no_actual_changes(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
    ):
        """Test that _has_files_changed() returns False when files haven't actually changed."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Get initial git state
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # First check - should return True because _last_scanned_files is empty
        assert scanner._has_files_changed(current_files, git_state) is True
        
        # Simulate that files were scanned (populate _last_scanned_files and _last_file_contents_hash)
        scanner._last_scanned_files = {"test.cpp"}  # Only non-ignored files
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Second check - should return False because files haven't actually changed
        assert scanner._has_files_changed(current_files, git_state) is False

    def test_has_files_changed_ignores_ignored_files(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
    ):
        """Test that _has_files_changed() ignores files matching ignore patterns."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Get git state
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files with only non-ignored file
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Should return False even though test.md is in git_state.changed_files
        # because test.md matches ignore pattern (*.md)
        assert scanner._has_files_changed(current_files, git_state) is False

    def test_has_files_changed_returns_true_when_new_file_added(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
        temp_dir: Path,
    ):
        """Test that _has_files_changed() returns True when a new file is added."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Create a new file
        new_file = temp_dir / "new.cpp"
        new_file.write_text("void new_func() {}")
        
        # Update git state to include new file
        def mock_get_state_with_new(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="test.cpp", status="unstaged"),
                ChangedFile(path="test.md", status="unstaged"),
                ChangedFile(path="new.cpp", status="unstaged"),
            ]
            return state
        
        mock_git_watcher.get_state = mock_get_state_with_new
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files with only test.cpp
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Should return True because new.cpp is a new file
        assert scanner._has_files_changed(current_files, git_state) is True

    def test_has_files_changed_returns_true_when_file_content_changes(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
        temp_dir: Path,
    ):
        """Test that _has_files_changed() returns True when file content changes."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Modify test.cpp
        test_file = temp_dir / "test.cpp"
        test_file.write_text("int main() { return 1; }")  # Changed from 0 to 1
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files with old content hash
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}  # Old hash
        
        # Should return True because test.cpp content changed
        assert scanner._has_files_changed(current_files, git_state) is True

    def test_has_files_changed_returns_false_when_file_removed(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
    ):
        """Test that _has_files_changed() returns False when a file is removed (committed)."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Populate _last_scanned_files with test.cpp
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Create git state without test.cpp (file was committed)
        def mock_get_state_without_file(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="test.md", status="unstaged"),
            ]
            return state
        
        mock_git_watcher.get_state = mock_get_state_without_file
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Should return False because test.cpp was removed (committed), not a new change
        assert scanner._has_files_changed(current_files, git_state) is False

    def test_has_files_changed_handles_deleted_files(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
        temp_dir: Path,
    ):
        """Test that _has_files_changed() correctly handles deleted files."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Create git state with a deleted file
        def mock_get_state_with_deleted(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="test.cpp", status="unstaged"),
                ChangedFile(path="deleted.cpp", status="deleted"),
            ]
            return state
        
        mock_git_watcher.get_state = mock_get_state_with_deleted
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Should return False because deleted files are excluded from current_files
        assert scanner._has_files_changed(current_files, git_state) is False

    def test_has_files_changed_handles_binary_files(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
        temp_dir: Path,
    ):
        """Test that _has_files_changed() correctly handles binary files."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Create a binary file
        binary_file = temp_dir / "test.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\x04\x05")
        
        # Create git state with binary file
        def mock_get_state_with_binary(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="test.cpp", status="unstaged"),
                ChangedFile(path="test.bin", status="unstaged"),
            ]
            return state
        
        mock_git_watcher.get_state = mock_get_state_with_binary
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files without binary file
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Should return True because test.bin is a new file
        assert scanner._has_files_changed(current_files, git_state) is True

    def test_has_files_changed_handles_multiple_files(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
        temp_dir: Path,
    ):
        """Test that _has_files_changed() correctly handles multiple files."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Create multiple files
        file1 = temp_dir / "file1.cpp"
        file1.write_text("void func1() {}")
        
        file2 = temp_dir / "file2.cpp"
        file2.write_text("void func2() {}")
        
        file3 = temp_dir / "file3.cpp"
        file3.write_text("void func3() {}")
        
        # Create git state with multiple files
        def mock_get_state_multiple(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="file1.cpp", status="unstaged"),
                ChangedFile(path="file2.cpp", status="unstaged"),
                ChangedFile(path="file3.cpp", status="unstaged"),
            ]
            return state
        
        mock_git_watcher.get_state = mock_get_state_multiple
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files with only file1 and file2
        scanner._last_scanned_files = {"file1.cpp", "file2.cpp"}
        scanner._last_file_contents_hash = {
            "file1.cpp": hash("void func1() {}"),
            "file2.cpp": hash("void func2() {}"),
        }
        
        # Should return True because file3.cpp is a new file
        assert scanner._has_files_changed(current_files, git_state) is True

    def test_has_files_changed_handles_whitespace_changes(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
        temp_dir: Path,
    ):
        """Test that _has_files_changed() detects whitespace changes."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Modify test.cpp with whitespace change
        test_file = temp_dir / "test.cpp"
        test_file.write_text("int main() { return 0; }\n")  # Added newline
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files with old content hash (without newline)
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Should return True because whitespace changed
        assert scanner._has_files_changed(current_files, git_state) is True

    def test_has_files_changed_handles_os_errors_for_existing_files(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
    ):
        """Test that _has_files_changed() doesn't assume changes for existing files with OSError."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Populate _last_scanned_files with test.cpp
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Create git state with test.cpp (file exists but can't be read due to OSError)
        def mock_get_state_with_oserror(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="test.cpp", status="unstaged"),
            ]
            return state
        
        mock_git_watcher.get_state = mock_get_state_with_oserror
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Should return False because test.cpp is in _last_scanned_files (existing file)
        # even though it can't be read due to OSError
        assert scanner._has_files_changed(current_files, git_state) is False

    def test_has_files_changed_returns_true_for_new_files_with_oserror(
        self,
        temp_config: Config,
        mock_git_watcher,
        mock_llm_client,
        mock_issue_tracker,
        mock_output_generator,
        mock_ctags_index,
        temp_dir: Path,
    ):
        """Test that _has_files_changed() returns True for new files even with OSError."""
        scanner = Scanner(
            config=temp_config,
            git_watcher=mock_git_watcher,
            llm_client=mock_llm_client,
            issue_tracker=mock_issue_tracker,
            output_generator=mock_output_generator,
            ctags_index=mock_ctags_index,
        )
        
        # Create a new file (will be deleted before scan to cause OSError)
        new_file = temp_dir / "new.cpp"
        new_file.write_text("void new_func() {}")
        new_file.unlink()  # Delete it to cause OSError
        
        # Create git state with new file
        def mock_get_state_with_new_oserror(force_refresh: bool = False) -> GitState:
            state = GitState()
            state.changed_files = [
                ChangedFile(path="test.cpp", status="unstaged"),
                ChangedFile(path="new.cpp", status="unstaged"),
            ]
            return state
        
        mock_git_watcher.get_state = mock_get_state_with_new_oserror
        
        git_state = mock_git_watcher.get_state()
        current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
        
        # Populate _last_scanned_files with only test.cpp
        scanner._last_scanned_files = {"test.cpp"}
        scanner._last_file_contents_hash = {"test.cpp": hash("int main() { return 0; }")}
        
        # Should return True because new.cpp is a new file (not in _last_scanned_files)
        # even though it can't be read due to OSError
        assert scanner._has_files_changed(current_files, git_state) is True
