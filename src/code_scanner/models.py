"""Data models for the code scanner."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class IssueStatus(Enum):
    """Status of a detected issue."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


@dataclass
class Issue:
    """Represents a single issue detected by the scanner."""

    file_path: str
    line_number: int
    description: str
    suggested_fix: str
    check_query: str
    timestamp: datetime
    status: IssueStatus = IssueStatus.OPEN
    code_snippet: str = ""

    def matches(self, other: "Issue", fuzzy_threshold: float = 0.8) -> bool:
        """Check if this issue matches another issue for deduplication.

        Issues match if they have the same file and similar code pattern/description.
        Line numbers are NOT used for matching as code can move.
        
        Uses fuzzy matching with Levenshtein distance for more robust comparison
        that handles minor code changes.

        Args:
            other: The other issue to compare against.
            fuzzy_threshold: Minimum similarity ratio (0.0 to 1.0) to consider a match.
                           Default 0.8 (80% similarity).

        Returns:
            True if issues match (should be deduplicated).
        """
        if self.file_path != other.file_path:
            return False

        # Normalize whitespace for comparison
        self_snippet = _normalize_whitespace(self.code_snippet)
        other_snippet = _normalize_whitespace(other.code_snippet)

        self_desc = _normalize_whitespace(self.description)
        other_desc = _normalize_whitespace(other.description)

        # Exact match first (fast path)
        if self_snippet == other_snippet or self_desc == other_desc:
            return True

        # Fuzzy match for code snippets using similarity ratio
        if self_snippet and other_snippet:
            snippet_similarity = _similarity_ratio(self_snippet, other_snippet)
            if snippet_similarity >= fuzzy_threshold:
                return True

        # Fuzzy match for descriptions
        if self_desc and other_desc:
            desc_similarity = _similarity_ratio(self_desc, other_desc)
            if desc_similarity >= fuzzy_threshold:
                return True

        return False

    @classmethod
    def from_llm_response(
        cls,
        data: dict,
        check_query: str,
        timestamp: Optional[datetime] = None,
    ) -> "Issue":
        """Create an Issue from LLM response data."""
        # Handle None values from LLM - use 'or' to fall back when key exists but value is None
        line_num = data.get("line_number") or data.get("line") or 0
        return cls(
            file_path=data.get("file") or data.get("file_path") or "",
            line_number=int(line_num),
            description=data.get("description") or "",
            suggested_fix=data.get("suggested_fix") or data.get("fix") or "",
            check_query=check_query,
            timestamp=timestamp or datetime.now(timezone.utc),
            code_snippet=data.get("code_snippet") or "",
        )


@dataclass
class ChangedFile:
    """Represents a file with uncommitted changes."""

    path: str
    status: str  # 'staged', 'unstaged', 'untracked', 'deleted'
    content: Optional[str] = None

    @property
    def is_deleted(self) -> bool:
        """Check if file is deleted."""
        return self.status == "deleted"


@dataclass
class GitState:
    """Current state of Git repository."""

    changed_files: list[ChangedFile] = field(default_factory=list)
    is_merging: bool = False
    is_rebasing: bool = False

    @property
    def is_conflict_resolution_in_progress(self) -> bool:
        """Check if merge/rebase conflict resolution is in progress."""
        return self.is_merging or self.is_rebasing

    @property
    def has_changes(self) -> bool:
        """Check if there are any uncommitted changes."""
        return len(self.changed_files) > 0


@dataclass
class LLMConfig:
    """Configuration for LLM backend connection.
    
    Supports both LM Studio and Ollama backends.
    The 'backend' field is required and must be explicitly set.
    """

    backend: str  # Required: "lm-studio" or "ollama"
    host: str  # Required: no default
    port: int  # Required: no default
    model: Optional[str] = None  # Required for Ollama, optional for LM Studio
    timeout: int = 120
    context_limit: Optional[int] = None  # Manual override for context window size

    # Valid backend values
    VALID_BACKENDS = ("lm-studio", "ollama")

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.backend not in self.VALID_BACKENDS:
            raise ValueError(
                f"Invalid backend '{self.backend}'. "
                f"Must be one of: {', '.join(self.VALID_BACKENDS)}"
            )
        
        if self.backend == "ollama" and not self.model:
            raise ValueError(
                "Ollama backend requires 'model' to be specified.\n"
                "Example: model = \"qwen3:4b\""
            )

    @property
    def base_url(self) -> str:
        """Get the base URL for LLM API."""
        if self.backend == "lm-studio":
            return f"http://{self.host}:{self.port}/v1"
        else:  # ollama
            return f"http://{self.host}:{self.port}"


@dataclass
class CheckGroup:
    """A group of checks that apply to files matching a pattern."""

    pattern: str  # Glob pattern like "*.cpp, *.h" or "*" for all files
    checks: list[str]  # List of checks to run

    def matches_file(self, file_path: str) -> bool:
        """Check if the file matches this check group's pattern.

        Supports:
        - File extension patterns: *.cpp, *.h
        - Wildcard: * matches all files
        - Directory patterns: /*dirname*/ matches files in directories containing 'dirname'

        Args:
            file_path: The file path to check.

        Returns:
            True if the file matches the pattern.
        """
        from fnmatch import fnmatch

        # Split patterns by comma and strip whitespace
        patterns = [p.strip() for p in self.pattern.split(",")]

        # Get just the filename for matching
        filename = file_path.split("/")[-1] if "/" in file_path else file_path

        # Check if any pattern matches
        for pattern in patterns:
            # Check for directory pattern: /*dirname*/
            if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 2:
                dir_pattern = pattern[1:-1]  # Remove leading and trailing /
                # Check if any directory component matches the pattern
                path_parts = file_path.replace("\\", "/").split("/")
                for part in path_parts[:-1]:  # Exclude the filename itself
                    if fnmatch(part, dir_pattern):
                        return True
            elif fnmatch(filename, pattern) or fnmatch(file_path, pattern):
                return True

        return False


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text for comparison.

    Collapses multiple whitespace characters into single spaces
    and strips leading/trailing whitespace.
    """
    return " ".join(text.split())


def _similarity_ratio(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings using SequenceMatcher.
    
    This uses Python's built-in difflib for Levenshtein-like distance calculation.
    
    Args:
        s1: First string.
        s2: Second string.
        
    Returns:
        Similarity ratio between 0.0 (completely different) and 1.0 (identical).
    """
    from difflib import SequenceMatcher
    return SequenceMatcher(None, s1, s2).ratio()
