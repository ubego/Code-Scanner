"""CLI entry point and main application."""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .config import Config, ConfigError, load_config
from .git_watcher import GitWatcher, GitError
from .issue_tracker import IssueTracker
from .llm_client import LLMClient, LLMClientError
from .output import OutputGenerator
from .scanner import Scanner
from .utils import setup_logging, is_interactive, prompt_yes_no

logger = logging.getLogger(__name__)


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
        self.llm_client: Optional[LLMClient] = None
        self.issue_tracker: Optional[IssueTracker] = None
        self.output_generator: Optional[OutputGenerator] = None
        self.scanner: Optional[Scanner] = None

        self._git_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock_acquired = False

    def run(self) -> int:
        """Run the application.

        Returns:
            Exit code (0 for success, non-zero for error).
        """
        try:
            self._setup()
            self._run_main_loop()
            return 0
        except (ConfigError, GitError, LLMClientError, LockFileError) as e:
            logger.error(str(e))
            return 1
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            return 130  # Standard exit code for SIGINT
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return 1
        finally:
            self._cleanup()

    def _setup(self) -> None:
        """Set up all components."""
        # Check and acquire lock
        self._acquire_lock()

        # Check for existing output file
        self._check_output_file()

        # Set up logging
        setup_logging(self.config.log_path)
        logger.info("=" * 60)
        logger.info("Code Scanner starting")
        logger.info(f"Target directory: {self.config.target_directory}")
        logger.info(f"Config file: {self.config.config_file}")
        logger.info(f"Checks: {len(self.config.checks)}")
        logger.info("=" * 60)

        # Initialize components
        self.git_watcher = GitWatcher(
            self.config.target_directory,
            self.config.commit_hash,
        )
        self.git_watcher.connect()

        self.llm_client = LLMClient(self.config.llm)
        self.llm_client.connect()

        self.issue_tracker = IssueTracker()
        self.output_generator = OutputGenerator(self.config.output_path)

        self.scanner = Scanner(
            config=self.config,
            git_watcher=self.git_watcher,
            llm_client=self.llm_client,
            issue_tracker=self.issue_tracker,
            output_generator=self.output_generator,
        )

    def _acquire_lock(self) -> None:
        """Acquire the lock file.

        Raises:
            LockFileError: If lock file exists.
        """
        lock_path = self.config.lock_path

        if lock_path.exists():
            raise LockFileError(
                f"Lock file exists: {lock_path}\n"
                "Another instance may be running. If not, delete the lock file manually."
            )

        # Create lock file with PID
        try:
            with open(lock_path, "w") as f:
                f.write(f"{os.getpid()}\n")
            self._lock_acquired = True
            logger.debug(f"Acquired lock: {lock_path}")
        except IOError as e:
            raise LockFileError(f"Could not create lock file: {e}")

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

    def _check_output_file(self) -> None:
        """Check for existing output file and prompt for overwrite.

        Raises:
            SystemExit: If user declines to overwrite.
        """
        output_path = self.config.output_path

        if output_path.exists():
            if not is_interactive():
                raise RuntimeError(
                    "Output file exists and running in non-interactive mode. "
                    "Please delete the file manually or run interactively."
                )

            if not prompt_yes_no(
                f"Output file {output_path} already exists. Overwrite?",
                default=False,
            ):
                logger.info("User declined to overwrite, exiting")
                sys.exit(0)

            # Delete existing file
            output_path.unlink()
            logger.info(f"Deleted existing output file: {output_path}")

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
                    logger.info("Git changes detected, signaling scanner")
                    self.scanner.signal_restart()
                    last_state = self.git_watcher.get_state()

                # Wait before next poll
                self._stop_event.wait(timeout=self.config.git_poll_interval)

            except Exception as e:
                logger.error(f"Git watcher error: {e}")
                time.sleep(5)

        logger.info("Git watcher stopped")

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle termination signals."""
        logger.info(f"Received signal {signum}, stopping...")
        self._stop_event.set()

    def _cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up...")

        self._stop_event.set()

        if self.scanner:
            self.scanner.stop()

        if self._git_thread and self._git_thread.is_alive():
            self._git_thread.join(timeout=2)

        self._release_lock()

        logger.info("Cleanup complete")


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
