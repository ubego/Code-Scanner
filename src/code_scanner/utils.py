"""Utility functions for the code scanner."""

import logging
import os
import sys
from pathlib import Path

# Known binary file extensions
BINARY_EXTENSIONS = frozenset({
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp", ".tiff",
    # Audio/Video
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac", ".ogg", ".webm",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    # Compiled/Binary
    ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".a", ".lib", ".pyc", ".pyo",
    ".class", ".jar", ".war", ".ear",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Databases
    ".db", ".sqlite", ".sqlite3",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Other binary
    ".bin", ".dat", ".iso", ".img",
})

# Characters per token estimate (conservative)
CHARS_PER_TOKEN = 4

logger = logging.getLogger(__name__)


def is_binary_file(file_path: Path) -> bool:
    """Check if a file is binary based on extension and content.

    Args:
        file_path: Path to the file to check.

    Returns:
        True if the file is binary, False otherwise.
    """
    # Check extension first (fast path)
    if file_path.suffix.lower() in BINARY_EXTENSIONS:
        return True

    # Check file content for null bytes
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            if b"\x00" in chunk:
                return True
    except (OSError, IOError):
        # If we can't read the file, assume it's not binary
        return False

    return False


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses a simple character-based approximation.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    return len(text) // CHARS_PER_TOKEN


def read_file_content(file_path: Path) -> str | None:
    """Read file content as text, returning None for binary files.

    Args:
        file_path: Path to the file to read.

    Returns:
        File content as string, or None if binary/unreadable.
    """
    if is_binary_file(file_path):
        return None

    try:
        with open(file_path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        # Try with fallback encoding
        try:
            with open(file_path, encoding="latin-1") as f:
                return f.read()
        except Exception:
            return None
    except (OSError, IOError) as e:
        logger.warning(f"Could not read file {file_path}: {e}")
        return None


def get_line_at(content: str, line_number: int) -> str:
    """Get a specific line from file content.

    Args:
        content: The full file content.
        line_number: 1-based line number.

    Returns:
        The line content, or empty string if line doesn't exist.
    """
    lines = content.splitlines()
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1]
    return ""


def get_context_lines(content: str, line_number: int, context: int = 3) -> str:
    """Get lines around a specific line for context.

    Args:
        content: The full file content.
        line_number: 1-based line number.
        context: Number of lines before and after.

    Returns:
        The context lines as a string.
    """
    lines = content.splitlines()
    start = max(0, line_number - 1 - context)
    end = min(len(lines), line_number + context)
    return "\n".join(lines[start:end])


def setup_logging(log_file: Path, console_level: int = logging.INFO) -> None:
    """Set up logging to both console and file.

    Args:
        log_file: Path to the log file.
        console_level: Logging level for console output.
    """
    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def group_files_by_directory(files: list[str]) -> dict[str, list[str]]:
    """Group files by their parent directory.

    Groups are ordered by directory depth (deepest first) to enable
    proper batching from leaves to root.

    Args:
        files: List of file paths.

    Returns:
        Dictionary mapping directory paths to lists of files.
    """
    groups: dict[str, list[str]] = {}

    for file_path in files:
        parent = str(Path(file_path).parent)
        if parent not in groups:
            groups[parent] = []
        groups[parent].append(file_path)

    # Sort by depth (deepest first)
    sorted_groups = dict(
        sorted(groups.items(), key=lambda x: -x[0].count(os.sep))
    )

    return sorted_groups


def is_interactive() -> bool:
    """Check if running in an interactive terminal.

    Returns:
        True if stdin is a TTY, False otherwise.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_yes_no(message: str, default: bool = False) -> bool:
    """Prompt user for yes/no confirmation.

    Args:
        message: The prompt message.
        default: Default value if user just presses Enter.

    Returns:
        True for yes, False for no.
    """
    if not is_interactive():
        raise RuntimeError("Cannot prompt in non-interactive mode")

    suffix = " [Y/n] " if default else " [y/N] "
    response = input(message + suffix).strip().lower()

    if not response:
        return default

    return response in ("y", "yes")
