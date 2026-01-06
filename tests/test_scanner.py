"""Tests for scanner module - integration tests."""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.scanner import Scanner
from code_scanner.models import GitState, ChangedFile, Issue, LLMConfig
from code_scanner.config import Config
from code_scanner.ctags_index import CtagsIndex


class TestScanner:
    """Tests for Scanner class - basic tests only.
    
    Full scanner testing requires mocking multiple dependencies.
    """

    @pytest.fixture
    def temp_config(self, temp_dir: Path) -> Config:
        """Create config for testing."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
checks = [
    "Find heap allocations without smart pointers",
    "Find repeated string literals"
]

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

    def test_scanner_requires_dependencies(self, temp_config: Config, mock_ctags_index):
        """Test that scanner requires all dependencies."""
        # Scanner needs git_watcher, llm_client, issue_tracker, output_generator
        # This tests the constructor signature
        git_watcher = MagicMock()
        llm_client = MagicMock()
        llm_client.context_limit = 8192  # Need a real value for AIToolExecutor
        issue_tracker = MagicMock()
        output_generator = MagicMock()
        
        scanner = Scanner(
            config=temp_config,
            git_watcher=git_watcher,
            llm_client=llm_client,
            issue_tracker=issue_tracker,
            output_generator=output_generator,
            ctags_index=mock_ctags_index,
        )
        
        assert scanner.config == temp_config


class TestGitState:
    """Tests for GitState model."""

    def test_git_state_no_changes(self):
        """Test GitState with no changes."""
        state = GitState()
        
        assert not state.has_changes
        assert not state.is_merging
        assert not state.is_rebasing

    def test_git_state_with_changes(self):
        """Test GitState with changed files."""
        state = GitState(
            changed_files=[
                ChangedFile(path="test.cpp", status="unstaged"),
            ]
        )
        
        assert state.has_changes
        assert len(state.changed_files) == 1

    def test_git_state_conflict_resolution(self):
        """Test GitState conflict resolution detection."""
        state = GitState(is_merging=True)
        
        assert state.is_conflict_resolution_in_progress

        state2 = GitState(is_rebasing=True)
        
        assert state2.is_conflict_resolution_in_progress


class TestChangedFile:
    """Tests for ChangedFile model."""

    def test_changed_file_not_deleted(self):
        """Test normal changed file."""
        file = ChangedFile(path="test.cpp", status="unstaged")
        
        assert file.path == "test.cpp"
        assert not file.is_deleted

    def test_changed_file_deleted(self):
        """Test deleted file detection."""
        file = ChangedFile(path="deleted.cpp", status="deleted")
        
        assert file.is_deleted


class TestIssueFromLLMResponse:
    """Tests for Issue.from_llm_response."""

    def test_create_from_response(self):
        """Test creating issue from LLM response data."""
        data = {
            "file": "test.cpp",
            "line_number": 42,
            "description": "Test issue",
            "suggested_fix": "Fix it",
            "code_snippet": "bad code",
        }
        
        issue = Issue.from_llm_response(data, check_query="test check")
        
        assert issue.file_path == "test.cpp"
        assert issue.line_number == 42
        assert issue.description == "Test issue"
        assert issue.check_query == "test check"

    def test_create_from_response_alternate_keys(self):
        """Test creating issue with alternate key names."""
        data = {
            "file_path": "test.cpp",  # Alternate key
            "line": 42,  # Alternate key
            "description": "Test issue",
            "fix": "Fix it",  # Alternate key
        }
        
        issue = Issue.from_llm_response(data, check_query="test check")
        
        assert issue.file_path == "test.cpp"
        assert issue.line_number == 42

    def test_create_from_response_with_timestamp(self):
        """Test creating issue with explicit timestamp."""
        data = {
            "file": "test.cpp",
            "line_number": 1,
            "description": "Test",
        }
        ts = datetime(2024, 1, 1, 12, 0, 0)
        
        issue = Issue.from_llm_response(data, check_query="test", timestamp=ts)
        
        assert issue.timestamp == ts

    def test_create_from_response_missing_fields(self):
        """Test creating issue with missing optional fields."""
        data = {
            "description": "Test issue only",
        }
        
        issue = Issue.from_llm_response(data, check_query="test")
        
        assert issue.file_path == ""
        assert issue.line_number == 0
        assert issue.suggested_fix == ""
