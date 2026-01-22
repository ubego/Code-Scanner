"""AI Scanner thread - executes checks against code."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .config import Config
from .ctags_index import CtagsIndex
from .file_filter import FileFilter
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
from .ai_tools import AIToolExecutor, AI_TOOLS_SCHEMA

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
        ctags_index: CtagsIndex,
        file_filter: Optional[FileFilter] = None,
    ):
        """Initialize the scanner.

        Args:
            config: Application configuration.
            git_watcher: Git watcher instance.
            llm_client: LLM client instance.
            issue_tracker: Issue tracker instance.
            output_generator: Output generator instance.
            ctags_index: Ctags index for symbol navigation.
            file_filter: Optional unified file filter for efficient filtering.
        """
        self.config = config
        self.git_watcher = git_watcher
        self.llm_client = llm_client
        self.issue_tracker = issue_tracker
        self.output_generator = output_generator
        self.ctags_index = ctags_index
        self._file_filter = file_filter

        # Initialize AI tool executor for context expansion
        self._tool_executor = None

        # Threading controls
        self._stop_event = threading.Event()
        self._refresh_event = threading.Event()  # Signals to refresh file contents
        self._thread: Optional[threading.Thread] = None

        # State
        self._last_scanned_files: set[str] = set()  # Files scanned in last cycle
        self._last_file_contents_hash: dict[str, int] = {}  # Hash of file contents
        self._scan_info: dict = {}

    @property
    def tool_executor(self) -> AIToolExecutor:
        """Lazy initialization of the tool executor.
        
        This prevents accessing llm_client.context_limit before the client
        is connected (which would raise an error).
        """
        if self._tool_executor is None:
            self._tool_executor = AIToolExecutor(
                target_directory=self.config.target_directory,
                context_limit=self.llm_client.context_limit,
                ctags_index=self.ctags_index,
            )
        return self._tool_executor

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

    def _signal_refresh(self) -> None:
        """Signal the scanner to refresh file contents for the current check.
        
        ⚠️ TEST ONLY: This method is intended for unit tests to simulate
        file system change signals. Production code should rely on the
        git watcher's file system monitoring.
        
        When files change, the scanner will continue from its current position
        with refreshed file contents, rather than restarting from the beginning.
        """
        logger.info("Refresh signal received - worktree changes detected by git watcher")
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
                    # Clear tracking since files were committed/reverted
                    self._last_scanned_files.clear()
                    self._last_file_contents_hash.clear()
                    # Wait for refresh signal or timeout
                    was_signaled = self._refresh_event.wait(timeout=self.config.git_poll_interval)
                    self._refresh_event.clear()
                    if was_signaled:
                        logger.debug("Woke up from refresh signal (no changes state)")
                    continue

                # Check if files have actually changed since last scan
                current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
                logger.debug(f"Checking if files changed: git_state.has_changes={git_state.has_changes}, "
                            f"current_files={len(current_files)}")
                has_changed = self._has_files_changed(current_files, git_state)
                logger.debug(f"_has_files_changed returned: {has_changed}")
                if has_changed:
                    # Clear refresh event before scan - any signals during scan will set it again
                    self._refresh_event.clear()
                    # Run scan
                    self._run_scan(git_state)
                else:
                    # No new changes - wait for refresh signal or timeout
                    logger.debug("No new file changes since last scan, waiting...")
                    was_signaled = self._refresh_event.wait(timeout=self.config.git_poll_interval)
                    self._refresh_event.clear()
                    if was_signaled:
                        logger.debug("Woke up from refresh signal (no content changes state)")

            except Exception as e:
                logger.error(f"Scanner error: {e}", exc_info=True)
                time.sleep(5)  # Brief pause before retrying

        logger.info("Scanner loop ended")

    def _is_file_ignored(self, file_path: str) -> bool:
        """Check if a file should be ignored from scanning.
        
        Uses the unified FileFilter if available (which includes config ignore
        patterns AND gitignore patterns), otherwise falls back to checking
        config ignore patterns only.
        
        Args:
            file_path: Relative path to the file.
            
        Returns:
            True if the file should be ignored from scanning.
        """
        # Use unified FileFilter if available (includes gitignore + config patterns)
        if self._file_filter is not None:
            should_skip, _ = self._file_filter.should_skip(file_path)
            return should_skip
        
        # Fallback: check config ignore patterns only
        for pattern_group in self.config.check_groups:
            if not pattern_group.checks and pattern_group.matches_file(file_path):
                return True
        return False

    def _has_files_changed(self, current_files: set[str], git_state: GitState) -> bool:
        """Check if files have changed since the last scan.
        
        Args:
            current_files: Set of current file paths (non-deleted).
            git_state: Current git state.
            
        Returns:
            True if files have changed and need rescanning.
        """
        # Note: _refresh_event being set just means git watcher detected something,
        # but we still need to check if files ACTUALLY changed content-wise
        
        # Filter out ignored files from current set to match _last_scanned_files
        # (_last_scanned_files only contains non-ignored files after scan completes)
        current_non_ignored = {f for f in current_files if not self._is_file_ignored(f)}
        
        logger.debug(f"_has_files_changed: current_files={len(current_files)}, current_non_ignored={len(current_non_ignored)}, "
                    f"last_scanned={len(self._last_scanned_files)}")
        
        # Check for new files added (files committed/removed don't require rescan)
        added_files = current_non_ignored - self._last_scanned_files
        if added_files:
            logger.debug(f"New files added to worktree: {list(added_files)[:5]}{'...' if len(added_files) > 5 else ''}")
            return True
        
        # Log removed files but don't trigger rescan
        removed_files = self._last_scanned_files - current_non_ignored
        if removed_files:
            logger.debug(f"Files removed from worktree (committed/reverted): {list(removed_files)[:5]}{'...' if len(removed_files) > 5 else ''}")
        
        # Check if any file contents have changed by comparing hashes
        for changed_file in git_state.changed_files:
            if changed_file.is_deleted:
                continue
            
            # Skip ignored files - they don't affect scan results
            # Skip early to avoid unnecessary hash checks and file reading
            if self._is_file_ignored(changed_file.path):
                continue
            
            file_path = self.config.target_directory / changed_file.path
            try:
                # Use helper for safe file reading (handles encoding issues)
                content = read_file_content(file_path)
                if content is None:
                    # Binary or unreadable file - check if it's new
                    if changed_file.path not in self._last_scanned_files:
                        logger.debug(f"New binary/unreadable file detected: {changed_file.path}")
                        return True
                    continue
                
                content_hash = hash(content)
                
                if changed_file.path not in self._last_file_contents_hash:
                    logger.debug(f"New file detected: {changed_file.path}")
                    return True
                if self._last_file_contents_hash[changed_file.path] != content_hash:
                    logger.debug(f"File content changed: {changed_file.path}")
                    return True
            except OSError as e:
                # File system error - file doesn't exist or can't be accessed
                # Check if it's a new file (not in _last_scanned_files)
                if changed_file.path not in self._last_scanned_files:
                    logger.debug(f"New file detected (OSError): {changed_file.path}")
                    return True
                # Existing file that can't be read - skip it (don't assume it changed)
                logger.debug(f"Cannot read existing file {changed_file.path}, skipping: {e}")
                continue
            except Exception as e:
                # Other errors (encoding, etc.) - assume it changed
                logger.debug(f"Cannot read file {changed_file.path}, assuming changed: {e}")
                return True
        
        logger.info("Refresh event processed: no actual file content changes detected")
        logger.debug(f"_has_files_changed returning False")
        return False

    def _run_scan(self, git_state: GitState) -> None:
        """Run a full scan cycle with watermark-based rescanning.

        When worktree changes during scanning, checks after the change point already
        use fresh content. Only checks before the change point need re-running.
        This loops until all checks complete on an unchanged worktree snapshot.

        Args:
            git_state: Current Git state with changed files.
        """
        # Clear file cache since we're starting a new scan with potentially changed files
        self.tool_executor.clear_file_cache()
        
        # Log changed files at the start of scan cycle
        changed_file_paths = [f.path for f in git_state.changed_files if not f.is_deleted]
        logger.info(f"Starting scan with {len(changed_file_paths)} changed files")
        if changed_file_paths:
            # Log first 20 files, with indicator if there are more
            files_to_log = changed_file_paths[:20]
            logger.info(f"Changed files: {files_to_log}{'...' if len(changed_file_paths) > 20 else ''}")

        # Build flat list of (check_group, check, filtered_batches) for index-based iteration
        # This needs to be rebuilt each iteration to get fresh file content
        def build_check_list() -> list[tuple[CheckGroup, str, list[dict[str, str]]]]:
            """Build list of checks with their filtered batches using fresh file content."""
            files_content = self._get_files_content(git_state.changed_files)
            if not files_content:
                return []

            # Filter out files matching ignore patterns
            filtered_content, ignored = self._filter_ignored_files(files_content)
            if ignored:
                logger.debug(f"Ignoring {len(ignored)} file(s) matching ignore patterns")
            
            if not filtered_content:
                return []

            # Update scan info - preserve checks_run count across iterations
            existing_checks_run = self._scan_info.get("checks_run", 0) if self._scan_info else 0
            existing_total_checks = self._scan_info.get("total_checks", 0) if self._scan_info else 0
            self._scan_info = {
                "files_scanned": list(filtered_content.keys()),
                "skipped_files": ignored,
                "checks_run": existing_checks_run,
                "total_checks": existing_total_checks,
            }

            batches = self._create_batches(filtered_content)
            
            check_list: list[tuple[CheckGroup, str, list[dict[str, str]]]] = []
            for check_group in self.config.check_groups:
                if not check_group.checks:
                    continue  # Skip ignore patterns
                
                filtered_batches = self._filter_batches_by_pattern(batches, check_group)
                if not filtered_batches:
                    continue  # No files match this pattern
                
                for check in check_group.checks:
                    check_list.append((check_group, check, filtered_batches))
            
            return check_list

        # Reset scan info for new scan cycle
        self._scan_info = {}
        
        # Initial build
        check_list = build_check_list()
        if not check_list:
            logger.info("No scannable files or checks found")
            return

        total_checks = len(check_list)
        run_until = total_checks  # First pass: run all checks
        all_issues: list[Issue] = []
        iteration = 0

        # Store total_checks in scan_info for output
        self._scan_info["total_checks"] = total_checks

        logger.info(f"Created {total_checks} check(s) to run")

        # Watermark loop: run checks until no changes occur during the run
        while run_until > 0:
            iteration += 1
            if iteration > 1:
                logger.info(f"Rescan iteration {iteration}: running checks 1-{run_until} of {total_checks}")
                # Rebuild check list with fresh file content
                check_list = build_check_list()
                if not check_list:
                    logger.info("No scannable files after refresh")
                    break

            last_change_at: int | None = None

            for check_idx in range(run_until):
                if self._stop_event.is_set():
                    break

                check_group, check, filtered_batches = check_list[check_idx]
                logger.info(f"Running check {check_idx + 1}/{total_checks}: {check[:50]}...")

                try:
                    # Run check against filtered batches (uses fresh content per batch)
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

                except ContextOverflowError as e:
                    # Context overflow despite dynamic token tracking - this indicates
                    # our token estimation or limits are miscalculated. Log as ERROR.
                    logger.error(
                        f"UNEXPECTED context overflow during check - limits may be miscalculated! "
                        f"Check: {check[:50]}, Error: {e}"
                    )
                    skipped_key = "skipped_batches_context_overflow"
                    if skipped_key not in self._scan_info:
                        self._scan_info[skipped_key] = []
                    self._scan_info[skipped_key].append({
                        "check": check[:50],
                        "batch": batch_idx + 1 if 'batch_idx' in dir() else 0,
                        "error": "limits_miscalculated",
                    })
                    continue  # Skip to next check
                except LLMClientError as e:
                    error_msg = str(e).lower()
                    # Check for any connection-related error (lost connection, connection refused, etc.)
                    is_connection_error = any(
                        phrase in error_msg for phrase in [
                            "lost connection",
                            "connection refused",
                            "connection reset",
                            "connection error",
                            "not connected",
                            "urlopen error",
                            "network",
                            "timed out",
                        ]
                    )
                    
                    if is_connection_error:
                        logger.warning(f"LLM connection error: {e}")
                        logger.info("Waiting for LLM connection to be restored...")
                        self.llm_client.wait_for_connection(self.config.llm_retry_interval)
                        logger.info("LLM connection restored, retrying check...")
                        # Retry by not incrementing - watermark ensures check will run again
                        continue
                    else:
                        # Non-connection error (e.g., malformed response after retries)
                        # Log but continue to next check
                        logger.error(f"LLM error during check (skipping): {e}")

                # Track worktree changes - update watermark only if content actually changed
                if self._refresh_event.is_set():
                    self._refresh_event.clear()
                    # Verify content actually changed before triggering rescan
                    # The git watcher uses mtime which can have false positives
                    current_files = {f.path for f in git_state.changed_files if not f.is_deleted}
                    if self._has_files_changed(current_files, git_state):
                        last_change_at = check_idx
                        logger.info(f"Worktree changed at check {check_idx + 1}, will rescan checks 1-{check_idx + 1}")
                    else:
                        logger.debug(f"Refresh event received at check {check_idx + 1}, but no actual content changes detected")

            if self._stop_event.is_set():
                break

            if last_change_at is None:
                # No changes during this run - all checks are on fresh content
                logger.info(f"Scan iteration {iteration} complete with no worktree changes")
                break
            else:
                # Re-run checks 0..last_change_at (they used stale content)
                run_until = last_change_at + 1

        # Handle deleted files - resolve their issues
        deleted_files = [f.path for f in git_state.changed_files if f.is_deleted]
        for deleted_file in deleted_files:
            self.issue_tracker.resolve_issues_for_file(deleted_file)

        # Log total issues found in this scan
        logger.info(f"Scan found {len(all_issues)} total issue(s) across all checks")

        # Determine which files have actually changed content since last scan
        # Only resolve issues for files with changed content (LLM results are non-deterministic)
        files_content = self._get_files_content(git_state.changed_files)
        files_content, _ = self._filter_ignored_files(files_content)
        
        actually_changed_files: list[str] = []
        for file_path, content in files_content.items():
            current_hash = hash(content)
            previous_hash = self._last_file_contents_hash.get(file_path)
            if previous_hash is None or current_hash != previous_hash:
                # File is new or content changed - issues can be resolved if not re-reported
                actually_changed_files.append(file_path)
            # If content unchanged, don't resolve issues even if LLM didn't re-report them
        
        if actually_changed_files:
            logger.debug(f"Files with changed content: {actually_changed_files[:10]}{'...' if len(actually_changed_files) > 10 else ''}")

        # Update issue tracker with scan results - only for files that actually changed
        new_count, resolved_count = self.issue_tracker.update_from_scan(
            all_issues, actually_changed_files
        )
        logger.info(f"Scan complete: {new_count} new issues, {resolved_count} resolved")

        # Write output
        self.output_generator.write(self.issue_tracker, self._scan_info)
        logger.info(f"Output file updated with {self.issue_tracker.get_stats()['total']} total issues")

        # Track scanned files and their content hashes to avoid rescanning unchanged files
        # Store only non-ignored files to match what's in _last_file_contents_hash
        all_changed_paths = {f.path for f in git_state.changed_files if not f.is_deleted}
        all_changed_non_ignored = {f for f in all_changed_paths if not self._is_file_ignored(f)}
        self._last_scanned_files = all_changed_non_ignored
        
        # Update hash tracking with current content (reuse files_content from above)
        self._last_file_contents_hash = {}
        for file_path, content in files_content.items():
            self._last_file_contents_hash[file_path] = hash(content)
        logger.info("Scan cycle complete. Waiting for new file changes...")

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

        Uses FileFilter for unified filtering if available,
        otherwise falls back to manual scanner_files check.

        Args:
            changed_files: List of changed files.

        Returns:
            Dictionary mapping file paths to content.
        """
        files_content: dict[str, str] = {}

        for file_info in changed_files:
            if file_info.is_deleted:
                continue

            # Use unified filter if available
            if self._file_filter is not None:
                should_skip, reason = self._file_filter.should_skip(file_info.path)
                if should_skip:
                    logger.debug(f"Skipping file (reason: {reason}): {file_info.path}")
                    continue
            else:
                # Fallback: Files generated by code-scanner that should never be scanned
                scanner_files = {
                    self.config.output_file,  # code_scanner_results.md
                    f"{self.config.output_file}.bak",  # code_scanner_results.md.bak
                    self.config.log_file,     # code_scanner.log
                }
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

    def _filter_ignored_files(
        self,
        files_content: dict[str, str],
    ) -> tuple[dict[str, str], list[str]]:
        """Filter out files matching ignore patterns.

        If FileFilter is available, this is a no-op since filtering was
        already done in _get_files_content. Otherwise, applies config
        ignore patterns (check groups with empty checks list).

        Args:
            files_content: Dictionary mapping file paths to content.

        Returns:
            Tuple of (filtered files_content, list of ignored file paths).
        """
        # If unified filter was used, files are already filtered
        if self._file_filter is not None:
            return files_content, []
        
        # Fallback: Get ignore patterns (check groups with empty checks)
        ignore_patterns = [
            group for group in self.config.check_groups
            if not group.checks
        ]

        if not ignore_patterns:
            return files_content, []

        filtered_content: dict[str, str] = {}
        ignored_files: list[str] = []

        for file_path, content in files_content.items():
            # Check if file matches any ignore pattern
            should_ignore = False
            for pattern_group in ignore_patterns:
                if pattern_group.matches_file(file_path):
                    should_ignore = True
                    logger.debug(f"File '{file_path}' matches ignore pattern '{pattern_group.pattern}'")
                    break

            if should_ignore:
                ignored_files.append(file_path)
            else:
                filtered_content[file_path] = content

        return filtered_content, ignored_files

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

        # Reserve tokens for prompt overhead, tool calling, and response
        # Using 55% for file content leaves 45% for system prompt & tools
        available_tokens = int(context_limit * 0.55)
        
        # Try all files together first
        total_tokens = sum(estimate_tokens(c) for c in files_content.values())
        if total_tokens <= available_tokens:
            return [files_content]

        # Group by directory hierarchy
        batches: list[dict[str, str]] = []
        groups = group_files_by_directory(list(files_content.keys()))
        
        # Ensure skipped_files list exists
        if "skipped_files" not in self._scan_info:
            self._scan_info["skipped_files"] = []

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

    def _parse_issues_from_response(
        self,
        response: dict[str, Any],
        check_query: str,
        batch_idx: int,
    ) -> list[Issue]:
        """Parse issues from LLM response.

        Validates that file paths exist before including issues.
        Issues with non-existent file paths are logged and skipped.

        Args:
            response: Raw LLM response dictionary.
            check_query: The check query that was run.
            batch_idx: Current batch index (for logging).

        Returns:
            List of parsed Issue objects with valid file paths.
        """
        issues_data = response.get("issues", [])
        logger.info(f"LLM returned {len(issues_data)} issue(s) for batch {batch_idx + 1}")
        timestamp = datetime.now(timezone.utc)

        parsed_issues: list[Issue] = []
        skipped_count = 0
        for issue_data in issues_data:
            try:
                issue = Issue.from_llm_response(
                    issue_data,
                    check_query=check_query,
                    timestamp=timestamp,
                )
                
                # Validate that the file path is non-empty and the file exists
                if not issue.file_path or not issue.file_path.strip():
                    logger.warning(
                        f"Skipping issue with empty file path "
                        f"(LLM hallucination or malformed response)"
                    )
                    skipped_count += 1
                    continue
                
                file_path = self.config.target_directory / issue.file_path
                if not file_path.is_file():
                    logger.warning(
                        f"Skipping issue for non-existent file: {issue.file_path} "
                        f"(LLM hallucination or stale reference)"
                    )
                    skipped_count += 1
                    continue
                
                parsed_issues.append(issue)
                logger.debug(f"Parsed issue: {issue.file_path}:{issue.line_number}")
            except Exception as e:
                logger.warning(f"Failed to parse issue: {e}, data: {issue_data}")

        if skipped_count > 0:
            logger.info(f"Skipped {skipped_count} issue(s) with invalid or non-existent file paths")
        
        return parsed_issues

    def _run_check(
        self,
        check_query: str,
        batches: list[dict[str, str]],
    ) -> list[Issue]:
        """Run a single check against all batches with AI tool support.

        The LLM can request additional context via tools. This method handles
        iterative tool calling until the LLM provides a final answer.

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

            # Run check with tool support (may involve multiple rounds)
            batch_issues = self._run_check_with_tools(
                check_query=check_query,
                batch=batch,
                batch_idx=batch_idx,
            )
            all_issues.extend(batch_issues)

            # Immediately add batch issues to tracker and update output
            if batch_issues:
                new_count = self.issue_tracker.add_issues(batch_issues)
                if new_count > 0:
                    logger.info(f"Added {new_count} new issue(s) from batch {batch_idx + 1}")

            # Update output after each batch for immediate feedback
            self.output_generator.write(self.issue_tracker, self._scan_info)
            logger.info(f"Output updated after batch {batch_idx + 1}/{len(batches)}")

        return all_issues

    def _run_check_with_tools(
        self,
        check_query: str,
        batch: dict[str, str],
        batch_idx: int,
    ) -> list[Issue]:
        """Run a check with iterative tool calling support.

        This method handles the conversation loop:
        1. Send initial query with tools available
        2. If LLM requests tools, execute them
        3. Send tool results back to LLM
        4. Repeat until LLM provides final answer

        Args:
            check_query: The check query to run.
            batch: File batch content.
            batch_idx: Batch index for logging.

        Returns:
            List of issues found.
        """
        # Build initial user prompt
        user_prompt = build_user_prompt(check_query, batch)
        logger.info(f"Sending query to LLM: {check_query}")
        logger.debug(f"User prompt length: {len(user_prompt)} chars")

        # Conversation history for multi-turn interactions
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE},
            {"role": "user", "content": user_prompt},
        ]

        # Dynamic token tracking to prevent context overflow
        context_limit = self.llm_client.context_limit
        context_safety_threshold = 0.85  # Stop tool calls at 85% of limit
        max_context_tokens = int(context_limit * context_safety_threshold)
        
        # Track accumulated tokens
        accumulated_tokens = (
            estimate_tokens(SYSTEM_PROMPT_TEMPLATE) + 
            estimate_tokens(user_prompt)
        )
        logger.debug(f"Initial context usage: {accumulated_tokens} tokens ({accumulated_tokens * 100 // context_limit}% of {context_limit})")

        # Calculate dynamic iteration limit based on available context
        # Estimate average tokens per tool call (conservative estimate)
        avg_tool_result_tokens = 500  # Typical tool result size
        remaining_tokens = max_context_tokens - accumulated_tokens
        estimated_possible_iterations = max(1, remaining_tokens // avg_tool_result_tokens)
        
        # Cap at 50 to prevent endless loops, but use context-based limit if smaller
        max_tool_iterations = min(estimated_possible_iterations, 50)
        logger.debug(f"Max tool iterations set to {max_tool_iterations} (based on context: {estimated_possible_iterations}, capped at 50)")
        
        iteration = 0

        while iteration < max_tool_iterations:
            iteration += 1

            try:
                # Query LLM with tools available
                response = self.llm_client.query(
                    system_prompt=messages[0]["content"],
                    user_prompt=messages[-1]["content"],
                    max_retries=self.config.max_llm_retries,
                    tools=AI_TOOLS_SCHEMA,
                )

                # Check if LLM wants to use tools
                if "tool_calls" in response:
                    tool_calls = response["tool_calls"]
                    tool_names = [tc["tool_name"] for tc in tool_calls]
                    logger.info(f"LLM requested {len(tool_calls)} tool call(s): {', '.join(tool_names)} (iteration {iteration})")

                    # Execute all requested tools
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_name = tool_call["tool_name"]
                        arguments = tool_call["arguments"]

                        # Log tool execution with compact argument summary
                        args_summary = self._format_tool_args_for_log(tool_name, arguments)
                        logger.info(f"  → {tool_name}: {args_summary}")

                        logger.debug(f"Executing tool: {tool_name} with args: {arguments}")
                        result = self.tool_executor.execute_tool(tool_name, arguments)

                        # Format tool result for LLM
                        if result.success:
                            result_msg = f"Tool {tool_name} succeeded:\n{self._format_tool_result(result)}"
                            if result.warning:
                                logger.info(f"  ✓ {tool_name} completed with warning: {result.warning[:100]}...")
                                result_msg = f"{result.warning}\n\n{result_msg}"
                            else:
                                logger.info(f"  ✓ {tool_name} completed successfully")
                        else:
                            logger.info(f"  ✗ {tool_name} failed: {result.error}")
                            result_msg = f"Tool {tool_name} failed: {result.error}"

                        tool_results.append(result_msg)

                    # Add tool results to conversation
                    tool_results_message = "\n\n".join(tool_results)
                    
                    # Check if adding tool results would exceed context threshold
                    tool_results_tokens = estimate_tokens(tool_results_message)
                    new_total = accumulated_tokens + tool_results_tokens
                    context_usage_pct = new_total * 100 // context_limit
                    
                    logger.debug(f"Context usage after tools: {new_total} tokens ({context_usage_pct}% of {context_limit})")
                    
                    if new_total > max_context_tokens:
                        # Approaching context limit - ask LLM to finalize with current info
                        logger.warning(
                            f"Context approaching limit ({context_usage_pct}% used, threshold {int(context_safety_threshold * 100)}%). "
                            f"Requesting LLM to finalize analysis without further tool calls."
                        )
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Tool results:\n\n{tool_results_message}\n\n"
                                "IMPORTANT: Context limit reached. Do NOT request more tools. "
                                "Provide your FINAL analysis now with issues found based on available information."
                            ),
                        })
                        accumulated_tokens = new_total
                        
                        # Query without tools to force final answer
                        response = self.llm_client.query(
                            system_prompt=messages[0]["content"],
                            user_prompt=messages[-1]["content"],
                            max_retries=self.config.max_llm_retries,
                            tools=None,  # No tools - force final answer
                        )
                        return self._parse_issues_from_response(response, check_query, batch_idx)
                    
                    # Normal case - continue with tool results
                    messages.append({
                        "role": "user",
                        "content": f"Tool results:\n\n{tool_results_message}\n\nNow provide your final analysis with any issues found.",
                    })
                    accumulated_tokens = new_total

                    # Continue loop to get LLM's response after tool execution
                    continue

                else:
                    # LLM provided final answer (no more tool calls)
                    logger.debug(f"LLM provided final answer after {iteration} iteration(s)")
                    return self._parse_issues_from_response(response, check_query, batch_idx)

            except LLMClientError as e:
                logger.error(f"Check failed after retries: {e}")
                raise

        # Max iterations reached
        logger.warning(f"Max tool iterations ({max_tool_iterations}) reached, using last response")
        return []

    def _format_tool_args_for_log(self, tool_name: str, arguments: dict) -> str:
        """Format tool arguments for compact logging.
        
        Creates a human-readable summary of tool arguments without
        hardcoding specific tool names.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool arguments dictionary.

        Returns:
            Compact string representation of arguments.
        """
        if not arguments:
            return "(no args)"
        
        # Common argument names that are good for logging
        path_keys = ['file_path', 'directory_path', 'path']
        search_keys = ['patterns', 'pattern', 'symbol', 'query']
        
        parts = []
        
        # Prioritize path-like arguments
        for key in path_keys:
            if key in arguments:
                parts.append(str(arguments[key]))
                break
        
        # Add search/pattern arguments
        for key in search_keys:
            if key in arguments:
                val = arguments[key]
                if isinstance(val, list):
                    val = ', '.join(str(v) for v in val[:3])
                parts.append(f"'{val}'")
                break
        
        # Add line range if present
        start = arguments.get('start_line')
        end = arguments.get('end_line')
        if start and end:
            parts.append(f"lines {start}-{end}")
        elif start:
            parts.append(f"from line {start}")
        
        return ' '.join(parts) if parts else str(arguments)

    def _format_tool_result(self, result) -> str:
        """Format a tool result for presentation to the LLM.

        Args:
            result: ToolResult object.

        Returns:
            Formatted string representation.
        """
        import json

        if isinstance(result.data, dict):
            return json.dumps(result.data, indent=2)
        elif isinstance(result.data, list):
            return json.dumps(result.data, indent=2)
        else:
            return str(result.data)
