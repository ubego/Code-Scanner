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
from .base_client import BaseLLMClient, LLMClientError, ContextOverflowError, SYSTEM_PROMPT_TEMPLATE, build_user_prompt
from .models import Issue, GitState, ChangedFile, CheckGroup
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
        llm_client: BaseLLMClient,
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
        self._refresh_event = threading.Event()  # Signals to refresh file contents
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
        self._refresh_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scanner thread started")

    def stop(self) -> None:
        """Stop the scanner thread."""
        logger.info("Stopping scanner thread...")
        self._stop_event.set()
        self._refresh_event.set()  # Wake up if waiting
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("Scanner thread stopped")

    def signal_refresh(self) -> None:
        """Signal the scanner to refresh file contents for the current check.
        
        When files change, the scanner will continue from its current position
        with refreshed file contents, rather than restarting from the beginning.
        """
        logger.info("Signaling scanner to refresh file contents")
        self._refresh_event.set()

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
                    # Wait for refresh signal or timeout
                    self._refresh_event.wait(timeout=self.config.git_poll_interval)
                    self._refresh_event.clear()
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

        # Process all check groups
        all_issues: list[Issue] = []
        total_checks = sum(len(g.checks) for g in self.config.check_groups)
        current_check_index = 0

        for group_idx, check_group in enumerate(self.config.check_groups):
            if self._stop_event.is_set():
                break

            # Filter batches to only include files matching this group's pattern
            filtered_batches = self._filter_batches_by_pattern(batches, check_group)
            if not filtered_batches:
                logger.debug(f"No files match pattern '{check_group.pattern}', skipping group")
                current_check_index += len(check_group.checks)
                continue

            logger.info(f"Check group {group_idx + 1}/{len(self.config.check_groups)}: pattern '{check_group.pattern}'")

            for check_idx, check in enumerate(check_group.checks):
                if self._stop_event.is_set():
                    break

                current_check_index += 1
                logger.info(f"Running check {current_check_index}/{total_checks}: {check[:50]}...")

                try:
                    # Run check against filtered batches
                    check_issues = self._run_check(check, filtered_batches)
                    all_issues.extend(check_issues)
                    self._scan_info["checks_run"] += 1

                    # Immediately add new issues to tracker
                    if check_issues:
                        new_count = self.issue_tracker.add_issues(check_issues)
                        if new_count > 0:
                            logger.info(f"Added {new_count} new issue(s) to tracker")

                    # Update output file after every check for incremental progress
                    self.output_generator.write(self.issue_tracker, self._scan_info)
                    logger.debug(f"Output file updated after check {self._scan_info['checks_run']}")

                except ContextOverflowError:
                    # Context overflow is FATAL - requires user intervention
                    # Re-raise to exit the application
                    raise
                except LLMClientError as e:
                    if "Lost connection" in str(e):
                        # Mid-session failure - wait for reconnection
                        logger.warning("Lost LLM connection, waiting for reconnection...")
                        self.llm_client.wait_for_connection(self.config.llm_retry_interval)
                        # Retry this check by decrementing counter
                        current_check_index -= 1
                        continue
                    else:
                        logger.error(f"LLM error during check: {e}")
                        # Skip this check after max retries

                # Check for refresh signal - clear it but continue processing
                # (files will be refreshed on next check iteration)
                if self._refresh_event.is_set():
                    logger.info("File changes detected, will use refreshed content for remaining checks")
                    self._refresh_event.clear()

        # Handle deleted files - resolve their issues
        deleted_files = [f.path for f in git_state.changed_files if f.is_deleted]
        for deleted_file in deleted_files:
            self.issue_tracker.resolve_issues_for_file(deleted_file)

        # Log total issues found in this scan
        logger.info(f"Scan found {len(all_issues)} total issue(s) across all checks")

        # Update issue tracker with scan results
        new_count, resolved_count = self.issue_tracker.update_from_scan(
            all_issues, scanned_files
        )
        logger.info(f"Scan complete: {new_count} new issues, {resolved_count} resolved")

        # Write output
        self.output_generator.write(self.issue_tracker, self._scan_info)
        logger.info(f"Output file updated with {self.issue_tracker.get_stats()['total']} total issues")

    def _filter_batches_by_pattern(
        self,
        batches: list[dict[str, str]],
        check_group: CheckGroup,
    ) -> list[dict[str, str]]:
        """Filter batches to only include files matching the check group's pattern.

        Args:
            batches: List of file batches.
            check_group: The check group with pattern to filter by.

        Returns:
            Filtered batches with only matching files.
        """
        filtered_batches: list[dict[str, str]] = []

        for batch in batches:
            filtered_batch = {
                file_path: content
                for file_path, content in batch.items()
                if check_group.matches_file(file_path)
            }
            if filtered_batch:
                filtered_batches.append(filtered_batch)

        return filtered_batches

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

        Issues are added to tracker and output is updated after each batch
        for immediate feedback, rather than waiting for all batches to complete.

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
                logger.info(f"LLM returned {len(issues_data)} issue(s) for batch {batch_idx + 1}")
                timestamp = datetime.now()

                batch_issues: list[Issue] = []
                for issue_data in issues_data:
                    try:
                        issue = Issue.from_llm_response(
                            issue_data,
                            check_query=check_query,
                            timestamp=timestamp,
                        )
                        batch_issues.append(issue)
                        all_issues.append(issue)
                        logger.debug(f"Parsed issue: {issue.file_path}:{issue.line_number}")
                    except Exception as e:
                        logger.warning(f"Failed to parse issue: {e}, data: {issue_data}")

                # Immediately add batch issues to tracker and update output
                if batch_issues:
                    new_count = self.issue_tracker.add_issues(batch_issues)
                    if new_count > 0:
                        logger.info(f"Added {new_count} new issue(s) from batch {batch_idx + 1}")

                # Update output after each batch for immediate feedback
                self.output_generator.write(self.issue_tracker, self._scan_info)
                logger.info(f"Output updated after batch {batch_idx + 1}/{len(batches)}")

            except LLMClientError as e:
                logger.error(f"Check failed after retries: {e}")
                raise

        return all_issues
