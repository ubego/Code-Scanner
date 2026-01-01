"""Data models for the code scanner."""

from dataclasses import dataclass, field
from datetime import datetime
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

    def matches(self, other: "Issue") -> bool:
        """Check if this issue matches another issue for deduplication.

        Issues match if they have the same file and similar code pattern/description.
        Line numbers are NOT used for matching as code can move.
        """
        if self.file_path != other.file_path:
            return False

        # Normalize whitespace for comparison
        self_snippet = _normalize_whitespace(self.code_snippet)
        other_snippet = _normalize_whitespace(other.code_snippet)

        self_desc = _normalize_whitespace(self.description)
        other_desc = _normalize_whitespace(other.description)

        # Match if code snippets are similar OR descriptions are similar
        return self_snippet == other_snippet or self_desc == other_desc

    def to_dict(self) -> dict:
        """Convert issue to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "description": self.description,
            "suggested_fix": self.suggested_fix,
            "check_query": self.check_query,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "code_snippet": self.code_snippet,
        }

    @classmethod
    def from_llm_response(
        cls,
        data: dict,
        check_query: str,
        timestamp: Optional[datetime] = None,
    ) -> "Issue":
        """Create an Issue from LLM response data."""
        return cls(
            file_path=data.get("file", data.get("file_path", "")),
            line_number=int(data.get("line_number", data.get("line", 0))),
            description=data.get("description", ""),
            suggested_fix=data.get("suggested_fix", data.get("fix", "")),
            check_query=check_query,
            timestamp=timestamp or datetime.now(),
            code_snippet=data.get("code_snippet", ""),
        )


@dataclass
class ScanResult:
    """Result of a single scan cycle."""

    issues: list[Issue] = field(default_factory=list)
    files_scanned: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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
    current_commit: str = ""

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
    """Configuration for LM Studio connection."""

    host: str = "localhost"
    port: int = 1234
    model: Optional[str] = None
    timeout: int = 120

    @property
    def base_url(self) -> str:
        """Get the base URL for LM Studio API."""
        return f"http://{self.host}:{self.port}/v1"


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text for comparison.

    Collapses multiple whitespace characters into single spaces
    and strips leading/trailing whitespace.
    """
    return " ".join(text.split())
