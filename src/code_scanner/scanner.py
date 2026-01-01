"""AI Scanner thread - executes checks against code."""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config
from .git_watcher import GitWatcher
from .issue_tracker import IssueTracker
from .llm_client import LLMClient, LLMClientError, SYSTEM_PROMPT_TEMPLATE, build_user_prompt
from .models import Issue, GitState, ChangedFile
from .output import OutputGenerator
from .utils import (
    estimate_tokens,
    read_file_content,
    is_binary_file,
    group_files_by_directory,
)

logger = logging.getLogger(__name__)


class Scanner:
    """AI Scanner that executes checks against code changes."""

    def __init__(
        self,
        config: Config,
        git_watcher: GitWatcher,
        llm_client: LLMClient,
        issue_tracker: IssueTracker,
        output_generator: OutputGenerator,
    ):
        """Initialize the scanner.

        Args:
            config: Application configuration.
            git_watcher: Git watcher instance.
            llm_client: LLM client instance.
            issue_tracker: Issue tracker instance.
            output_generator: Output generator instance.
        """
        self.config = config
        self.git_watcher = git_watcher
        self.llm_client = llm_client
        self.issue_tracker = issue_tracker
        self.output_generator = output_generator

        # Threading controls
        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # State
        self._current_check_index = 0
        self._last_git_state: Optional[GitState] = None
        self._scan_info: dict = {}

    def start(self) -> None:
        """Start the scanner thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Scanner already running")
            return

        self._stop_event.clear()
        self._restart_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scanner thread started")

    def stop(self) -> None:
        """Stop the scanner thread."""
        logger.info("Stopping scanner thread...")
        self._stop_event.set()
        self._restart_event.set()  # Wake up if waiting
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("Scanner thread stopped")

    def signal_restart(self) -> None:
        """Signal the scanner to restart from the beginning of checks."""
        logger.info("Signaling scanner restart")
        self._restart_event.set()

    def _run_loop(self) -> None:
        """Main scanner loop."""
        logger.info("Scanner loop started")

        while not self._stop_event.is_set():
            try:
                # Get current git state
                git_state = self.git_watcher.get_state()

                # Wait if merge/rebase in progress
                if git_state.is_conflict_resolution_in_progress:
                    logger.info("Waiting for merge/rebase to complete...")
                    time.sleep(self.config.git_poll_interval)
                    continue

                # Wait if no changes
                if not git_state.has_changes:
                    logger.debug("No changes detected, waiting...")
                    # Wait for restart signal or timeout
                    self._restart_event.wait(timeout=self.config.git_poll_interval)
                    self._restart_event.clear()
                    continue

                # Run scan
                self._run_scan(git_state)

            except Exception as e:
                logger.error(f"Scanner error: {e}", exc_info=True)
                time.sleep(5)  # Brief pause before retrying

        logger.info("Scanner loop ended")

    def _run_scan(self, git_state: GitState) -> None:
        """Run a full scan cycle.

        Args:
            git_state: Current Git state with changed files.
        """
        logger.info(f"Starting scan with {len(git_state.changed_files)} changed files")

        # Get file contents
        files_content = self._get_files_content(git_state.changed_files)
        if not files_content:
            logger.info("No scannable files found")
            return

        scanned_files = list(files_content.keys())
        self._scan_info = {
            "files_scanned": scanned_files,
            "skipped_files": [],
            "checks_run": 0,
        }

        # Determine batching strategy
        batches = self._create_batches(files_content)
        logger.info(f"Created {len(batches)} batch(es) for scanning")

        # Process all checks
        self._current_check_index = 0
        all_issues: list[Issue] = []

        while self._current_check_index < len(self.config.checks):
            if self._stop_event.is_set():
                break

            check = self.config.checks[self._current_check_index]
            logger.info(f"Running check {self._current_check_index + 1}/{len(self.config.checks)}: {check[:50]}...")

            try:
                # Run check against all batches
                check_issues = self._run_check(check, batches)
                all_issues.extend(check_issues)
                self._scan_info["checks_run"] += 1

            except LLMClientError as e:
                if "Lost connection" in str(e):
                    # Mid-session failure - wait for reconnection
                    logger.warning("Lost LLM connection, waiting for reconnection...")
                    self.llm_client.wait_for_connection(self.config.llm_retry_interval)
                    continue  # Retry this check
                else:
                    logger.error(f"LLM error during check: {e}")
                    # Skip this check after max retries

            # Check for restart signal
            if self._restart_event.is_set():
                logger.info("Restart signal received, discarding current check results")
                self._restart_event.clear()
                self._current_check_index = 0
                all_issues.clear()
                
                # Get fresh git state
                git_state = self.git_watcher.get_state()
                files_content = self._get_files_content(git_state.changed_files)
                if not files_content:
                    return
                batches = self._create_batches(files_content)
                scanned_files = list(files_content.keys())
                continue

            self._current_check_index += 1

        # Handle deleted files - resolve their issues
        deleted_files = [f.path for f in git_state.changed_files if f.is_deleted]
        for deleted_file in deleted_files:
            self.issue_tracker.resolve_issues_for_file(deleted_file)

        # Update issue tracker with scan results
        new_count, resolved_count = self.issue_tracker.update_from_scan(
            all_issues, scanned_files
        )
        logger.info(f"Scan complete: {new_count} new issues, {resolved_count} resolved")

        # Write output if there were changes
        if self.issue_tracker.has_changed:
            self.output_generator.write(self.issue_tracker, self._scan_info)
            self.issue_tracker.reset_changed_flag()

        # Loop back to first check and continue
        self._current_check_index = 0

    def _get_files_content(
        self,
        changed_files: list[ChangedFile],
    ) -> dict[str, str]:
        """Get content of changed files.

        Args:
            changed_files: List of changed files.

        Returns:
            Dictionary mapping file paths to content.
        """
        # Files generated by code-scanner that should never be scanned
        scanner_files = {
            self.config.output_file,  # code_scanner_results.md
            self.config.log_file,     # code_scanner.log
        }
        
        files_content: dict[str, str] = {}

        for file_info in changed_files:
            if file_info.is_deleted:
                continue

            # Skip code-scanner's own output files
            if file_info.path in scanner_files:
                logger.debug(f"Skipping scanner output file: {file_info.path}")
                continue

            file_path = self.config.target_directory / file_info.path

            if is_binary_file(file_path):
                logger.debug(f"Skipping binary file: {file_info.path}")
                continue

            content = read_file_content(file_path)
            if content is not None:
                files_content[file_info.path] = content
            else:
                logger.warning(f"Could not read file: {file_info.path}")

        return files_content

    def _create_batches(
        self,
        files_content: dict[str, str],
    ) -> list[dict[str, str]]:
        """Create batches of files based on context limit.

        Args:
            files_content: Dictionary of file paths to content.

        Returns:
            List of batches, each a dict of file paths to content.
        """
        context_limit = self.llm_client.context_limit

        # Reserve tokens for prompt overhead and response
        available_tokens = int(context_limit * 0.7)  # 70% for content

        # Try all files together first
        total_tokens = sum(estimate_tokens(c) for c in files_content.values())
        if total_tokens <= available_tokens:
            return [files_content]

        # Group by directory hierarchy
        batches: list[dict[str, str]] = []
        groups = group_files_by_directory(list(files_content.keys()))

        current_batch: dict[str, str] = {}
        current_tokens = 0

        for dir_path, file_paths in groups.items():
            dir_content: dict[str, str] = {}
            dir_tokens = 0

            for file_path in file_paths:
                content = files_content[file_path]
                tokens = estimate_tokens(content)

                # Skip files that alone exceed the limit
                if tokens > available_tokens:
                    logger.warning(
                        f"Skipping oversized file: {file_path} "
                        f"({tokens} tokens > {available_tokens} available)"
                    )
                    self._scan_info["skipped_files"].append(file_path)
                    continue

                dir_content[file_path] = content
                dir_tokens += tokens

            if not dir_content:
                continue

            # Check if directory group fits in current batch
            if current_tokens + dir_tokens <= available_tokens:
                current_batch.update(dir_content)
                current_tokens += dir_tokens
            else:
                # Try to fit individual files
                if dir_tokens <= available_tokens:
                    # Start new batch with this directory
                    if current_batch:
                        batches.append(current_batch)
                    current_batch = dir_content
                    current_tokens = dir_tokens
                else:
                    # Split directory into individual files
                    if current_batch:
                        batches.append(current_batch)
                        current_batch = {}
                        current_tokens = 0

                    for file_path, content in dir_content.items():
                        tokens = estimate_tokens(content)
                        if current_tokens + tokens <= available_tokens:
                            current_batch[file_path] = content
                            current_tokens += tokens
                        else:
                            if current_batch:
                                batches.append(current_batch)
                            current_batch = {file_path: content}
                            current_tokens = tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    def _run_check(
        self,
        check_query: str,
        batches: list[dict[str, str]],
    ) -> list[Issue]:
        """Run a single check against all batches.

        Args:
            check_query: The check query to run.
            batches: List of file batches.

        Returns:
            List of issues found.
        """
        all_issues: list[Issue] = []

        for batch_idx, batch in enumerate(batches):
            if self._stop_event.is_set():
                break

            logger.debug(f"Processing batch {batch_idx + 1}/{len(batches)}")

            # Build prompt
            user_prompt = build_user_prompt(check_query, batch)
            logger.info(f"Sending query to LLM: {check_query}")
            logger.debug(f"User prompt length: {len(user_prompt)} chars")

            # Query LLM
            try:
                response = self.llm_client.query(
                    system_prompt=SYSTEM_PROMPT_TEMPLATE,
                    user_prompt=user_prompt,
                    max_retries=self.config.max_llm_retries,
                )

                # Parse issues from response
                issues_data = response.get("issues", [])
                timestamp = datetime.now()

                for issue_data in issues_data:
                    try:
                        issue = Issue.from_llm_response(
                            issue_data,
                            check_query=check_query,
                            timestamp=timestamp,
                        )
                        all_issues.append(issue)
                    except Exception as e:
                        logger.warning(f"Failed to parse issue: {e}")

            except LLMClientError as e:
                logger.error(f"Check failed after retries: {e}")
                raise

        return all_issues
