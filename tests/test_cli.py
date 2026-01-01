"""Tests for CLI and Application functionality."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from code_scanner.cli import (
    Application,
    LockFileError,
    parse_args,
)
from code_scanner.config import Config
from code_scanner.models import LLMConfig, CheckGroup


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parse_target_directory_only(self):
        """Parse with only target directory."""
        with patch.object(sys, 'argv', ['code-scanner', '/path/to/project']):
            args = parse_args()
            assert args.target_directory == Path('/path/to/project')
            assert args.config is None
            assert args.commit is None

    def test_parse_with_config(self):
        """Parse with config file."""
        with patch.object(sys, 'argv', ['code-scanner', '/project', '-c', '/config.toml']):
            args = parse_args()
            assert args.config == Path('/config.toml')

    def test_parse_with_commit(self):
        """Parse with commit hash."""
        with patch.object(sys, 'argv', ['code-scanner', '/project', '--commit', 'abc123']):
            args = parse_args()
            assert args.commit == 'abc123'

    def test_parse_all_options(self):
        """Parse with all options."""
        with patch.object(sys, 'argv', [
            'code-scanner', '/project',
            '-c', '/config.toml',
            '--commit', 'abc123'
        ]):
            args = parse_args()
            assert args.target_directory == Path('/project')
            assert args.config == Path('/config.toml')
            assert args.commit == 'abc123'


class TestApplicationLockFile:
    """Tests for Application lock file handling."""

    def test_acquire_lock_creates_file(self, tmp_path):
        """Acquire lock creates lock file."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".code_scanner.lock"
        config.output_path = tmp_path / "output.md"
        config.log_path = tmp_path / "log.log"
        config.target_directory = tmp_path
        config.config_file = tmp_path / "config.toml"
        config.check_groups = []
        
        app = Application(config)
        app._acquire_lock()
        
        assert config.lock_path.exists()
        assert app._lock_acquired is True
        
        # Cleanup
        app._release_lock()

    def test_acquire_lock_fails_if_exists(self, tmp_path):
        """Acquire lock fails if lock file exists."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".code_scanner.lock"
        
        # Create existing lock
        config.lock_path.write_text("1234")
        
        app = Application(config)
        
        with pytest.raises(LockFileError, match="Lock file exists"):
            app._acquire_lock()

    def test_release_lock_removes_file(self, tmp_path):
        """Release lock removes lock file."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".code_scanner.lock"
        
        app = Application(config)
        app._lock_acquired = True
        config.lock_path.write_text("1234")
        
        app._release_lock()
        
        assert not config.lock_path.exists()
        assert app._lock_acquired is False

    def test_release_lock_does_nothing_if_not_acquired(self, tmp_path):
        """Release lock does nothing if lock not acquired."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".code_scanner.lock"
        
        # Create file but don't mark as acquired
        config.lock_path.write_text("1234")
        
        app = Application(config)
        app._lock_acquired = False
        
        app._release_lock()
        
        # File should still exist
        assert config.lock_path.exists()


class TestApplicationSignalHandler:
    """Tests for Application signal handling."""

    def test_signal_handler_sets_stop_event(self, tmp_path):
        """Signal handler sets stop event."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".lock"
        
        app = Application(config)
        
        assert not app._stop_event.is_set()
        
        app._signal_handler(2, None)  # SIGINT
        
        assert app._stop_event.is_set()


class TestApplicationCleanup:
    """Tests for Application cleanup."""

    def test_cleanup_stops_scanner(self, tmp_path):
        """Cleanup stops scanner."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".lock"
        
        app = Application(config)
        app.scanner = MagicMock()
        app._lock_acquired = False
        
        app._cleanup()
        
        app.scanner.stop.assert_called_once()

    def test_cleanup_releases_lock(self, tmp_path):
        """Cleanup releases lock."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".lock"
        config.lock_path.write_text("1234")
        
        app = Application(config)
        app._lock_acquired = True
        
        app._cleanup()
        
        assert not config.lock_path.exists()

    def test_cleanup_handles_no_scanner(self, tmp_path):
        """Cleanup handles case when scanner is None."""
        config = MagicMock(spec=Config)
        config.lock_path = tmp_path / ".lock"
        
        app = Application(config)
        app.scanner = None
        app._lock_acquired = False
        
        # Should not raise
        app._cleanup()


class TestLockFileError:
    """Tests for LockFileError exception."""

    def test_lock_file_error_message(self):
        """LockFileError has proper message."""
        error = LockFileError("Lock file exists")
        assert str(error) == "Lock file exists"

    def test_lock_file_error_is_exception(self):
        """LockFileError is an Exception."""
        assert issubclass(LockFileError, Exception)
