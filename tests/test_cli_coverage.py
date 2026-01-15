"""Coverage-focused tests for CLI module - targeting uncovered lines."""

import os
import pytest
import signal
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from code_scanner.cli import Application, LockFileError, parse_args, main
from code_scanner.config import Config, ConfigError, LLMConfig, CheckGroup
from code_scanner.git_watcher import GitError
from code_scanner.lmstudio_client import LLMClientError


@pytest.fixture
def temp_git_repo():
    """Create a temporary Git repository."""
    import shutil
    temp_dir = tempfile.mkdtemp()
    
    os.system(f"cd {temp_dir} && git init -q")
    os.system(f"cd {temp_dir} && git config user.email 'test@test.com'")
    os.system(f"cd {temp_dir} && git config user.name 'Test'")
    
    readme = Path(temp_dir) / "README.md"
    readme.write_text("# Test\n")
    os.system(f"cd {temp_dir} && git add . && git commit -m 'Initial' -q")
    
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


class TestApplicationSetup:
    """Tests for Application _setup method."""

    def test_setup_acquires_lock(self, mock_config):
        """Setup acquires the lock file."""
        app = Application(mock_config)
        
        mock_llm = MagicMock()
        mock_llm.connect = MagicMock()
        mock_llm.backend_name = "LM Studio"
        
        with patch.object(app, '_backup_existing_output'), \
             patch('code_scanner.cli.setup_logging'), \
             patch('code_scanner.cli.GitWatcher') as MockGitWatcher, \
             patch('code_scanner.cli.create_llm_client', return_value=mock_llm), \
             patch('code_scanner.cli.IssueTracker'), \
             patch('code_scanner.cli.OutputGenerator'), \
             patch('code_scanner.cli.CtagsIndex'), \
             patch('code_scanner.cli.Scanner'):
            
            MockGitWatcher.return_value.connect = MagicMock()
            
            app._setup()
            
            assert app._lock_acquired
            assert mock_config.lock_path.exists()
        
        # Cleanup
        app._release_lock()

    def test_setup_initializes_git_watcher(self, mock_config):
        """Setup initializes GitWatcher correctly."""
        app = Application(mock_config)
        
        mock_llm = MagicMock()
        mock_llm.connect = MagicMock()
        mock_llm.backend_name = "LM Studio"
        
        with patch.object(app, '_acquire_lock'), \
             patch.object(app, '_backup_existing_output'), \
             patch('code_scanner.cli.setup_logging'), \
             patch('code_scanner.cli.FileFilter') as MockFileFilter, \
             patch('code_scanner.cli.GitWatcher') as MockGitWatcher, \
             patch('code_scanner.cli.create_llm_client', return_value=mock_llm), \
             patch('code_scanner.cli.IssueTracker'), \
             patch('code_scanner.cli.OutputGenerator'), \
             patch('code_scanner.cli.CtagsIndex'), \
             patch('code_scanner.cli.Scanner'):
            
            app._setup()
            
            # FileFilter should be created with scanner files and ignore patterns
            MockFileFilter.assert_called_once()
            
            # GitWatcher should include excluded_files and file_filter
            MockGitWatcher.assert_called_once_with(
                mock_config.target_directory,
                mock_config.commit_hash,
                excluded_files={
                    mock_config.output_file,
                    f"{mock_config.output_file}.bak",
                    mock_config.log_file,
                },
                file_filter=MockFileFilter.return_value,
            )
            MockGitWatcher.return_value.connect.assert_called_once()

    def test_setup_initializes_llm_client(self, mock_config):
        """Setup initializes LLMClient correctly."""
        app = Application(mock_config)
        
        mock_llm = MagicMock()
        mock_llm.connect = MagicMock()
        mock_llm.backend_name = "LM Studio"
        
        with patch.object(app, '_acquire_lock'), \
             patch.object(app, '_backup_existing_output'), \
             patch('code_scanner.cli.setup_logging'), \
             patch('code_scanner.cli.GitWatcher') as MockGitWatcher, \
             patch('code_scanner.cli.create_llm_client', return_value=mock_llm) as mock_factory, \
             patch('code_scanner.cli.IssueTracker'), \
             patch('code_scanner.cli.OutputGenerator'), \
             patch('code_scanner.cli.CtagsIndex'), \
             patch('code_scanner.cli.Scanner'):
            
            MockGitWatcher.return_value.connect = MagicMock()
            
            app._setup()
            
            mock_factory.assert_called_once_with(mock_config)
            mock_llm.connect.assert_called_once()

    def test_setup_sets_context_limit_from_config(self, mock_config):
        """Setup sets context limit from config (now required)."""
        app = Application(mock_config)
        
        mock_llm = MagicMock()
        mock_llm.connect = MagicMock()
        mock_llm.backend_name = "LM Studio"
        mock_config.llm.context_limit = 16384
        
        with patch.object(app, '_acquire_lock'), \
             patch.object(app, '_backup_existing_output'), \
             patch('code_scanner.cli.setup_logging'), \
             patch('code_scanner.cli.GitWatcher') as MockGitWatcher, \
             patch('code_scanner.cli.create_llm_client', return_value=mock_llm), \
             patch('code_scanner.cli.IssueTracker'), \
             patch('code_scanner.cli.OutputGenerator'), \
             patch('code_scanner.cli.CtagsIndex'), \
             patch('code_scanner.cli.Scanner'):
            
            MockGitWatcher.return_value.connect = MagicMock()
            
            app._setup()
            
            mock_llm.set_context_limit.assert_called_once_with(16384)

    def test_setup_creates_initial_output(self, mock_config):
        """Setup creates initial output file."""
        app = Application(mock_config)
        
        mock_output = MagicMock()
        mock_llm = MagicMock()
        mock_llm.connect = MagicMock()
        mock_llm.backend_name = "LM Studio"
        
        with patch.object(app, '_acquire_lock'), \
             patch.object(app, '_backup_existing_output'), \
             patch('code_scanner.cli.setup_logging'), \
             patch('code_scanner.cli.GitWatcher') as MockGitWatcher, \
             patch('code_scanner.cli.create_llm_client', return_value=mock_llm), \
             patch('code_scanner.cli.IssueTracker'), \
             patch('code_scanner.cli.OutputGenerator') as MockOutputGen, \
             patch('code_scanner.cli.CtagsIndex'), \
             patch('code_scanner.cli.Scanner'):
            
            MockGitWatcher.return_value.connect = MagicMock()
            MockOutputGen.return_value = mock_output
            
            app._setup()
            
            mock_output.write.assert_called_once()


class TestApplicationMainLoop:
    """Tests for Application _run_main_loop method."""

    def test_run_main_loop_sets_signal_handlers(self, mock_config):
        """Main loop sets up signal handlers."""
        app = Application(mock_config)
        app.scanner = MagicMock()
        
        def stop_after_brief_run(*args, **kwargs):
            time.sleep(0.1)
            app._stop_event.set()
        
        with patch('signal.signal') as mock_signal, \
             patch.object(threading.Thread, 'start', side_effect=stop_after_brief_run):
            app._run_main_loop()
        
        # Should register SIGINT and SIGTERM handlers
        assert mock_signal.call_count >= 2

    def test_run_main_loop_starts_git_thread(self, mock_config):
        """Main loop starts git watcher thread."""
        app = Application(mock_config)
        app.scanner = MagicMock()
        
        app._stop_event.set()  # Exit immediately
        
        with patch('signal.signal'):
            app._run_main_loop()
        
        # Git thread should be created
        assert app._git_thread is not None

    def test_run_main_loop_starts_scanner(self, mock_config):
        """Main loop starts scanner."""
        app = Application(mock_config)
        app.scanner = MagicMock()
        
        app._stop_event.set()  # Exit immediately
        
        with patch('signal.signal'):
            app._run_main_loop()
        
        app.scanner.start.assert_called_once()


class TestApplicationGitWatchLoop:
    """Tests for Application _git_watch_loop method."""

    def test_git_watch_loop_exits_on_stop(self, mock_config):
        """Git watch loop exits when stop event is set."""
        app = Application(mock_config)
        app.git_watcher = MagicMock()
        app.scanner = MagicMock()
        app._stop_event.set()
        
        # Should exit immediately
        app._git_watch_loop()

    def test_git_watch_loop_signals_restart_on_changes(self, mock_config):
        """Git watch loop signals scanner restart when changes detected."""
        app = Application(mock_config)
        app.git_watcher = MagicMock()
        app.scanner = MagicMock()
        
        call_count = [0]
        def has_changes_side_effect(last_state):
            call_count[0] += 1
            if call_count[0] == 1:
                return True
            app._stop_event.set()
            return False
        
        app.git_watcher.has_changes_since.side_effect = has_changes_side_effect
        app.git_watcher.get_state.return_value = MagicMock()
        
        app._git_watch_loop()
        
        app.scanner.signal_refresh.assert_called_once()

    def test_git_watch_loop_handles_exceptions(self, mock_config):
        """Git watch loop handles exceptions and continues."""
        app = Application(mock_config)
        app.git_watcher = MagicMock()
        app.scanner = MagicMock()
        
        call_count = [0]
        def has_changes_side_effect(last_state):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Test error")
            app._stop_event.set()
            return False
        
        app.git_watcher.has_changes_since.side_effect = has_changes_side_effect
        
        # Should not raise
        app._git_watch_loop()
        assert call_count[0] >= 1


class TestApplicationBackupOutput:
    """Tests for Application _backup_existing_output method."""

    def test_backup_no_existing_file(self, mock_config):
        """Backup does nothing when no output file exists."""
        app = Application(mock_config)
        
        # Ensure output doesn't exist
        if mock_config.output_path.exists():
            mock_config.output_path.unlink()
        
        app._backup_existing_output()  # Should not raise

    def test_backup_creates_backup_file(self, mock_config):
        """Backup creates .bak file with content."""
        app = Application(mock_config)
        mock_config.output_path.write_text("# Original content\n")
        
        app._backup_existing_output()
        
        backup_path = mock_config.output_path.parent / f"{mock_config.output_path.name}.bak"
        assert backup_path.exists()
        backup_content = backup_path.read_text()
        assert "# Original content" in backup_content
        assert "Backup created:" in backup_content
        assert not mock_config.output_path.exists()  # Original should be deleted
        
        # Cleanup
        backup_path.unlink()

    def test_backup_appends_to_existing_backup(self, mock_config):
        """Backup appends to existing .bak file."""
        app = Application(mock_config)
        backup_path = mock_config.output_path.parent / f"{mock_config.output_path.name}.bak"
        
        # Create existing backup
        backup_path.write_text("# Previous backup\n")
        
        # Create output file
        mock_config.output_path.write_text("# Current content\n")
        
        app._backup_existing_output()
        
        backup_content = backup_path.read_text()
        assert "# Previous backup" in backup_content
        assert "# Current content" in backup_content
        
        # Cleanup
        backup_path.unlink()

    def test_backup_includes_timestamp(self, mock_config):
        """Backup includes timestamp in separator."""
        app = Application(mock_config)
        mock_config.output_path.write_text("# Test\n")
        
        app._backup_existing_output()
        
        backup_path = mock_config.output_path.parent / f"{mock_config.output_path.name}.bak"
        backup_content = backup_path.read_text()
        assert "Backup created:" in backup_content
        assert "=" * 60 in backup_content
        
        # Cleanup
        backup_path.unlink()


class TestApplicationProcessCheck:
    """Tests for Application _is_process_running method."""

    def test_current_process_is_running(self, mock_config):
        """Current process PID is reported as running."""
        import os
        app = Application(mock_config)
        assert app._is_process_running(os.getpid()) is True

    def test_invalid_pid_is_not_running(self, mock_config):
        """Invalid PID is reported as not running."""
        app = Application(mock_config)
        assert app._is_process_running(999999999) is False


class TestApplicationRun:
    """Tests for Application run method."""

    def test_run_returns_0_on_success(self, mock_config):
        """Run returns 0 on successful execution."""
        app = Application(mock_config)
        
        with patch.object(app, '_setup'), \
             patch.object(app, '_run_main_loop'), \
             patch.object(app, '_cleanup'):
            result = app.run()
        
        assert result == 0

    def test_run_returns_1_on_config_error(self, mock_config):
        """Run returns 1 on ConfigError."""
        app = Application(mock_config)
        
        with patch.object(app, '_setup', side_effect=ConfigError("Test")), \
             patch.object(app, '_cleanup'):
            result = app.run()
        
        assert result == 1

    def test_run_returns_1_on_git_error(self, mock_config):
        """Run returns 1 on GitError."""
        app = Application(mock_config)
        
        with patch.object(app, '_setup', side_effect=GitError("Test")), \
             patch.object(app, '_cleanup'):
            result = app.run()
        
        assert result == 1

    def test_run_returns_1_on_llm_error(self, mock_config):
        """Run returns 1 on LLMClientError."""
        app = Application(mock_config)
        
        with patch.object(app, '_setup', side_effect=LLMClientError("Test")), \
             patch.object(app, '_cleanup'):
            result = app.run()
        
        assert result == 1

    def test_run_returns_130_on_keyboard_interrupt(self, mock_config):
        """Run returns 130 on KeyboardInterrupt."""
        app = Application(mock_config)
        
        with patch.object(app, '_setup', side_effect=KeyboardInterrupt), \
             patch.object(app, '_cleanup'):
            result = app.run()
        
        assert result == 130

    def test_run_returns_1_on_unexpected_error(self, mock_config):
        """Run returns 1 on unexpected exceptions."""
        app = Application(mock_config)
        
        with patch.object(app, '_setup', side_effect=ValueError("Unexpected")), \
             patch.object(app, '_cleanup'):
            result = app.run()
        
        assert result == 1

    def test_run_always_calls_cleanup(self, mock_config):
        """Run always calls cleanup even on error."""
        app = Application(mock_config)
        
        with patch.object(app, '_setup', side_effect=RuntimeError("Error")), \
             patch.object(app, '_cleanup') as mock_cleanup:
            app.run()
        
        mock_cleanup.assert_called_once()


class TestApplicationSignalHandler:
    """Tests for Application _signal_handler method."""

    def test_signal_handler_sets_stop_event(self, mock_config):
        """Signal handler sets stop event."""
        app = Application(mock_config)
        
        app._signal_handler(signal.SIGINT, None)
        
        assert app._stop_event.is_set()

    def test_signal_handler_handles_sigterm(self, mock_config):
        """Signal handler works with SIGTERM."""
        app = Application(mock_config)
        
        app._signal_handler(signal.SIGTERM, None)
        
        assert app._stop_event.is_set()


class TestApplicationCleanup:
    """Tests for Application _cleanup method."""

    def test_cleanup_sets_stop_event(self, mock_config):
        """Cleanup sets stop event."""
        app = Application(mock_config)
        
        app._cleanup()
        
        assert app._stop_event.is_set()

    def test_cleanup_stops_scanner(self, mock_config):
        """Cleanup stops scanner."""
        app = Application(mock_config)
        app.scanner = MagicMock()
        
        app._cleanup()
        
        app.scanner.stop.assert_called_once()

    def test_cleanup_joins_git_thread(self, mock_config):
        """Cleanup joins git thread."""
        app = Application(mock_config)
        app._git_thread = MagicMock()
        app._git_thread.is_alive.return_value = True
        
        app._cleanup()
        
        app._git_thread.join.assert_called_once_with(timeout=2)

    def test_cleanup_releases_lock(self, mock_config):
        """Cleanup releases lock file."""
        app = Application(mock_config)
        
        # Acquire lock first
        mock_config.lock_path.write_text("1234\n")
        app._lock_acquired = True
        
        app._cleanup()
        
        assert not mock_config.lock_path.exists()

    def test_cleanup_handles_no_scanner(self, mock_config):
        """Cleanup handles None scanner."""
        app = Application(mock_config)
        app.scanner = None
        
        app._cleanup()  # Should not raise


class TestApplicationLockFile:
    """Tests for Application lock file handling."""

    def test_acquire_lock_creates_file(self, mock_config):
        """Acquire lock creates lock file."""
        app = Application(mock_config)
        
        if mock_config.lock_path.exists():
            mock_config.lock_path.unlink()
        
        app._acquire_lock()
        
        assert mock_config.lock_path.exists()
        assert app._lock_acquired
        
        app._release_lock()

    def test_acquire_lock_writes_pid(self, mock_config):
        """Acquire lock writes PID to file."""
        app = Application(mock_config)
        
        if mock_config.lock_path.exists():
            mock_config.lock_path.unlink()
        
        app._acquire_lock()
        
        content = mock_config.lock_path.read_text()
        assert str(os.getpid()) in content
        
        app._release_lock()

    def test_acquire_lock_fails_if_process_running(self, mock_config):
        """Acquire lock fails if lock file exists and process is running."""
        import os
        app = Application(mock_config)
        # Use current PID to simulate a running process
        mock_config.lock_path.write_text(f"{os.getpid()}\n")
        
        with pytest.raises(LockFileError) as exc_info:
            app._acquire_lock()
        
        assert "Another code-scanner instance is already running" in str(exc_info.value)
        mock_config.lock_path.unlink()

    def test_acquire_lock_removes_stale_lock(self, mock_config):
        """Acquire lock removes stale lock if PID is not running."""
        import os
        app = Application(mock_config)
        # Use a PID that's definitely not running
        mock_config.lock_path.write_text("999999999\n")
        
        app._acquire_lock()  # Should succeed by removing stale lock
        
        assert app._lock_acquired is True
        content = mock_config.lock_path.read_text()
        assert str(os.getpid()) in content
        
        app._release_lock()

    def test_release_lock_removes_file(self, mock_config):
        """Release lock removes file."""
        app = Application(mock_config)
        
        if mock_config.lock_path.exists():
            mock_config.lock_path.unlink()
        
        app._acquire_lock()
        app._release_lock()
        
        assert not mock_config.lock_path.exists()
        assert not app._lock_acquired

    def test_release_lock_does_nothing_if_not_acquired(self, mock_config):
        """Release lock does nothing if not acquired."""
        app = Application(mock_config)
        mock_config.lock_path.write_text("9999\n")
        
        app._release_lock()
        
        # File should still exist since we didn't acquire it
        assert mock_config.lock_path.exists()
        mock_config.lock_path.unlink()


class TestMainFunction:
    """Tests for main entry point function."""

    def test_main_returns_1_on_config_error(self, temp_git_repo):
        """Main returns 1 on configuration error."""
        fake_config = temp_git_repo / "nonexistent.toml"
        
        with patch('sys.argv', ['code-scanner', str(temp_git_repo), '-c', str(fake_config)]):
            result = main()
        
        assert result == 1

    def test_main_creates_application_and_runs(self, temp_git_repo):
        """Main creates Application and calls run."""
        config_path = temp_git_repo / "config.toml"
        config_path.write_text('''[[checks]]
pattern = "*"
checks = ["Check"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
context_limit = 16384
''')
        
        with patch('sys.argv', ['code-scanner', str(temp_git_repo), '-c', str(config_path)]), \
             patch('code_scanner.cli.Application') as MockApp:
            MockApp.return_value.run.return_value = 0
            
            result = main()
        
        MockApp.assert_called_once()
        MockApp.return_value.run.assert_called_once()
        assert result == 0


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parse_target_only(self):
        """Parse with only target directory."""
        with patch('sys.argv', ['code-scanner', '/tmp/test']):
            args = parse_args()
        
        assert args.target_directory == Path('/tmp/test')
        assert args.config is None
        assert args.commit is None

    def test_parse_with_config_short(self):
        """Parse with short config flag."""
        with patch('sys.argv', ['code-scanner', '/tmp/test', '-c', '/path/config.toml']):
            args = parse_args()
        
        assert args.config == Path('/path/config.toml')

    def test_parse_with_config_long(self):
        """Parse with long config flag."""
        with patch('sys.argv', ['code-scanner', '/tmp/test', '--config', '/path/config.toml']):
            args = parse_args()
        
        assert args.config == Path('/path/config.toml')

    def test_parse_with_commit(self):
        """Parse with commit hash."""
        with patch('sys.argv', ['code-scanner', '/tmp/test', '--commit', 'abc123']):
            args = parse_args()
        
        assert args.commit == 'abc123'

    def test_parse_all_options(self):
        """Parse with all options."""
        with patch('sys.argv', [
            'code-scanner', '/tmp/test',
            '-c', '/config.toml',
            '--commit', 'abc123'
        ]):
            args = parse_args()
        
        assert args.target_directory == Path('/tmp/test')
        assert args.config == Path('/config.toml')
        assert args.commit == 'abc123'
