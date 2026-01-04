"""Tests for utility functions."""

import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from code_scanner.utils import (
    is_binary_file,
    estimate_tokens,
    read_file_content,
    get_line_at,
    get_context_lines,
    setup_logging,
    group_files_by_directory,
    CHARS_PER_TOKEN,
    Colors,
    ColoredFormatter,
)


class TestIsBinaryFile:
    """Tests for is_binary_file function."""

    def test_binary_extension_detected(self, tmp_path):
        """Binary file detected by extension."""
        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"PNG data")
        assert is_binary_file(binary_file) is True

    def test_text_file_not_binary(self, tmp_path):
        """Text file is not binary."""
        text_file = tmp_path / "code.py"
        text_file.write_text("print('hello')")
        assert is_binary_file(text_file) is False

    def test_null_bytes_detected_as_binary(self, tmp_path):
        """File with null bytes detected as binary."""
        binary_file = tmp_path / "data.txt"
        binary_file.write_bytes(b"text\x00with\x00nulls")
        assert is_binary_file(binary_file) is True

    def test_unreadable_file_not_binary(self, tmp_path):
        """Unreadable file defaults to not binary."""
        fake_path = tmp_path / "nonexistent.txt"
        assert is_binary_file(fake_path) is False

    def test_various_binary_extensions(self, tmp_path):
        """Test various binary extensions."""
        extensions = [".exe", ".dll", ".pdf", ".zip", ".jpg", ".mp3"]
        for ext in extensions:
            binary_file = tmp_path / f"file{ext}"
            binary_file.write_bytes(b"data")
            assert is_binary_file(binary_file) is True, f"Extension {ext} should be binary"


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self):
        """Empty string has zero tokens."""
        assert estimate_tokens("") == 0

    def test_short_string(self):
        """Short string token estimation."""
        text = "hello"  # 5 chars
        assert estimate_tokens(text) == 5 // CHARS_PER_TOKEN

    def test_long_string(self):
        """Long string token estimation."""
        text = "a" * 1000
        assert estimate_tokens(text) == 1000 // CHARS_PER_TOKEN


class TestReadFileContent:
    """Tests for read_file_content function."""

    def test_read_text_file(self, tmp_path):
        """Read valid text file."""
        text_file = tmp_path / "test.py"
        content = "def hello():\n    pass"
        text_file.write_text(content)
        assert read_file_content(text_file) == content

    def test_binary_file_returns_none(self, tmp_path):
        """Binary file returns None."""
        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")
        assert read_file_content(binary_file) is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        """Nonexistent file returns None."""
        fake_path = tmp_path / "nonexistent.txt"
        assert read_file_content(fake_path) is None

    def test_unicode_decode_error_fallback(self, tmp_path):
        """Falls back to latin-1 on unicode decode error."""
        file_path = tmp_path / "latin1.txt"
        # Write bytes that are valid latin-1 but not utf-8
        file_path.write_bytes(b"caf\xe9")  # café with latin-1 é
        result = read_file_content(file_path)
        assert result is not None
        assert "caf" in result


class TestGetLineAt:
    """Tests for get_line_at function."""

    def test_get_first_line(self):
        """Get first line."""
        content = "line1\nline2\nline3"
        assert get_line_at(content, 1) == "line1"

    def test_get_middle_line(self):
        """Get middle line."""
        content = "line1\nline2\nline3"
        assert get_line_at(content, 2) == "line2"

    def test_get_last_line(self):
        """Get last line."""
        content = "line1\nline2\nline3"
        assert get_line_at(content, 3) == "line3"

    def test_line_number_too_high(self):
        """Line number out of range returns empty string."""
        content = "line1\nline2"
        assert get_line_at(content, 10) == ""

    def test_line_number_zero(self):
        """Line number zero returns empty string."""
        content = "line1"
        assert get_line_at(content, 0) == ""

    def test_negative_line_number(self):
        """Negative line number returns empty string."""
        content = "line1"
        assert get_line_at(content, -1) == ""


class TestGetContextLines:
    """Tests for get_context_lines function."""

    def test_get_context_middle(self):
        """Get context around middle line."""
        content = "1\n2\n3\n4\n5\n6\n7"
        result = get_context_lines(content, 4, context=2)
        assert result == "2\n3\n4\n5\n6"

    def test_get_context_at_start(self):
        """Get context at file start."""
        content = "1\n2\n3\n4\n5"
        result = get_context_lines(content, 1, context=2)
        assert result == "1\n2\n3"

    def test_get_context_at_end(self):
        """Get context at file end."""
        content = "1\n2\n3\n4\n5"
        result = get_context_lines(content, 5, context=2)
        assert result == "3\n4\n5"


class TestGroupFilesByDirectory:
    """Tests for group_files_by_directory function."""

    def test_single_directory(self):
        """Files in single directory."""
        files = ["src/a.py", "src/b.py"]
        result = group_files_by_directory(files)
        assert "src" in result
        assert len(result["src"]) == 2

    def test_multiple_directories(self):
        """Files in multiple directories."""
        files = ["src/a.py", "tests/b.py"]
        result = group_files_by_directory(files)
        assert "src" in result
        assert "tests" in result

    def test_nested_directories_sorted_by_depth(self):
        """Nested directories sorted deepest first."""
        files = ["src/a.py", "src/utils/b.py", "src/utils/helpers/c.py"]
        result = group_files_by_directory(files)
        keys = list(result.keys())
        # Deepest first
        assert keys[0].count(os.sep) >= keys[-1].count(os.sep)

    def test_empty_list(self):
        """Empty file list."""
        result = group_files_by_directory([])
        assert result == {}




class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_creates_log_file(self, tmp_path):
        """Creates log file."""
        log_file = tmp_path / "test.log"
        
        # Clear existing handlers
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        
        setup_logging(log_file)
        
        # Log something
        logger = logging.getLogger("test")
        logger.info("Test message")
        
        # Check file was created
        assert log_file.exists()
        
        # Cleanup handlers
        for handler in root.handlers[:]:
            handler.close()
            root.removeHandler(handler)

    def test_suppresses_third_party_logs(self, tmp_path):
        """Suppresses verbose third-party logs."""
        log_file = tmp_path / "test.log"
        
        # Clear existing handlers
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        
        setup_logging(log_file)
        
        # Check that httpx and openai loggers are suppressed
        assert logging.getLogger("openai._base_client").level == logging.WARNING
        assert logging.getLogger("httpx").level == logging.WARNING
        
        # Cleanup
        for handler in root.handlers[:]:
            handler.close()
            root.removeHandler(handler)


class TestColoredFormatter:
    """Tests for ColoredFormatter class."""

    def test_colors_class_has_required_attributes(self):
        """Colors class has all required ANSI codes."""
        assert hasattr(Colors, "RESET")
        assert hasattr(Colors, "BOLD")
        assert hasattr(Colors, "RED")
        assert hasattr(Colors, "GREEN")
        assert hasattr(Colors, "YELLOW")
        assert hasattr(Colors, "BLUE")
        assert hasattr(Colors, "CYAN")
        
        # Verify they are ANSI escape codes
        assert Colors.RESET == "\033[0m"
        assert "\033[" in Colors.RED

    def test_formatter_with_colors_enabled(self):
        """Formatter adds colors when enabled."""
        formatter = ColoredFormatter(use_colors=True)
        # Force colors even in non-TTY environment
        formatter.use_colors = True
        
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        formatted = formatter.format(record)
        
        # Should contain ANSI codes
        assert "\033[" in formatted
        assert Colors.RESET in formatted
        assert "Test message" in formatted

    def test_formatter_with_colors_disabled(self):
        """Formatter does not add colors when disabled."""
        formatter = ColoredFormatter(use_colors=False)
        
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        formatted = formatter.format(record)
        
        # Should not contain ANSI codes
        assert "\033[" not in formatted
        assert "Test message" in formatted

    def test_formatter_different_levels_have_different_colors(self):
        """Different log levels produce different colored output."""
        formatter = ColoredFormatter(use_colors=True)
        formatter.use_colors = True
        
        levels = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR]
        formatted_outputs = []
        
        for level in levels:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="test.py",
                lineno=10,
                msg="Test",
                args=(),
                exc_info=None,
            )
            formatted_outputs.append(formatter.format(record))
        
        # Each level should produce different output (different colors)
        # Check that at least some outputs differ
        unique_outputs = set(formatted_outputs)
        assert len(unique_outputs) > 1

    @patch.dict(os.environ, {"NO_COLOR": "1"})
    def test_no_color_env_disables_colors(self):
        """NO_COLOR environment variable disables colors."""
        formatter = ColoredFormatter()
        assert formatter.use_colors is False

    @patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=False)
    def test_force_color_env_enables_colors(self):
        """FORCE_COLOR environment variable enables colors."""
        # Clear NO_COLOR if set and mock TTY
        with patch.dict(os.environ, {"NO_COLOR": ""}, clear=False):
            with patch.object(sys.stderr, "isatty", return_value=True):
                formatter = ColoredFormatter()
                # FORCE_COLOR should enable colors
                assert formatter._supports_color() is True

    def test_supports_color_returns_false_for_non_tty(self):
        """_supports_color returns False when stderr is not a TTY."""
        with patch.object(sys.stderr, "isatty", return_value=False):
            with patch.dict(os.environ, {"FORCE_COLOR": ""}, clear=False):
                result = ColoredFormatter._supports_color()
                assert result is False
