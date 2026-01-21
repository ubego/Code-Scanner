"""Extended coverage tests for CLI module - targeting uncovered paths."""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from code_scanner.cli import Application, LockFileError, create_llm_client
from code_scanner.config import Config, ConfigError, LLMConfig, CheckGroup


@pytest.fixture
def temp_git_repo():
    """Create a temporary Git repository."""
    import shutil
    import subprocess
    temp_dir = tempfile.mkdtemp()
    
    subprocess.run(['git', 'init', '-q'], cwd=temp_dir, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=temp_dir, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=temp_dir, check=True)
    
    readme = Path(temp_dir) / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(['git', 'add', '.'], cwd=temp_dir, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial', '-q'], cwd=temp_dir, check=True)
    
    yield Path(temp_dir)
    
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_config(temp_git_repo):
    """Create a mock Config object."""
    config = MagicMock(spec=Config)
    config.target_directory = temp_git_repo
    config.output_path = temp_git_repo / "results.md"
    config.log_path = temp_git_repo / "scanner.log"
    config.lock_path = temp_git_repo / ".code_scanner.lock"
    config.config_file = temp_git_repo / "config.toml"
    config.output_file = "results.md"
    config.log_file = "scanner.log"
    config.git_poll_interval = 0.1
    config.llm_retry_interval = 0.1
    config.max_llm_retries = 2
    config.check_groups = [CheckGroup(pattern="*", checks=["Check"])]
    config.llm = LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384)
    config.commit_hash = None
    return config


class TestCreateLLMClientCoverage:
    """Test create_llm_client function edge cases."""

    def test_invalid_backend_raises_config_error(self, mock_config):
        """Test invalid backend configuration raises ConfigError."""
        mock_config.llm.backend = "invalid-backend"
        
        with pytest.raises(ConfigError) as exc_info:
            create_llm_client(mock_config)
        
        error_msg = str(exc_info.value)
        assert "Invalid backend" in error_msg
        assert "invalid-backend" in error_msg
        assert "lm-studio" in error_msg
        assert "ollama" in error_msg

    def test_lm_studio_backend(self, mock_config):
        """Test LM Studio backend client creation."""
        mock_config.llm.backend = "lm-studio"
        
        with patch('code_scanner.cli.LMStudioClient') as MockClient:
            MockClient.return_value = MagicMock()
            client = create_llm_client(mock_config)
            MockClient.assert_called_once_with(mock_config.llm)

    def test_ollama_backend(self, mock_config):
        """Test Ollama backend client creation."""
        mock_config.llm.backend = "ollama"
        mock_config.llm.model = "qwen3:4b"
        
        with patch('code_scanner.cli.OllamaClient') as MockClient:
            MockClient.return_value = MagicMock()
            client = create_llm_client(mock_config)
            MockClient.assert_called_once_with(mock_config.llm)


class TestLockFileCoverage:
    """Test lock file handling edge cases."""

    def test_invalid_lock_file_contents(self, mock_config):
        """Test handling of corrupt lock file with non-numeric content."""
        # Write invalid content to lock file
        mock_config.lock_path.write_text("not-a-pid")
        
        app = Application(mock_config)
        
        # Should remove invalid lock and acquire new one
        app._acquire_lock()
        
        assert app._lock_acquired
        # Lock file should now contain valid PID
        assert mock_config.lock_path.read_text().strip().isdigit()
        
        app._release_lock()

    def test_stale_lock_from_dead_process(self, mock_config):
        """Test removal of stale lock from terminated process."""
        # Write a PID that almost certainly doesn't exist
        mock_config.lock_path.write_text("999999999")
        
        app = Application(mock_config)
        app._acquire_lock()
        
        assert app._lock_acquired
        
        app._release_lock()

    def test_active_lock_from_running_process(self, mock_config):
        """Test that active lock from running process raises error."""
        # Write current process PID (simulating another instance)
        mock_config.lock_path.write_text(f"{os.getpid()}")
        
        app = Application(mock_config)
        
        with pytest.raises(LockFileError) as exc_info:
            app._acquire_lock()
        
        assert "already running" in str(exc_info.value).lower()

    def test_lock_file_empty(self, mock_config):
        """Test handling of empty lock file."""
        mock_config.lock_path.write_text("")
        
        app = Application(mock_config)
        
        # Should handle empty file (ValueError on int conversion)
        app._acquire_lock()
        
        assert app._lock_acquired
        
        app._release_lock()


class TestBackupExistingOutputCoverage:
    """Test _backup_existing_output edge cases."""

    def test_backup_io_error(self, mock_config, monkeypatch):
        """Test handling of backup failure."""
        # Create existing output file
        mock_config.output_path.write_text("existing content")
        
        app = Application(mock_config)
        
        # Make backup path unwritable
        backup_path = mock_config.output_path.parent / f"{mock_config.output_path.name}.bak"
        
        original_open = open
        def failing_open(path, mode='r', **kwargs):
            if str(path) == str(backup_path) and 'a' in mode:
                raise IOError("Disk full")
            return original_open(path, mode, **kwargs)
        
        # Should handle the error gracefully
        with patch('builtins.open', failing_open):
            app._backup_existing_output()  # Should not raise

    def test_backup_no_existing_output(self, mock_config):
        """Test backup when no existing output file."""
        app = Application(mock_config)
        
        # Ensure output doesn't exist
        if mock_config.output_path.exists():
            mock_config.output_path.unlink()
        
        # Should not raise
        app._backup_existing_output()


class TestCleanupCoverage:
    """Test _cleanup method edge cases."""

    def test_cleanup_before_logging_setup(self, mock_config):
        """Test cleanup handles logging not being set up."""
        app = Application(mock_config)
        
        # Simulate state before logging is configured
        app.scanner = None
        app._lock_acquired = False
        
        # Should not raise even if logger might fail
        app._cleanup()

    def test_cleanup_with_scanner(self, mock_config):
        """Test cleanup properly stops scanner."""
        app = Application(mock_config)
        
        mock_scanner = MagicMock()
        app.scanner = mock_scanner
        app._lock_acquired = False
        
        app._cleanup()
        
        mock_scanner.stop.assert_called_once()


class TestIsProcessRunning:
    """Test _is_process_running method."""

    def test_current_process_is_running(self, mock_config):
        """Test that current process is detected as running."""
        app = Application(mock_config)
        
        assert app._is_process_running(os.getpid()) is True

    def test_invalid_pid_not_running(self, mock_config):
        """Test that invalid PID is not running."""
        app = Application(mock_config)
        
        # Very high PID that shouldn't exist
        assert app._is_process_running(999999999) is False


class TestSystemExitHandling:
    """Test Application.run handles SystemExit properly."""

    def test_run_with_system_exit(self, mock_config, monkeypatch):
        """Test Application.run handles SystemExit."""
        app = Application(mock_config)
        
        def setup_that_exits():
            raise SystemExit(1)
        
        monkeypatch.setattr(app, '_setup', setup_that_exits)
        
        with pytest.raises(SystemExit):
            app.run()

    def test_run_with_keyboard_interrupt(self, mock_config, monkeypatch):
        """Test Application.run handles KeyboardInterrupt."""
        app = Application(mock_config)
        
        def setup_that_interrupts():
            raise KeyboardInterrupt()
        
        monkeypatch.setattr(app, '_setup', setup_that_interrupts)
        
        result = app.run()
        
        assert result == 130  # Standard exit code for SIGINT
