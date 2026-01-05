"""Unit tests for AI tools (context expansion via function calling)."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

from code_scanner.ai_tools import (
    AIToolExecutor,
    ToolResult,
    AI_TOOLS_SCHEMA,
    DEFAULT_CHUNK_SIZE_TOKENS,
)
from code_scanner.utils import read_file_content


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository structure for testing."""
    # Create directory structure
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    utils_dir = src_dir / "utils"
    utils_dir.mkdir()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    # Create sample files
    (src_dir / "main.py").write_text(
        "def main():\n    print('Hello')\n    calculate_total()\n"
    )
    (utils_dir / "math.py").write_text(
        "def calculate_total(items):\n    return sum(items)\n\n"
        "def calculate_average(items):\n    return sum(items) / len(items)\n"
    )
    (utils_dir / "helpers.py").write_text(
        "class Helper:\n    def __init__(self):\n        pass\n"
    )
    (tests_dir / "test_main.py").write_text(
        "from src.main import main\n\ndef test_main():\n    main()\n"
    )

    # Create a binary file
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # Create hidden directory (should be skipped)
    hidden_dir = tmp_path / ".git"
    hidden_dir.mkdir()
    (hidden_dir / "config").write_text("gitconfig")

    return tmp_path


class TestAIToolExecutor:
    """Test suite for AIToolExecutor."""

    def test_init(self, temp_repo):
        """Test executor initialization."""
        executor = AIToolExecutor(
            target_directory=temp_repo,
            context_limit=8192,
        )

        assert executor.target_directory == temp_repo
        assert executor.context_limit == 8192
        assert executor.chunk_size == min(DEFAULT_CHUNK_SIZE_TOKENS, 8192 // 4)

    def test_execute_unknown_tool(self, temp_repo):
        """Test executing an unknown tool."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool("unknown_tool", {})

        assert not result.success
        assert "Unknown tool" in result.error

    def test_search_text_missing_patterns(self, temp_repo):
        """Test search_text with missing patterns."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool("search_text", {})

        assert not result.success
        assert "pattern" in result.error.lower()

    def test_search_text_single_pattern(self, temp_repo):
        """Test searching for a single pattern."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "calculate_total"},
        )

        assert result.success
        assert "calculate_total" in result.data["patterns_searched"]
        assert result.data["total_matches"] >= 2  # Definition + usage

        matches = result.data["matches_by_pattern"].get("calculate_total", [])
        # Should find in main.py (usage) and math.py (definition)
        file_paths = [m["file"] for m in matches]
        assert any("main.py" in fp for fp in file_paths)
        assert any("math.py" in fp for fp in file_paths)

    def test_search_text_multiple_patterns(self, temp_repo):
        """Test searching for multiple patterns at once."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": ["Helper", "calculate_total"]},
        )

        assert result.success
        assert len(result.data["patterns_searched"]) == 2
        # Should find matches for both patterns
        assert "Helper" in result.data["matches_by_pattern"]
        assert "calculate_total" in result.data["matches_by_pattern"]

    def test_search_text_no_matches(self, temp_repo):
        """Test searching when nothing matches."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "nonexistent_function"},
        )

        assert result.success
        assert result.data["total_matches"] == 0

    def test_search_text_skips_binary_files(self, temp_repo):
        """Test that binary files are skipped during search."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Search for something that might be in binary
        result = executor.execute_tool(
            "search_text",
            {"patterns": "PNG"},
        )

        # Should not crash, binary files should be skipped
        assert result.success

    def test_search_text_skips_hidden_dirs(self, temp_repo):
        """Test that hidden directories are skipped."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "gitconfig"},
        )

        # Should not find anything in .git directory
        assert result.success
        assert result.data["total_matches"] == 0

    def test_search_text_partial_results_warning(self, temp_repo):
        """Test warning when results are truncated."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Create many files with matches
        for i in range(100):
            (temp_repo / f"file_{i}.py").write_text(f"def calculate_total():\n    pass\n")

        result = executor.execute_tool(
            "search_text",
            {"patterns": "calculate_total"},
        )

        assert result.success
        # Should truncate to 50 results per page
        matches = result.data["matches_by_pattern"].get("calculate_total", [])
        assert result.data["total_matches"] > 50
        assert result.warning is not None
        assert "PARTIAL RESULTS" in result.warning

    def test_search_text_case_insensitive(self, temp_repo):
        """Test case-insensitive search (default)."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "HELPER", "case_sensitive": False},
        )

        assert result.success
        assert result.data["total_matches"] >= 1

    def test_search_text_case_sensitive(self, temp_repo):
        """Test case-sensitive search."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "HELPER", "case_sensitive": True},
        )

        assert result.success
        # "HELPER" in all caps shouldn't match "Helper"
        assert result.data["total_matches"] == 0

    def test_search_text_substring_match(self, temp_repo):
        """Test substring matching (match_whole_word=False)."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "calc", "match_whole_word": False},
        )

        assert result.success
        # Should match "calculate_total" as substring
        assert result.data["total_matches"] >= 1

    def test_search_text_file_pattern_filter(self, temp_repo):
        """Test file pattern filtering."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "def", "file_pattern": "*.py"},
        )

        assert result.success
        # Should only find in .py files
        matches = []
        for pattern_matches in result.data["matches_by_pattern"].values():
            matches.extend(pattern_matches)
        for match in matches:
            assert match["file"].endswith(".py")

    def test_read_file_success(self, temp_repo):
        """Test reading a file successfully."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "src/main.py"},
        )

        assert result.success
        assert "main()" in result.data["content"]
        assert result.data["file_path"] == "src/main.py"
        # File content has 3 lines plus potential trailing newline
        assert result.data["total_lines"] in [3, 4]
        assert not result.data["is_partial"]

    def test_read_file_missing_path(self, temp_repo):
        """Test read_file with missing file_path."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool("read_file", {})

        assert not result.success
        assert "file_path is required" in result.error

    def test_read_file_not_found(self, temp_repo):
        """Test reading a non-existent file."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "nonexistent.py"},
        )

        assert not result.success
        assert "File not found" in result.error

    def test_read_file_outside_repo(self, temp_repo):
        """Test reading a file outside the repository (security check)."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "../outside.txt"},
        )

        assert not result.success
        assert "Access denied" in result.error

    def test_read_file_binary(self, temp_repo):
        """Test reading a binary file."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "image.png"},
        )

        assert not result.success
        assert "Cannot read binary file" in result.error

    def test_read_file_with_line_range(self, temp_repo):
        """Test reading a file with specific line range."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "src/utils/math.py", "start_line": 1, "end_line": 2},
        )

        assert result.success
        content = result.data["content"]
        assert "calculate_total" in content
        assert "calculate_average" not in content  # Line 4
        assert result.data["start_line"] == 1
        assert result.data["end_line"] == 2

    def test_read_file_invalid_line_range(self, temp_repo):
        """Test reading with invalid line numbers."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "src/main.py", "start_line": 100},
        )

        assert not result.success
        assert "Invalid start_line" in result.error

    def test_read_file_chunking_large_file(self, temp_repo):
        """Test that large files are chunked."""
        # Create a very large file
        large_content = "# Line\n" * 10000
        (temp_repo / "large.py").write_text(large_content)

        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "large.py"},
        )

        assert result.success
        assert result.data["is_partial"]
        assert result.warning is not None
        assert "PARTIAL CONTENT" in result.warning
        assert "start_line=" in result.warning  # Should suggest next chunk

    def test_list_directory_root(self, temp_repo):
        """Test listing root directory."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "."},
        )

        assert result.success
        directories = result.data["directories"]
        files = result.data["files"]

        assert "src" in directories
        assert "tests" in directories
        # Files in root may include image.png, but not main.py (which is in src/)

    def test_list_directory_includes_line_counts(self, temp_repo):
        """Test that file listings include line counts for text files."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "src"},
        )

        assert result.success
        files = result.data["files"]

        # Find main.py and check it has path and lines
        main_py = next((f for f in files if isinstance(f, dict) and "main.py" in f["path"]), None)
        assert main_py is not None, "main.py should be in listing"
        assert "path" in main_py
        assert "lines" in main_py
        assert isinstance(main_py["lines"], int)
        assert main_py["lines"] > 0

    def test_list_directory_subdirectory(self, temp_repo):
        """Test listing a subdirectory."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "src"},
        )

        assert result.success
        assert "src/utils" in result.data["directories"]
        # Files are now dicts with "path" and optionally "lines"
        file_paths = [f["path"] if isinstance(f, dict) else f for f in result.data["files"]]
        assert any("main.py" in f for f in file_paths)

    def test_list_directory_recursive(self, temp_repo):
        """Test recursive directory listing."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "src", "recursive": True},
        )

        assert result.success
        files = result.data["files"]
        # Files are now dicts with "path" and optionally "lines"
        file_paths = [f["path"] if isinstance(f, dict) else f for f in files]

        # Should find files in subdirectories
        assert any("utils/math.py" in f for f in file_paths)
        assert any("utils/helpers.py" in f for f in file_paths)

    def test_list_directory_not_found(self, temp_repo):
        """Test listing a non-existent directory."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "nonexistent"},
        )

        assert not result.success
        assert "Directory not found" in result.error

    def test_list_directory_outside_repo(self, temp_repo):
        """Test listing directory outside repository."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": ".."},
        )

        assert not result.success
        assert "Access denied" in result.error

    def test_list_directory_skips_hidden(self, temp_repo):
        """Test that hidden directories are skipped."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "."},
        )

        assert result.success
        # Should not include .git
        assert ".git" not in result.data["directories"]

    def test_list_directory_truncation_warning(self, temp_repo):
        """Test warning when directory has too many items."""
        # Create many files
        large_dir = temp_repo / "large_dir"
        large_dir.mkdir()
        for i in range(600):
            (large_dir / f"file_{i}.py").write_text("pass")

        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "large_dir"},
        )

        assert result.success
        total_items = len(result.data["files"]) + len(result.data["directories"])
        assert total_items <= 500
        assert result.warning is not None
        assert "PARTIAL LISTING" in result.warning


class TestToolSchemas:
    """Test AI tool schemas."""

    def test_schemas_structure(self):
        """Test that tool schemas have correct structure."""
        assert len(AI_TOOLS_SCHEMA) == 3

        tool_names = {tool["function"]["name"] for tool in AI_TOOLS_SCHEMA}
        assert tool_names == {"search_text", "read_file", "list_directory"}

        # Check each schema has required fields
        for tool in AI_TOOLS_SCHEMA:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_search_text_schema(self):
        """Test search_text schema details."""
        schema = next(
            t for t in AI_TOOLS_SCHEMA if t["function"]["name"] == "search_text"
        )

        params = schema["function"]["parameters"]
        assert "patterns" in params["properties"]
        assert "match_whole_word" in params["properties"]
        assert "case_sensitive" in params["properties"]
        assert "file_pattern" in params["properties"]
        assert "patterns" in params["required"]

    def test_read_file_schema(self):
        """Test read_file schema details."""
        schema = next(
            t for t in AI_TOOLS_SCHEMA if t["function"]["name"] == "read_file"
        )

        params = schema["function"]["parameters"]
        assert "file_path" in params["properties"]
        assert "start_line" in params["properties"]
        assert "end_line" in params["properties"]
        assert "file_path" in params["required"]

    def test_list_directory_schema(self):
        """Test list_directory schema details."""
        schema = next(
            t for t in AI_TOOLS_SCHEMA if t["function"]["name"] == "list_directory"
        )

        params = schema["function"]["parameters"]
        assert "directory_path" in params["properties"]
        assert "recursive" in params["properties"]
        assert "directory_path" in params["required"]


class TestToolResultDataClass:
    """Test ToolResult data class."""

    def test_success_result(self):
        """Test creating a success result."""
        result = ToolResult(success=True, data={"key": "value"})

        assert result.success
        assert result.data == {"key": "value"}
        assert result.error is None
        assert result.warning is None

    def test_error_result(self):
        """Test creating an error result."""
        result = ToolResult(success=False, data=None, error="Something went wrong")

        assert not result.success
        assert result.data is None
        assert result.error == "Something went wrong"

    def test_warning_result(self):
        """Test creating a result with warning."""
        result = ToolResult(
            success=True,
            data={"partial": True},
            warning="Partial content only",
        )

        assert result.success
        assert result.warning == "Partial content only"


class TestErrorHandling:
    """Test error handling in tool execution."""

    def test_execute_tool_exception_handling(self, temp_repo):
        """Test that exceptions are caught and returned as errors."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Mock a method to raise an exception
        with patch.object(
            executor, "_search_text", side_effect=RuntimeError("Test error")
        ):
            result = executor.execute_tool(
                "search_text", {"patterns": "test"}
            )

            assert not result.success
            assert "Tool execution failed" in result.error
            assert "Test error" in result.error

    def test_read_file_read_error(self, temp_repo):
        """Test handling file read errors."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Create a file with permission issues (simulate)
        with patch("code_scanner.ai_tools.read_file_content", return_value=None):
            result = executor.execute_tool(
                "read_file", {"file_path": "src/main.py"}
            )

            assert not result.success
            assert "Failed to read file" in result.error

    def test_read_file_exception_during_read(self, temp_repo):
        """Test handling exceptions during file read."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Simulate an exception during read
        with patch("code_scanner.ai_tools.read_file_content", side_effect=IOError("Permission denied")):
            result = executor.execute_tool(
                "read_file", {"file_path": "src/main.py"}
            )

            assert not result.success
            assert "Error reading file" in result.error

    def test_list_directory_exception_during_listing(self, temp_repo):
        """Test handling exceptions during directory listing."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Simulate an exception during listing
        with patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")):
            result = executor.execute_tool(
                "list_directory", {"directory_path": "."}
            )

            assert not result.success
            assert "Error listing directory" in result.error

    def test_search_text_skips_unreadable_files(self, temp_repo):
        """Test that unreadable files during search are skipped."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Simulate read_file_content returning None for some files
        original_read = read_file_content

        def mock_read(path):
            if "main.py" in str(path):
                return None  # Simulate unreadable
            return original_read(path)

        with patch("code_scanner.ai_tools.read_file_content", side_effect=mock_read):
            result = executor.execute_tool(
                "search_text", {"patterns": "calculate_total"}
            )

            # Should still succeed but may have fewer results
            assert result.success

    def test_search_text_handles_search_exceptions(self, temp_repo):
        """Test that exceptions during individual file search are handled."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Create a mock that raises on specific files
        original_read = read_file_content

        call_count = [0]

        def mock_read(path):
            call_count[0] += 1
            if call_count[0] == 2:  # Raise on second file
                raise RuntimeError("Unexpected error")
            return original_read(path)

        with patch("code_scanner.ai_tools.read_file_content", side_effect=mock_read):
            result = executor.execute_tool(
                "search_text", {"patterns": "def"}
            )

            # Should still succeed (exception is caught and logged)
            assert result.success


class TestReadFileHints:
    """Test the hints feature in read_file."""

    def test_read_file_complete_file_hint(self, temp_repo):
        """Test that complete files include a hint."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file", {"file_path": "src/main.py"}
        )

        assert result.success
        assert "hint" in result.data
        assert "COMPLETE file" in result.data["hint"]
        assert "No need to read it again" in result.data["hint"]

    def test_read_file_partial_no_hint_for_small_percentage(self, temp_repo):
        """Test that small partial reads don't get the 'mostly read' hint."""
        # Create a larger file
        large_content = "\n".join([f"line {i}" for i in range(1000)])
        (temp_repo / "large_file.py").write_text(large_content)

        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file", {"file_path": "large_file.py", "start_line": 1, "end_line": 100}
        )

        assert result.success
        assert result.data["is_partial"]
        # Less than 80%, so no hint
        assert "hint" not in result.data or "Consider proceeding" not in result.data.get("hint", "")


class TestGetFileInfo:
    """Test the _get_file_info helper method."""

    def test_get_file_info_returns_path_and_lines(self, temp_repo):
        """Test that file info includes path and line count."""
        executor = AIToolExecutor(temp_repo, 8192)

        full_path = temp_repo / "src" / "main.py"
        relative_path = Path("src/main.py")

        info = executor._get_file_info(full_path, relative_path)

        assert "path" in info
        assert info["path"] == "src/main.py"
        assert "lines" in info
        assert info["lines"] > 0

    def test_get_file_info_handles_read_error(self, temp_repo):
        """Test that file info handles read errors gracefully."""
        executor = AIToolExecutor(temp_repo, 8192)

        full_path = temp_repo / "src" / "main.py"
        relative_path = Path("src/main.py")

        # Simulate read error
        with patch("code_scanner.ai_tools.read_file_content", side_effect=IOError("Read error")):
            info = executor._get_file_info(full_path, relative_path)

            # Should still return path, just without lines
            assert "path" in info
            assert info["path"] == "src/main.py"
            # No lines key because read failed
            assert "lines" not in info

    def test_get_file_info_skips_binary_files(self, temp_repo):
        """Test that binary files don't get line count."""
        executor = AIToolExecutor(temp_repo, 8192)

        full_path = temp_repo / "image.png"
        relative_path = Path("image.png")

        info = executor._get_file_info(full_path, relative_path)

        assert "path" in info
        assert info["path"] == "image.png"
        # Binary files don't have lines
        assert "lines" not in info


class TestPaginationSupport:
    """Test pagination support across all tools."""

    def test_search_text_pagination_offset(self, temp_repo):
        """Test that search_text supports offset pagination."""
        # Create many files with matches
        for i in range(100):
            (temp_repo / f"file_{i}.py").write_text(f"def my_function():\n    pass\n")

        executor = AIToolExecutor(temp_repo, 8192)

        # First page (default offset=0)
        result1 = executor.execute_tool(
            "search_text",
            {"patterns": "my_function"},
        )

        assert result1.success
        assert result1.data["has_more"] is True
        assert result1.data["returned_count"] == 50
        assert result1.data["total_matches"] > 50
        assert "next_offset" in result1.data
        next_offset = result1.data["next_offset"]
        assert next_offset == 50

        # Second page
        result2 = executor.execute_tool(
            "search_text",
            {"patterns": "my_function", "offset": next_offset},
        )

        assert result2.success
        assert result2.data["returned_count"] == 50
        assert result2.data["offset"] == 50

        # Matches from page 1 and page 2 should be different
        page1_files = {m["file"] for m in result1.data["matches_by_pattern"].get("my_function", [])}
        page2_files = {m["file"] for m in result2.data["matches_by_pattern"].get("my_function", [])}
        assert page1_files.isdisjoint(page2_files), "Pages should contain different files"

    def test_search_text_no_more_pages(self, temp_repo):
        """Test that has_more is False when all results fit."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "calculate_total"},
        )

        assert result.success
        # Only 2 matches (main.py, math.py), should fit in one page
        assert result.data["has_more"] is False
        assert "next_offset" not in result.data

    def test_list_directory_pagination_offset(self, temp_repo):
        """Test that list_directory supports offset pagination."""
        # Create many files
        many_files_dir = temp_repo / "many_files"
        many_files_dir.mkdir()
        for i in range(150):
            (many_files_dir / f"file_{i:03d}.txt").write_text(f"content {i}")

        executor = AIToolExecutor(temp_repo, 8192)

        # First page (default offset=0)
        result1 = executor.execute_tool(
            "list_directory",
            {"directory_path": "many_files"},
        )

        assert result1.success
        assert result1.data["has_more"] is True
        assert result1.data["returned_count"] == 100
        assert result1.data["total_items"] == 150
        assert "next_offset" in result1.data
        next_offset = result1.data["next_offset"]
        assert next_offset == 100

        # Second page
        result2 = executor.execute_tool(
            "list_directory",
            {"directory_path": "many_files", "offset": next_offset},
        )

        assert result2.success
        assert result2.data["returned_count"] == 50
        assert result2.data["offset"] == 100
        assert result2.data["has_more"] is False
        assert "next_offset" not in result2.data

    def test_list_directory_no_pagination_needed(self, temp_repo):
        """Test that has_more is False when all items fit."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "src"},
        )

        assert result.success
        assert result.data["has_more"] is False
        assert "next_offset" not in result.data

    def test_read_file_has_more_metadata(self, temp_repo):
        """Test that read_file includes has_more and next_start_line."""
        # Create a file with multiple lines
        (temp_repo / "multiline.txt").write_text("\n".join([f"line {i}" for i in range(1, 51)]))

        executor = AIToolExecutor(temp_repo, 8192)

        # Read first 10 lines
        result = executor.execute_tool(
            "read_file",
            {"file_path": "multiline.txt", "start_line": 1, "end_line": 10},
        )

        assert result.success
        assert result.data["has_more"] is True
        assert result.data["next_start_line"] == 11
        assert result.data["lines_returned"] == 10

    def test_read_file_no_more_lines(self, temp_repo):
        """Test that has_more is False when reading entire file."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "src/main.py"},
        )

        assert result.success
        assert result.data["has_more"] is False
        assert "next_start_line" not in result.data

    def test_pagination_warning_message_format(self, temp_repo):
        """Test that pagination warnings include next_offset instructions."""
        # Create many files with matches
        for i in range(100):
            (temp_repo / f"usage_{i}.py").write_text(f"def paginate_me():\n    pass\n")

        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "paginate_me"},
        )

        assert result.warning is not None
        assert "offset=50" in result.warning
        assert "PARTIAL RESULTS" in result.warning


class TestAdditionalCoverage:
    """Additional tests to increase code coverage."""

    def test_search_text_skips_build_directories(self, temp_repo):
        """Test that search_text skips node_modules, __pycache__, etc."""
        # Create build directories with matching content
        build_dir = temp_repo / "node_modules"
        build_dir.mkdir()
        (build_dir / "package.py").write_text("def target_func():\n    pass\n")

        pycache_dir = temp_repo / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "module.py").write_text("def target_func():\n    pass\n")

        # Create a normal file with the function
        (temp_repo / "normal.py").write_text("def target_func():\n    pass\n")

        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": "target_func"},
        )

        assert result.success
        # Should only find in normal.py, not in build directories
        matches = result.data["matches_by_pattern"].get("target_func", [])
        files = [m["file"] for m in matches]
        assert "normal.py" in files
        assert not any("node_modules" in f for f in files)
        assert not any("__pycache__" in f for f in files)

    def test_read_file_directory_path_returns_error(self, temp_repo):
        """Test that read_file returns error when given a directory path."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "src"},  # src is a directory
        )

        assert not result.success
        assert "Not a file" in result.error

    def test_read_file_end_line_adjusted_when_invalid(self, temp_repo):
        """Test that end_line is adjusted when it exceeds total lines."""
        (temp_repo / "short.txt").write_text("line1\nline2\nline3")

        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "read_file",
            {"file_path": "short.txt", "start_line": 1, "end_line": 100},
        )

        assert result.success
        assert result.data["end_line"] == 3  # Adjusted to actual file length
        assert result.data["total_lines"] == 3

    def test_read_file_partial_hint_for_high_coverage(self, temp_repo):
        """Test that hint is shown when 80%+ of file is read."""
        # Create a file with 100 lines
        (temp_repo / "long.txt").write_text("\n".join([f"line {i}" for i in range(100)]))

        executor = AIToolExecutor(temp_repo, 8192)

        # Read 85 lines (85%)
        result = executor.execute_tool(
            "read_file",
            {"file_path": "long.txt", "start_line": 1, "end_line": 85},
        )

        assert result.success
        assert "hint" in result.data
        assert "85%" in result.data["hint"]
        assert "Consider proceeding" in result.data["hint"]

    def test_list_directory_not_a_directory_error(self, temp_repo):
        """Test that list_directory returns error for non-directory path."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "src/main.py"},  # This is a file, not directory
        )

        assert not result.success
        assert "Not a directory" in result.error

    def test_list_directory_recursive_skips_build_dirs(self, temp_repo):
        """Test that recursive listing skips build directories."""
        # Create build directory with files
        build_dir = temp_repo / "src" / "node_modules"
        build_dir.mkdir(parents=True)
        (build_dir / "package.js").write_text("module.exports = {}")

        dist_dir = temp_repo / "dist"
        dist_dir.mkdir()
        (dist_dir / "output.js").write_text("console.log('built')")

        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": ".", "recursive": True},
        )

        assert result.success
        # Check that build directories are not in results
        all_paths = [f["path"] if isinstance(f, dict) else f for f in result.data["files"]]
        all_paths += result.data["directories"]

        assert not any("node_modules" in p for p in all_paths)
        assert not any("dist" in p for p in all_paths)

    def test_list_directory_recursive_exception_handling(self, temp_repo):
        """Test that list_directory handles exceptions during recursive listing."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Patch rglob to raise an exception
        with patch.object(Path, "rglob", side_effect=PermissionError("Access denied")):
            result = executor.execute_tool(
                "list_directory",
                {"directory_path": ".", "recursive": True},
            )

            assert not result.success
            assert "Error listing directory" in result.error or "Access denied" in result.error

    def test_find_code_usage_legacy_support(self, temp_repo):
        """Test legacy find_code_usage redirects to search_text."""
        executor = AIToolExecutor(temp_repo, 8192)

        # Use legacy find_code_usage tool name
        result = executor.execute_tool(
            "find_code_usage",
            {"entity_name": "calculate_total"},
        )

        assert result.success
        assert result.data["total_matches"] >= 1
        assert "matches_by_pattern" in result.data

    def test_find_code_usage_legacy_with_offset(self, temp_repo):
        """Test legacy find_code_usage with pagination offset."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "find_code_usage",
            {"entity_name": "calculate_total", "offset": 0},
        )

        assert result.success
        assert "offset" in result.data

    def test_search_text_empty_pattern_in_list(self, temp_repo):
        """Test search_text filters out empty patterns."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "search_text",
            {"patterns": ["", "calculate_total", ""]},
        )

        assert result.success
        assert result.data["total_matches"] >= 1

    def test_list_directory_empty_path_default(self, temp_repo):
        """Test list_directory with empty string defaults to current directory."""
        executor = AIToolExecutor(temp_repo, 8192)

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": ""},
        )

        assert result.success
        # Should list root directory contents
        assert len(result.data["files"]) > 0 or len(result.data["directories"]) > 0
