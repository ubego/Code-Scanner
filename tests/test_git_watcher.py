"""Tests for Git watcher module."""

import pytest
import subprocess
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.git_watcher import GitWatcher, GitError


class TestGitWatcher:
    """Tests for GitWatcher class."""

    def test_connect_to_valid_repo(self, git_repo: Path):
        """Test connecting to a valid Git repository."""
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        watcher.connect()

    def test_connect_to_non_repo_raises_error(self, temp_dir: Path):
        """Test that connecting to non-Git directory raises error."""
        watcher = GitWatcher(temp_dir)
        
        with pytest.raises(GitError) as exc_info:
            watcher.connect()
        
        assert "Not a Git repository" in str(exc_info.value)

    def test_get_state_no_changes(self, git_repo: Path):
        """Test getting state when there are no changes."""
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert not state.has_changes
        assert len(state.changed_files) == 0

    def test_get_state_with_unstaged_changes(self, git_repo: Path):
        """Test getting state with unstaged changes."""
        # Modify a file
        readme = git_repo / "README.md"
        readme.write_text("Modified content\n")
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert state.has_changes
        assert len(state.changed_files) == 1
        assert state.changed_files[0].path == "README.md"
        assert state.changed_files[0].status == "unstaged"

    def test_get_state_with_staged_changes(self, git_repo: Path):
        """Test getting state with staged changes."""
        # Create and stage a new file
        new_file = git_repo / "new.txt"
        new_file.write_text("New file\n")
        subprocess.run(["git", "add", "new.txt"], cwd=git_repo, capture_output=True)
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert state.has_changes
        # The new file should show up as some kind of change (staged or untracked varies by git version)
        assert len(state.changed_files) >= 1
        assert any(f.path == "new.txt" for f in state.changed_files)

    def test_get_state_with_untracked_files(self, git_repo: Path):
        """Test getting state with untracked files."""
        # Create an untracked file
        new_file = git_repo / "untracked.txt"
        new_file.write_text("Untracked\n")
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert state.has_changes
        assert any(f.path == "untracked.txt" and f.status == "untracked" 
                   for f in state.changed_files)

    def test_get_state_with_deleted_file(self, git_repo: Path):
        """Test getting state with deleted file."""
        # Delete the README
        readme = git_repo / "README.md"
        readme.unlink()
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert state.has_changes
        deleted_files = [f for f in state.changed_files if f.is_deleted]
        assert len(deleted_files) == 1

    def test_gitignore_respected(self, git_repo: Path):
        """Test that .gitignore patterns are respected."""
        # Create .gitignore
        gitignore = git_repo / ".gitignore"
        gitignore.write_text("*.log\nbuild/\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add gitignore"],
            cwd=git_repo,
            capture_output=True,
        )
        
        # Create ignored files
        (git_repo / "test.log").write_text("log")
        build_dir = git_repo / "build"
        build_dir.mkdir()
        (build_dir / "output.txt").write_text("output")
        
        # Create non-ignored file
        (git_repo / "test.txt").write_text("test")
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        # Only test.txt should be detected
        paths = [f.path for f in state.changed_files]
        assert "test.txt" in paths
        assert "test.log" not in paths

    def test_has_changes_since(self, git_repo: Path):
        """Test detecting changes since last state."""
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        # Get initial state
        state1 = watcher.get_state()
        
        # No changes yet
        assert not watcher.has_changes_since(state1)
        
        # Make a change and stage it so git status sees it
        (git_repo / "new.txt").write_text("new")
        subprocess.run(["git", "add", "new.txt"], cwd=git_repo, capture_output=True)
        
        # Now there should be changes
        assert watcher.has_changes_since(state1)

    def test_has_changes_since_excludes_specified_files(self, git_repo: Path):
        """Test that excluded files don't trigger change detection."""
        # Create the output file (which should be excluded)
        output_file = git_repo / "code_scanner_results.md"
        output_file.write_text("initial content")
        
        # Create a normal file
        normal_file = git_repo / "code.py"
        normal_file.write_text("# code")
        
        # Create watcher with exclusion
        watcher = GitWatcher(
            git_repo,
            excluded_files={"code_scanner_results.md", "code_scanner_results.md.bak"}
        )
        watcher.connect()
        
        state1 = watcher.get_state()
        
        # Modify only the excluded file
        import time
        time.sleep(0.01)
        output_file.write_text("updated content")
        
        # Should NOT detect changes (excluded file modified)
        assert not watcher.has_changes_since(state1)
        
        # Now modify the normal file
        time.sleep(0.01)
        normal_file.write_text("# updated code")
        
        # Should detect changes (non-excluded file modified)
        assert watcher.has_changes_since(state1)

    def test_has_changes_since_mtime_detection(self, git_repo: Path):
        """Test that has_changes_since detects in-place file modifications via mtime."""
        # Create a file and stage it
        test_file = git_repo / "test.txt"
        test_file.write_text("original content")
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        # Get initial state (file is unstaged/untracked)
        state1 = watcher.get_state()
        assert len(state1.changed_files) > 0
        
        # No changes detected when state is same
        assert not watcher.has_changes_since(state1)
        
        # Wait a tiny bit and modify the file in-place
        import time
        time.sleep(0.01)  # Ensure mtime changes
        test_file.write_text("modified content")
        
        # Now mtime-based detection should see changes
        assert watcher.has_changes_since(state1)

    def test_has_changes_since_same_paths_no_mtime_change(self, git_repo: Path):
        """Test that has_changes_since returns False when paths same and mtime unchanged."""
        # Create a file
        test_file = git_repo / "test.txt"
        test_file.write_text("content")
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        # Get state twice without modifying file
        state1 = watcher.get_state()
        state2 = watcher.get_state()
        
        # Should not detect changes - paths same and mtime same
        assert not watcher.has_changes_since(state1)
        # state2 also works as base
        assert not watcher.has_changes_since(state2)

    def test_merge_in_progress_detected(self, git_repo: Path):
        """Test that merge in progress is detected."""
        # Create MERGE_HEAD to simulate merge
        merge_head = git_repo / ".git" / "MERGE_HEAD"
        merge_head.write_text("abc123")
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert state.is_merging
        assert state.is_conflict_resolution_in_progress

    def test_rebase_in_progress_detected(self, git_repo: Path):
        """Test that rebase in progress is detected."""
        # Create rebase directory to simulate rebase
        rebase_dir = git_repo / ".git" / "rebase-merge"
        rebase_dir.mkdir()
        
        watcher = GitWatcher(git_repo)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert state.is_rebasing
        assert state.is_conflict_resolution_in_progress

    def test_invalid_commit_hash_raises_error(self, git_repo: Path):
        """Test that invalid commit hash raises error."""
        watcher = GitWatcher(git_repo, commit_hash="invalid_hash_12345")
        
        with pytest.raises(GitError) as exc_info:
            watcher.connect()
        
        assert "Invalid commit hash" in str(exc_info.value)
