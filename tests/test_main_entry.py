"""Tests for __main__.py module execution."""

import subprocess
import sys
from pathlib import Path

import pytest


class TestMainModuleExecution:
    """Test running code_scanner as a module."""

    def test_main_module_help(self):
        """Test running code_scanner as a module with --help."""
        result = subprocess.run(
            [sys.executable, "-m", "code_scanner", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "code-scanner" in result.stdout.lower()

    def test_main_module_version(self):
        """Test running code_scanner as a module with --version."""
        result = subprocess.run(
            [sys.executable, "-m", "code_scanner", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Version flag should succeed
        assert result.returncode == 0
        # Should output version info
        assert "code" in result.stdout.lower() or result.stdout.strip()

    def test_main_module_missing_target_directory(self):
        """Test module execution without required target_directory."""
        result = subprocess.run(
            [sys.executable, "-m", "code_scanner"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should fail due to missing required argument
        assert result.returncode != 0
        assert "error" in result.stderr.lower() or "required" in result.stderr.lower()

    def test_main_module_invalid_directory(self, tmp_path):
        """Test module execution with non-existent directory."""
        non_existent = tmp_path / "does_not_exist"
        result = subprocess.run(
            [sys.executable, "-m", "code_scanner", str(non_existent)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should fail due to invalid directory
        assert result.returncode != 0

    def test_main_module_not_git_repo(self, tmp_path):
        """Test module execution on directory that is not a git repo."""
        # Create a directory that is not a git repo
        not_git = tmp_path / "not_git"
        not_git.mkdir()
        (not_git / "test.py").write_text("print('hello')")
        
        result = subprocess.run(
            [sys.executable, "-m", "code_scanner", str(not_git)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should fail because directory is not a git repository
        # (or may fail due to lock file if another instance is running)
        assert result.returncode != 0
