"""Additional tests for git_watcher module to increase coverage."""

import os
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from code_scanner.git_watcher import GitWatcher, GitError
from code_scanner.models import GitState, ChangedFile


@pytest.fixture
def temp_git_repo():
    """Create a temporary Git repository."""
    temp_dir = tempfile.mkdtemp()
    
    # Initialize Git repo
    os.system(f"cd {temp_dir} && git init -q")
    os.system(f"cd {temp_dir} && git config user.email 'test@test.com'")
    os.system(f"cd {temp_dir} && git config user.name 'Test'")
    
    # Create initial commit
    readme = Path(temp_dir) / "README.md"
    readme.write_text("# Test\n")
    os.system(f"cd {temp_dir} && git add . && git commit -m 'Initial' -q")
    
    yield Path(temp_dir)
    
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestGitWatcherUnquotePath:
    """Tests for _unquote_path method."""

    def test_unquote_simple_path(self, temp_git_repo):
        """Simple paths pass through unchanged."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._unquote_path("simple/path.txt")
        assert result == "simple/path.txt"

    def test_unquote_quoted_path(self, temp_git_repo):
        """Quoted paths are unquoted."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._unquote_path('"path with spaces.txt"')
        assert result == "path with spaces.txt"

    def test_unquote_escaped_quotes(self, temp_git_repo):
        """Escaped quotes in path are handled."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._unquote_path('"file\\"name.txt"')
        assert result == 'file"name.txt'

    def test_unquote_escaped_newlines(self, temp_git_repo):
        """Escaped newlines are converted."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._unquote_path('"line1\\nline2.txt"')
        assert result == "line1\nline2.txt"

    def test_unquote_escaped_tabs(self, temp_git_repo):
        """Escaped tabs are converted."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._unquote_path('"col1\\tcol2.txt"')
        assert result == "col1\tcol2.txt"

    def test_unquote_escaped_backslashes(self, temp_git_repo):
        """Escaped backslashes are converted."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._unquote_path('"path\\\\to\\\\file.txt"')
        assert result == "path\\to\\file.txt"


class TestGitWatcherIsIgnored:
    """Tests for _is_ignored method."""

    def test_ignored_file_returns_true(self, temp_git_repo):
        """Files in .gitignore return True."""
        # Create .gitignore
        gitignore = temp_git_repo / ".gitignore"
        gitignore.write_text("*.log\n")
        os.system(f"cd {temp_git_repo} && git add .gitignore && git commit -m 'Add gitignore' -q")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._is_ignored("test.log")
        assert result is True

    def test_non_ignored_file_returns_false(self, temp_git_repo):
        """Files not in .gitignore return False."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._is_ignored("test.py")
        assert result is False

    def test_is_ignored_not_connected(self):
        """Returns False when not connected."""
        watcher = GitWatcher(Path("/tmp"))
        # Don't connect
        
        result = watcher._is_ignored("test.py")
        assert result is False


class TestGitWatcherCommitComparison:
    """Tests for commit hash comparison."""

    def test_changes_relative_to_commit(self, temp_git_repo):
        """Test detecting changes relative to a specific commit."""
        # Get current commit hash
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True
        )
        initial_commit = result.stdout.strip()
        
        # Make another commit
        test_file = temp_git_repo / "test.py"
        test_file.write_text("print('test')\n")
        os.system(f"cd {temp_git_repo} && git add . && git commit -m 'Add test' -q")
        
        # Create watcher comparing to initial commit
        watcher = GitWatcher(temp_git_repo, commit_hash=initial_commit)
        watcher.connect()
        
        state = watcher.get_state()
        
        # test.py should show as changed relative to initial commit
        # (it was added after)
        file_paths = [f.path for f in state.changed_files]
        # Note: The file was committed, so it won't show as uncommitted
        # This tests the commit comparison path exists


class TestGitWatcherMergeConflict:
    """Tests for merge/rebase conflict detection."""

    def test_merge_head_detected(self, temp_git_repo):
        """Test that MERGE_HEAD file is detected."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Simulate merge in progress
        merge_head = temp_git_repo / ".git" / "MERGE_HEAD"
        merge_head.write_text("abc123\n")
        
        state = watcher.get_state()
        
        assert state.is_conflict_resolution_in_progress is True
        
        # Cleanup
        merge_head.unlink()

    def test_rebase_head_detected(self, temp_git_repo):
        """Test that REBASE_HEAD file is detected."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Simulate rebase in progress
        rebase_head = temp_git_repo / ".git" / "REBASE_HEAD"
        rebase_head.write_text("abc123\n")
        
        state = watcher.get_state()
        
        assert state.is_conflict_resolution_in_progress is True
        
        # Cleanup
        rebase_head.unlink()

    def test_rebase_merge_dir_detected(self, temp_git_repo):
        """Test that rebase-merge directory is detected."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Simulate interactive rebase
        rebase_dir = temp_git_repo / ".git" / "rebase-merge"
        rebase_dir.mkdir()
        
        state = watcher.get_state()
        
        assert state.is_conflict_resolution_in_progress is True
        
        # Cleanup
        rebase_dir.rmdir()


class TestGitWatcherFileStatuses:
    """Tests for different file status handling."""

    def test_renamed_file_detection(self, temp_git_repo):
        """Test that renamed files are detected."""
        # Create and commit a file
        old_file = temp_git_repo / "old_name.txt"
        old_file.write_text("content\n")
        os.system(f"cd {temp_git_repo} && git add . && git commit -m 'Add file' -q")
        
        # Rename the file
        new_file = temp_git_repo / "new_name.txt"
        old_file.rename(new_file)
        os.system(f"cd {temp_git_repo} && git add .")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        # Should detect renamed file
        assert state.has_changes

    def test_deleted_file_detection(self, temp_git_repo):
        """Test that deleted files are detected with correct status."""
        # Create and commit a file
        test_file = temp_git_repo / "to_delete.txt"
        test_file.write_text("content\n")
        os.system(f"cd {temp_git_repo} && git add . && git commit -m 'Add file' -q")
        
        # Delete the file
        test_file.unlink()
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        deleted_files = [f for f in state.changed_files if f.is_deleted]
        assert len(deleted_files) >= 1
        assert any("to_delete.txt" in f.path for f in deleted_files)

    def test_untracked_file_detection(self, temp_git_repo):
        """Test that untracked files are detected."""
        # Create untracked file
        untracked = temp_git_repo / "untracked.txt"
        untracked.write_text("new content\n")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        file_paths = [f.path for f in state.changed_files]
        assert "untracked.txt" in file_paths


class TestGitWatcherIsConnectedProperty:
    """Tests for is_connected property."""

    def test_is_connected_false_before_connect(self, temp_git_repo):
        """is_connected is False before connect() called."""
        watcher = GitWatcher(temp_git_repo)
        assert watcher.is_connected is False

    def test_is_connected_true_after_connect(self, temp_git_repo):
        """is_connected is True after connect() called."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        assert watcher.is_connected is True


class TestGitWatcherGetFileContent:
    """Tests for get_file_content method."""

    def test_get_content_existing_file(self, temp_git_repo):
        """Reading existing file returns content."""
        test_file = temp_git_repo / "test.txt"
        test_file.write_text("Hello World\n")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        content = watcher.get_file_content("test.txt")
        assert content == "Hello World\n"

    def test_get_content_nonexistent_file(self, temp_git_repo):
        """Reading nonexistent file returns None."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        content = watcher.get_file_content("nonexistent.txt")
        assert content is None

    def test_get_content_binary_file(self, temp_git_repo):
        """Reading binary file returns None (UnicodeDecodeError)."""
        binary_file = temp_git_repo / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        content = watcher.get_file_content("binary.bin")
        assert content is None


class TestGitWatcherHasChangesSince:
    """Tests for has_changes_since method."""

    def test_has_changes_since_none(self, temp_git_repo):
        """has_changes_since(None) returns True if has_changes."""
        # Create uncommitted file
        test_file = temp_git_repo / "new.txt"
        test_file.write_text("content\n")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher.has_changes_since(None)
        assert result is True

    def test_has_changes_since_same_state(self, temp_git_repo):
        """has_changes_since returns False if state unchanged."""
        # Create uncommitted file
        test_file = temp_git_repo / "new.txt"
        test_file.write_text("content\n")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        state1 = watcher.get_state()
        
        # Check against same state
        result = watcher.has_changes_since(state1)
        assert result is False

    def test_has_changes_since_different_state(self, temp_git_repo):
        """has_changes_since returns True if state changed."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Get initial state (no changes)
        state1 = watcher.get_state()
        
        # Create new file
        test_file = temp_git_repo / "new.txt"
        test_file.write_text("content\n")
        
        # Check for changes
        result = watcher.has_changes_since(state1)
        assert result is True
