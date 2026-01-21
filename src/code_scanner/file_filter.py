"""Unified file filtering for the code scanner.

Combines all file exclusion logic in one place:
- Scanner output files (code_scanner_results.md, .log, .bak)
- Gitignore patterns (parsed from .gitignore)
- Config ignore patterns (*.md, *.txt, etc.)

This eliminates redundant filtering and subprocess calls.
"""

import fnmatch
import logging
from pathlib import Path
from typing import Optional

try:
    import pathspec
    HAS_PATHSPEC = True
except ImportError:
    HAS_PATHSPEC = False

logger = logging.getLogger(__name__)


class FileFilter:
    """Unified file filter combining all exclusion rules.
    
    Provides O(1) or O(patterns) filtering without subprocess calls.
    """

    def __init__(
        self,
        repo_path: Path,
        scanner_files: Optional[set[str]] = None,
        config_ignore_patterns: Optional[list[str]] = None,
        load_gitignore: bool = True,
    ):
        """Initialize the file filter.

        Args:
            repo_path: Path to the repository root.
            scanner_files: Set of scanner output files to always skip.
                          e.g., {"code_scanner_results.md", "code_scanner.log"}
            config_ignore_patterns: List of glob patterns from config.
                          e.g., ["*.md", "*.txt", "*.json"]
            load_gitignore: Whether to load .gitignore patterns.
        """
        self.repo_path = repo_path
        self.scanner_files = scanner_files or set()
        self.config_patterns = config_ignore_patterns or []
        
        # Load gitignore patterns for in-memory matching
        self._gitignore_spec: Optional["pathspec.PathSpec"] = None
        if load_gitignore:
            self._gitignore_spec = self._load_gitignore()

    def _load_gitignore(self) -> Optional["pathspec.PathSpec"]:
        """Load and parse .gitignore patterns.
        
        Returns:
            PathSpec object for matching, or None if pathspec not available.
        """
        if not HAS_PATHSPEC:
            logger.debug("pathspec not installed, gitignore filtering disabled")
            return None
            
        patterns: list[str] = []
        
        # Load root .gitignore
        gitignore = self.repo_path / ".gitignore"
        if gitignore.exists():
            try:
                patterns.extend(gitignore.read_text().splitlines())
            except OSError as e:
                logger.warning(f"Could not read .gitignore: {e}")
        
        # Also check for nested .gitignore files in common locations
        # (simplified - full git behavior is more complex)
        
        if not patterns:
            return None
            
        try:
            return pathspec.PathSpec.from_lines("gitignore", patterns)
        except Exception as e:
            logger.warning(f"Could not parse .gitignore patterns: {e}")
            return None

    def should_skip(self, path: str) -> tuple[bool, str]:
        """Check if a file should be skipped.
        
        Checks all exclusion rules in order of cheapest to most expensive:
        1. Scanner files (set lookup - O(1))
        2. Config ignore patterns (fnmatch - O(patterns))
        3. Gitignore patterns (pathspec - O(patterns))
        
        Args:
            path: Relative file path from repository root.
            
        Returns:
            Tuple of (should_skip, reason).
            reason is empty string if file should not be skipped.
        """
        # 1. Check scanner files (O(1) set lookup)
        if path in self.scanner_files:
            return True, "scanner_file"
        
        # Also check if basename matches (for paths like "subdir/results.md")
        basename = Path(path).name
        if basename in self.scanner_files:
            return True, "scanner_file"
        
        # 2. Check config ignore patterns (O(patterns) fnmatch)
        for pattern in self.config_patterns:
            # Handle directory patterns like /*tests*/ or /*vendor*/
            if pattern.startswith("/*") and pattern.endswith("/"):
                # Extract directory name pattern (e.g., "tests*" from "/*tests*/")
                # Remove "/*" prefix and "/" suffix to get the fnmatch pattern
                dir_pattern = pattern[2:-1]  # "/*tests*/" -> "tests*"
                # Check if any path component matches the directory pattern
                # Use fnmatch to support wildcards like /*cmake-build-*/
                for part in path.split("/"):
                    if fnmatch.fnmatch(part, dir_pattern):
                        return True, f"config_pattern:{pattern}"
                continue
            
            # fnmatch on basename for simple patterns like "*.md"
            if fnmatch.fnmatch(basename, pattern):
                return True, f"config_pattern:{pattern}"
            # Also try full path match for patterns like "docs/*"
            if fnmatch.fnmatch(path, pattern):
                return True, f"config_pattern:{pattern}"
        
        # 3. Check gitignore patterns (O(patterns) pathspec)
        if self._gitignore_spec is not None:
            if self._gitignore_spec.match_file(path):
                return True, "gitignore"
        
        return False, ""

    def filter_paths(self, paths: list[str]) -> tuple[list[str], dict[str, str]]:
        """Filter a list of paths, returning kept and skipped.
        
        Args:
            paths: List of relative file paths.
            
        Returns:
            Tuple of (kept_paths, skipped_dict).
            skipped_dict maps path -> skip reason.
        """
        kept: list[str] = []
        skipped: dict[str, str] = {}
        
        for path in paths:
            should_skip, reason = self.should_skip(path)
            if should_skip:
                skipped[path] = reason
            else:
                kept.append(path)
        
        return kept, skipped

    def is_gitignored(self, path: str) -> bool:
        """Check if a path is gitignored (in-memory check).
        
        This is a fast replacement for 'git check-ignore' subprocess calls.
        
        Args:
            path: Relative file path.
            
        Returns:
            True if the file matches gitignore patterns.
        """
        if self._gitignore_spec is not None:
            return self._gitignore_spec.match_file(path)
        return False

    def add_scanner_files(self, *files: str) -> None:
        """Add additional scanner files to exclude.
        
        Args:
            files: File paths to add to exclusion set.
        """
        self.scanner_files.update(files)

    def add_config_patterns(self, *patterns: str) -> None:
        """Add additional config patterns to exclude.
        
        Args:
            patterns: Glob patterns to add.
        """
        self.config_patterns.extend(patterns)

    def reload_gitignore(self) -> None:
        """Reload .gitignore patterns from disk.
        
        Call this if .gitignore has changed.
        """
        self._gitignore_spec = self._load_gitignore()
