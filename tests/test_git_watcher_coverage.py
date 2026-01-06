"""Coverage-focused tests for git_watcher module."""

import os
import pytest
import tempfile
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from code_scanner.git_watcher import GitWatcher, GitError
from code_scanner.models import GitState, ChangedFile


@pytest.fixture
def temp_git_repo():
    """Create a temporary Git repository."""
    temp_dir = tempfile.mkdtemp()
    
    subprocess.run(["git", "init", "-q"], cwd=temp_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=temp_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_dir, capture_output=True)
    
    readme = Path(temp_dir) / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial", "-q"], cwd=temp_dir, capture_output=True)
    
    yield Path(temp_dir)
    
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestGitWatcherIsIgnored:
    """Tests for _is_ignored method."""

    def test_is_ignored_returns_false_for_tracked(self, temp_git_repo):
        """Test _is_ignored returns False for tracked files."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._is_ignored("README.md")
        assert result is False

    def test_is_ignored_returns_true_for_gitignored(self, temp_git_repo):
        """Test _is_ignored returns True for ignored files."""
        # Create .gitignore
        gitignore = temp_git_repo / ".gitignore"
        gitignore.write_text("*.log\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add gitignore", "-q"], cwd=temp_git_repo, capture_output=True)
        
        # Create ignored file
        log_file = temp_git_repo / "test.log"
        log_file.write_text("log content")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher._is_ignored("test.log")
        assert result is True

    def test_is_ignored_returns_false_when_not_connected(self, temp_git_repo):
        """Test _is_ignored returns False when not connected."""
        watcher = GitWatcher(temp_git_repo)
        # Don't connect
        
        result = watcher._is_ignored("any.txt")
        assert result is False


class TestGitWatcherGetState:
    """Tests for get_state method edge cases."""

    def test_get_state_not_connected_raises(self, temp_git_repo):
        """Test get_state raises error when not connected."""
        watcher = GitWatcher(temp_git_repo)
        
        with pytest.raises(GitError) as exc_info:
            watcher.get_state()
        
        assert "Not connected" in str(exc_info.value)

    def test_get_state_rebase_head_detected(self, temp_git_repo):
        """Test get_state detects REBASE_HEAD."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Create REBASE_HEAD to simulate rebase
        rebase_head = temp_git_repo / ".git" / "REBASE_HEAD"
        rebase_head.write_text("abc123")
        
        state = watcher.get_state()
        
        assert state.is_rebasing
        
        # Cleanup
        rebase_head.unlink()

    def test_get_state_rebase_apply_detected(self, temp_git_repo):
        """Test get_state detects rebase-apply directory."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Create rebase-apply directory
        rebase_dir = temp_git_repo / ".git" / "rebase-apply"
        rebase_dir.mkdir()
        
        state = watcher.get_state()
        
        assert state.is_rebasing
        
        # Cleanup
        rebase_dir.rmdir()

    def test_get_state_handles_detached_head(self, temp_git_repo):
        """Test get_state handles detached HEAD state."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Get current commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True
        )
        commit = result.stdout.strip()
        
        # Detach HEAD
        subprocess.run(["git", "checkout", commit, "-q"], cwd=temp_git_repo, capture_output=True)
        
        state = watcher.get_state()
        
        # Should not crash in detached HEAD state
        assert state is not None


class TestGitWatcherGetChangedFiles:
    """Tests for _get_changed_files method."""

    def test_get_changed_files_handles_renamed(self, temp_git_repo):
        """Test handling of renamed files."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Create and commit a file
        old_file = temp_git_repo / "old_name.txt"
        old_file.write_text("content")
        subprocess.run(["git", "add", "old_name.txt"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add file", "-q"], cwd=temp_git_repo, capture_output=True)
        
        # Rename the file
        new_file = temp_git_repo / "new_name.txt"
        subprocess.run(["git", "mv", "old_name.txt", "new_name.txt"], cwd=temp_git_repo, capture_output=True)
        
        state = watcher.get_state()
        
        # Should detect the rename
        assert state.has_changes

    def test_get_changed_files_skips_directories(self, temp_git_repo):
        """Test that directories (submodules) are skipped."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Create a directory that looks like an untracked item
        subdir = temp_git_repo / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")
        
        state = watcher.get_state()
        
        # Should have the file but not the directory itself
        paths = [f.path for f in state.changed_files]
        assert "subdir" not in paths

    def test_get_changed_files_with_commit_hash(self, temp_git_repo):
        """Test comparing against a specific commit."""
        # Get initial commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True
        )
        initial_commit = result.stdout.strip()
        
        # Make a new commit
        new_file = temp_git_repo / "new.txt"
        new_file.write_text("new content")
        subprocess.run(["git", "add", "new.txt"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add new", "-q"], cwd=temp_git_repo, capture_output=True)
        
        # Create watcher comparing against initial commit
        watcher = GitWatcher(temp_git_repo, commit_hash=initial_commit)
        watcher.connect()
        
        state = watcher.get_state()
        
        # Should detect the new file as changed since initial commit
        paths = [f.path for f in state.changed_files]
        assert "new.txt" in paths


class TestGitWatcherHasChangesSince:
    """Tests for has_changes_since method."""

    def test_has_changes_since_none_returns_has_changes(self, temp_git_repo):
        """Test has_changes_since with None returns current has_changes."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Create uncommitted file
        (temp_git_repo / "new.txt").write_text("content")
        
        result = watcher.has_changes_since(None)
        
        assert result is True

    def test_has_changes_since_same_state_returns_false(self, temp_git_repo):
        """Test has_changes_since with same state returns False."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Create a change
        (temp_git_repo / "new.txt").write_text("content")
        
        state1 = watcher.get_state()
        
        # No new changes
        result = watcher.has_changes_since(state1)
        
        assert result is False

    def test_has_changes_since_new_file_returns_true(self, temp_git_repo):
        """Test has_changes_since detects new files."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        state1 = watcher.get_state()
        
        # Create a new file
        (temp_git_repo / "new.txt").write_text("content")
        
        result = watcher.has_changes_since(state1)
        
        assert result is True


class TestGitWatcherConnect:
    """Tests for connect method."""

    def test_connect_valid_repo(self, temp_git_repo):
        """Test connecting to valid repository."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()

    def test_connect_invalid_path_raises(self):
        """Test connecting to non-repo raises error."""
        temp_dir = tempfile.mkdtemp()
        
        try:
            watcher = GitWatcher(Path(temp_dir))
            
            with pytest.raises(GitError) as exc_info:
                watcher.connect()
            
            assert "Not a Git repository" in str(exc_info.value)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_connect_with_valid_commit_hash(self, temp_git_repo):
        """Test connecting with valid commit hash."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True
        )
        commit = result.stdout.strip()
        
        watcher = GitWatcher(temp_git_repo, commit_hash=commit)
        watcher.connect()

    def test_connect_with_invalid_commit_hash_raises(self, temp_git_repo):
        """Test connecting with invalid commit hash raises error."""
        watcher = GitWatcher(temp_git_repo, commit_hash="invalid123456")
        
        with pytest.raises(GitError) as exc_info:
            watcher.connect()
        
        assert "Invalid commit hash" in str(exc_info.value)


class TestGitWatcherIsIgnoredNoRepo:
    """Tests for _is_ignored when not connected."""

    def test_is_ignored_returns_false_when_not_connected(self, temp_git_repo):
        """Test _is_ignored returns False when repo is None."""
        watcher = GitWatcher(temp_git_repo)
        # Don't call connect(), so _repo is None
        
        result = watcher._is_ignored("anyfile.txt")
        assert result is False


class TestHasChangesSinceEdgeCases:
    """Additional tests for has_changes_since method."""

    def test_has_changes_since_identical_states(self, temp_git_repo):
        """Test has_changes_since returns False for identical states."""
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        result = watcher.has_changes_since(state)
        assert result is False

    def test_has_changes_since_none_with_changes(self, temp_git_repo):
        """Test has_changes_since with None and changes present."""
        # Create a new untracked file
        new_file = temp_git_repo / "new_file.txt"
        new_file.write_text("content")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        result = watcher.has_changes_since(None)
        assert result is True

    def test_has_changes_since_oserror_on_stat(self, temp_git_repo):
        """Test has_changes_since returns True when file stat fails during mtime check."""
        from unittest.mock import patch, MagicMock
        
        # Create a file
        new_file = temp_git_repo / "test_file.txt"
        new_file.write_text("content")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Get state with the file (has mtime in content)
        state = watcher.get_state()
        assert len(state.changed_files) > 0
        
        # Create a fake current_state that will be returned by get_state 
        # but has a file where stat will fail
        fake_changed_file = ChangedFile(
            path="test_file.txt",
            status="unstaged", 
            content=str(new_file.stat().st_mtime)
        )
        fake_state = GitState(changed_files=[fake_changed_file])
        
        # Delete the file so stat will fail during mtime check
        new_file.unlink()
        
        with patch.object(watcher, 'get_state', return_value=fake_state):
            # has_changes_since should return True due to OSError when trying to stat
            result = watcher.has_changes_since(state)
        
        assert result is True

    def test_has_changes_since_deleted_file_skipped(self, temp_git_repo):
        """Test has_changes_since skips deleted files in mtime check."""
        # Create and commit a file
        test_file = temp_git_repo / "to_delete.txt"
        test_file.write_text("content")
        subprocess.run(["git", "add", "to_delete.txt"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add file", "-q"], cwd=temp_git_repo, capture_output=True)
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Delete the file and stage the deletion
        subprocess.run(["git", "rm", "to_delete.txt"], cwd=temp_git_repo, capture_output=True)
        
        state1 = watcher.get_state()
        
        # Should have a deleted file
        deleted_files = [f for f in state1.changed_files if f.is_deleted]
        assert len(deleted_files) >= 1
        
        # has_changes_since should work without errors
        result = watcher.has_changes_since(state1)
        assert result is False

    def test_has_changes_since_invalid_mtime_content(self, temp_git_repo):
        """Test has_changes_since handles invalid mtime in content field."""
        # Create a file
        new_file = temp_git_repo / "test_file.txt"
        new_file.write_text("content")
        
        watcher = GitWatcher(temp_git_repo)
        watcher.connect()
        
        # Get initial state
        state = watcher.get_state()
        
        # Manually set invalid mtime content
        if state.changed_files:
            state.changed_files[0] = ChangedFile(
                path=state.changed_files[0].path, 
                status="unstaged", 
                content="not_a_number"
            )
        
        # Should not crash and return False (invalid mtime treated as no change)
        result = watcher.has_changes_since(state)
        assert result is False
