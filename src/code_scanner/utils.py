"""Utility functions for the code scanner."""

import logging
import os
import sys
from pathlib import Path

# ANSI color codes for terminal output
class Colors:
    """ANSI color codes for terminal coloring."""
    
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Foreground colors
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    
    # Bright foreground colors
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_CYAN = "\033[96m"


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to log messages based on level."""
    
    # Level-specific colors
    LEVEL_COLORS = {
        logging.DEBUG: Colors.GRAY,
        logging.INFO: Colors.BRIGHT_CYAN,
        logging.WARNING: Colors.BRIGHT_YELLOW,
        logging.ERROR: Colors.BRIGHT_RED,
        logging.CRITICAL: Colors.BOLD + Colors.BRIGHT_RED,
    }
    
    # Level name colors (for the level label itself)
    LEVEL_NAME_COLORS = {
        logging.DEBUG: Colors.GRAY,
        logging.INFO: Colors.GREEN,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.RED,
        logging.CRITICAL: Colors.BOLD + Colors.RED,
    }
    
    def __init__(self, fmt: str | None = None, datefmt: str | None = None, use_colors: bool = True):
        """Initialize the colored formatter.
        
        Args:
            fmt: Log message format string.
            datefmt: Date format string.
            use_colors: Whether to use colors (auto-detected if terminal supports it).
        """
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors and self._supports_color()
    
    @staticmethod
    def _supports_color() -> bool:
        """Check if the terminal supports colors."""
        # Check if output is a TTY
        if not hasattr(sys.stderr, "isatty") or not sys.stderr.isatty():
            return False
        
        # Check for NO_COLOR environment variable (standard for disabling colors)
        if os.environ.get("NO_COLOR"):
            return False
        
        # Check for FORCE_COLOR environment variable
        if os.environ.get("FORCE_COLOR"):
            return True
        
        # Check terminal type
        term = os.environ.get("TERM", "")
        if term == "dumb":
            return False
        
        # Most modern terminals support colors
        return True
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with colors.
        
        Args:
            record: The log record to format.
            
        Returns:
            Formatted and colored log string.
        """
        if not self.use_colors:
            return super().format(record)
        
        # Get colors for this level
        level_color = self.LEVEL_COLORS.get(record.levelno, "")
        level_name_color = self.LEVEL_NAME_COLORS.get(record.levelno, "")
        
        # Color the timestamp
        original_asctime = self.formatTime(record, self.datefmt)
        colored_asctime = f"{Colors.DIM}{original_asctime}{Colors.RESET}"
        
        # Color the level name
        colored_levelname = f"{level_name_color}{record.levelname:8}{Colors.RESET}"
        
        # Color the logger name
        colored_name = f"{Colors.BLUE}{record.name}{Colors.RESET}"
        
        # Color the message
        colored_message = f"{level_color}{record.getMessage()}{Colors.RESET}"
        
        # Build the formatted string
        return f"{colored_asctime} - {colored_name} - {colored_levelname} - {colored_message}"


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
    # Create formatter for file (no colors)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Create colored formatter for console
    console_formatter = ColoredFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler (with colors)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (no colors)
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Suppress verbose logs from third-party libraries
    # These retry messages from OpenAI client are confusing without context
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


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

