"""CLI entry point and main application."""

import argparse
import atexit
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .config import Config, ConfigError, load_config
from .ctags_index import CtagsIndex, CtagsNotFoundError, CtagsError
from .git_watcher import GitWatcher, GitError
from .issue_tracker import IssueTracker
from .base_client import BaseLLMClient, LLMClientError
from .lmstudio_client import LMStudioClient
from .ollama_client import OllamaClient
from .output import OutputGenerator
from .scanner import Scanner
from .utils import setup_logging

logger = logging.getLogger(__name__)


def create_llm_client(config: Config) -> BaseLLMClient:
    """Create the appropriate LLM client based on configuration.

    Args:
        config: Application configuration with LLM settings.

    Returns:
        Configured LLM client instance.

    Raises:
        ConfigError: If backend is invalid.
    """
    backend = config.llm.backend
    
    if backend == "lm-studio":
        return LMStudioClient(config.llm)
    elif backend == "ollama":
        return OllamaClient(config.llm)
    else:
        raise ConfigError(
            f"Invalid backend '{backend}'. "
            f"Supported backends: lm-studio, ollama"
        )


class LockFileError(Exception):
    """Lock file related error."""

    pass


class Application:
    """Main application coordinator."""

    def __init__(self, config: Config):
        """Initialize the application.

        Args:
            config: Application configuration.
        """
        self.config = config
        self.git_watcher: Optional[GitWatcher] = None
        self.llm_client: Optional[BaseLLMClient] = None
        self.issue_tracker: Optional[IssueTracker] = None
        self.output_generator: Optional[OutputGenerator] = None
        self.scanner: Optional[Scanner] = None

        self._git_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock_acquired = False
        self.ctags_index: Optional[CtagsIndex] = None

    def run(self) -> int:
        """Run the application.

        Returns:
            Exit code (0 for success, non-zero for error).
        """
        try:
            self._setup()
            self._run_main_loop()
            return 0
        except (ConfigError, GitError, LLMClientError, LockFileError, CtagsNotFoundError, CtagsError) as e:
            logger.error(str(e))
            return 1
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            return 130  # Standard exit code for SIGINT
        except SystemExit as e:
            # User declined to overwrite or other sys.exit() call
            # Make sure cleanup runs
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return 1
        finally:
            self._cleanup()

    def _setup(self) -> None:
        """Set up all components."""
        # Print paths before logging is set up (goes to console only)
        print(f"Log file: {self.config.log_path}")
        print(f"Lock file: {self.config.lock_path}")
        
        # Check and acquire lock
        self._acquire_lock()

        # Backup existing output file (automated, no prompts)
        self._backup_existing_output()

        # Set up logging
        setup_logging(self.config.log_path)
        total_checks = sum(len(g.checks) for g in self.config.check_groups)
        logger.info(
            f"{'=' * 60}\n"
            f"Code Scanner starting\n"
            f"Target directory: {self.config.target_directory}\n"
            f"Config file: {self.config.config_file}\n"
            f"Output file: {self.config.output_path}\n"
            f"Log file: {self.config.log_path}\n"
            f"Lock file: {self.config.lock_path}\n"
            f"Check groups: {len(self.config.check_groups)}, Total checks: {total_checks}\n"
            f"{'=' * 60}"
        )

        # Initialize components
        self.git_watcher = GitWatcher(
            self.config.target_directory,
            self.config.commit_hash,
        )
        self.git_watcher.connect()

        # Create appropriate LLM client based on backend
        self.llm_client = create_llm_client(self.config)
        self.llm_client.connect()
        logger.info(f"Connected to {self.llm_client.backend_name}")

        # Set context limit from config (now required)
        self.llm_client.set_context_limit(self.config.llm.context_limit)

        # Initialize ctags index for symbol navigation
        logger.info("Initializing ctags index...")
        self.ctags_index = CtagsIndex(self.config.target_directory)
        symbol_count = self.ctags_index.generate_index()
        logger.info(f"Ctags index ready: {symbol_count} symbols indexed")

        self.issue_tracker = IssueTracker()
        self.output_generator = OutputGenerator(self.config.output_path)

        # Create initial output file so user knows it's working
        self.output_generator.write(self.issue_tracker, {"status": "Scanning in progress..."})
        logger.info(f"Created initial output file: {self.config.output_path}")

        self.scanner = Scanner(
            config=self.config,
            git_watcher=self.git_watcher,
            llm_client=self.llm_client,
            issue_tracker=self.issue_tracker,
            output_generator=self.output_generator,
            ctags_index=self.ctags_index,
        )

    def _acquire_lock(self) -> None:
        """Acquire the lock file.
        
        Checks if the lock file exists and if the PID in it is still running.
        If the process is dead, removes the stale lock and acquires a new one.

        Raises:
            LockFileError: If another instance is already running.
        """
        lock_path = self.config.lock_path

        if lock_path.exists():
            # Read PID from lock file
            try:
                pid_str = lock_path.read_text().strip()
                pid = int(pid_str)
                
                # Check if process is still running
                if self._is_process_running(pid):
                    raise LockFileError(
                        f"Another code-scanner instance is already running (PID: {pid}).\n"
                        f"Lock file: {lock_path}\n"
                        "Wait for it to finish or terminate it manually."
                    )
                else:
                    # Process is dead, remove stale lock
                    lock_path.unlink()
                    logger.info(f"Removed stale lock file (PID {pid} no longer running)")
            except (ValueError, IOError) as e:
                # Invalid lock file contents, remove it
                try:
                    lock_path.unlink()
                    logger.warning(f"Removed invalid lock file: {e}")
                except IOError:
                    raise LockFileError(f"Could not remove invalid lock file: {lock_path}")

        # Create lock file with PID
        try:
            with open(lock_path, "w") as f:
                f.write(f"{os.getpid()}\n")
            self._lock_acquired = True
            logger.debug(f"Acquired lock: {lock_path}")
            
            # Register atexit handler to ensure lock is released on any exit
            atexit.register(self._release_lock)
        except IOError as e:
            raise LockFileError(f"Could not create lock file: {e}")

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with the given PID is running.
        
        Args:
            pid: Process ID to check.
            
        Returns:
            True if the process is running, False otherwise.
        """
        try:
            # os.kill with signal 0 doesn't kill, just checks if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _release_lock(self) -> None:
        """Release the lock file."""
        if self._lock_acquired:
            lock_path = self.config.lock_path
            try:
                if lock_path.exists():
                    lock_path.unlink()
                    logger.debug(f"Released lock: {lock_path}")
            except IOError as e:
                logger.warning(f"Could not remove lock file: {e}")
            self._lock_acquired = False

    def _backup_existing_output(self) -> None:
        """Backup existing output file if it exists.
        
        Appends content to .bak file with timestamp prefix.
        """
        output_path = self.config.output_path

        if output_path.exists():
            backup_path = output_path.parent / f"{output_path.name}.bak"
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            
            try:
                content = output_path.read_text(encoding='utf-8')
                
                # Append to backup file with timestamp separator
                with open(backup_path, "a", encoding='utf-8') as f:
                    f.write(f"\n\n{'=' * 60}\n")
                    f.write(f"Backup created: {timestamp}\n")
                    f.write(f"{'=' * 60}\n\n")
                    f.write(content)
                
                logger.info(f"Backed up existing output to {backup_path}")
                
                # Remove original file
                output_path.unlink()
                logger.debug(f"Removed existing output file: {output_path}")
                
            except IOError as e:
                logger.warning(f"Could not backup output file: {e}")

    def _run_main_loop(self) -> None:
        """Run the main application loop."""
        # Set up signal handler for clean exit
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start Git watcher thread
        self._git_thread = threading.Thread(target=self._git_watch_loop, daemon=True)
        self._git_thread.start()

        # Start scanner
        self.scanner.start()

        # Wait for stop signal
        logger.info("Scanner running. Press Ctrl+C to stop.")
        while not self._stop_event.is_set():
            time.sleep(0.5)

    def _git_watch_loop(self) -> None:
        """Git watcher loop - polls for changes."""
        logger.info("Git watcher started")
        last_state = None

        while not self._stop_event.is_set():
            try:
                # Check for changes
                if self.git_watcher.has_changes_since(last_state):
                    logger.info("Git changes detected, signaling scanner to refresh")
                    self.scanner.signal_refresh()
                    last_state = self.git_watcher.get_state()

                # Wait before next poll
                self._stop_event.wait(timeout=self.config.git_poll_interval)

            except Exception as e:
                logger.error(f"Git watcher error: {e}")
                time.sleep(5)

        logger.info("Git watcher stopped")

    def _signal_handler(self, signum: int, _frame: object) -> None:
        """Handle termination signals."""
        logger.info(f"Received signal {signum}, stopping...")
        self._stop_event.set()

    def _cleanup(self) -> None:
        """Clean up resources."""
        try:
            logger.info("Cleaning up...")
        except Exception:
            pass  # Logging may not be set up yet

        self._stop_event.set()

        if self.scanner:
            self.scanner.stop()

        if self._git_thread and self._git_thread.is_alive():
            self._git_thread.join(timeout=2)

        self._release_lock()

        try:
            logger.info("Cleanup complete")
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="code-scanner",
        description="AI-driven code scanner for identifying issues in uncommitted changes",
    )

    parser.add_argument(
        "target_directory",
        type=Path,
        help="Target directory to scan (must be a Git repository)",
    )

    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=None,
        help="Path to configuration file (default: config.toml in scanner directory)",
    )

    parser.add_argument(
        "--commit",
        type=str,
        default=None,
        help="Git commit hash to compare against (default: HEAD)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point.

    Returns:
        Exit code.
    """
    args = parse_args()

    try:
        config = load_config(
            target_directory=args.target_directory,
            config_file=args.config,
            commit_hash=args.commit,
        )
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    app = Application(config)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
