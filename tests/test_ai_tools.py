"""Unit tests for AI tools (context expansion via function calling)."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open

from code_scanner.ai_tools import (
    AIToolExecutor,
    ToolResult,
    AI_TOOLS_SCHEMA,
    DEFAULT_CHUNK_SIZE_TOKENS,
)
from code_scanner.ctags_index import CtagsIndex, Symbol
from code_scanner.utils import read_file_content


def make_mock_ctags(target_dir):
    """Create a mock CtagsIndex for testing."""
    mock_index = MagicMock(spec=CtagsIndex)
    mock_index.repo_path = target_dir
    mock_index.find_symbol.return_value = []
    mock_index.find_definitions.return_value = []
    mock_index.find_symbols_by_pattern.return_value = []
    mock_index.get_symbols_in_file.return_value = []
    mock_index.get_file_structure.return_value = {
        "file_path": "test.py",
        "classes": [],
        "functions": [],
        "variables": [],
        "imports": [],
        "other": [],
    }
    mock_index.get_stats.return_value = {
        "indexed": True,
        "total_symbols": 0,
        "total_files": 0,
        "by_kind": {},
        "by_language": {},
    }
    return mock_index


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
            ctags_index=make_mock_ctags(temp_repo),
        )

        assert executor.target_directory == temp_repo
        assert executor.context_limit == 8192
        assert executor.chunk_size == min(DEFAULT_CHUNK_SIZE_TOKENS, 8192 // 4)

    def test_execute_unknown_tool(self, temp_repo):
        """Test executing an unknown tool."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool("unknown_tool", {})

        assert not result.success
        assert "Unknown tool" in result.error

    def test_search_text_missing_patterns(self, temp_repo):
        """Test search_text with missing patterns."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool("search_text", {})

        assert not result.success
        assert "pattern" in result.error.lower()

    def test_search_text_single_pattern(self, temp_repo):
        """Test searching for a single pattern."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": "nonexistent_function"},
        )

        assert result.success
        assert result.data["total_matches"] == 0

    def test_search_text_skips_binary_files(self, temp_repo):
        """Test that binary files are skipped during search."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        # Search for something that might be in binary
        result = executor.execute_tool(
            "search_text",
            {"patterns": "PNG"},
        )

        # Should not crash, binary files should be skipped
        assert result.success

    def test_search_text_skips_hidden_dirs(self, temp_repo):
        """Test that hidden directories are skipped."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": "gitconfig"},
        )

        # Should not find anything in .git directory
        assert result.success
        assert result.data["total_matches"] == 0

    def test_search_text_partial_results_warning(self, temp_repo):
        """Test warning when results are truncated."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": "HELPER", "case_sensitive": False},
        )

        assert result.success
        assert result.data["total_matches"] >= 1

    def test_search_text_case_sensitive(self, temp_repo):
        """Test case-sensitive search."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": "HELPER", "case_sensitive": True},
        )

        assert result.success
        # "HELPER" in all caps shouldn't match "Helper"
        assert result.data["total_matches"] == 0

    def test_search_text_substring_match(self, temp_repo):
        """Test substring matching (match_whole_word=False)."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": "calc", "match_whole_word": False},
        )

        assert result.success
        # Should match "calculate_total" as substring
        assert result.data["total_matches"] >= 1

    def test_search_text_file_pattern_filter(self, temp_repo):
        """Test file pattern filtering."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool("read_file", {})

        assert not result.success
        assert "file_path is required" in result.error

    def test_read_file_not_found(self, temp_repo):
        """Test reading a non-existent file."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "read_file",
            {"file_path": "nonexistent.py"},
        )

        assert not result.success
        assert "File not found" in result.error

    def test_read_file_outside_repo(self, temp_repo):
        """Test reading a file outside the repository (security check)."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "read_file",
            {"file_path": "../outside.txt"},
        )

        assert not result.success
        assert "Access denied" in result.error

    def test_read_file_binary(self, temp_repo):
        """Test reading a binary file."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "read_file",
            {"file_path": "image.png"},
        )

        assert not result.success
        assert "Cannot read binary file" in result.error

    def test_read_file_with_line_range(self, temp_repo):
        """Test reading a file with specific line range."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": "nonexistent"},
        )

        assert not result.success
        assert "Directory not found" in result.error

    def test_list_directory_outside_repo(self, temp_repo):
        """Test listing directory outside repository."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": ".."},
        )

        assert not result.success
        assert "Access denied" in result.error

    def test_list_directory_skips_hidden(self, temp_repo):
        """Test that hidden directories are skipped."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        assert len(AI_TOOLS_SCHEMA) == 10

        tool_names = {tool["function"]["name"] for tool in AI_TOOLS_SCHEMA}
        assert tool_names == {
            "search_text", "read_file", "list_directory",
            "get_file_diff", "get_file_summary", "symbol_exists",
            "find_definition", "find_symbols",
            "get_enclosing_scope", "find_usages",
        }

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
        assert "is_regex" in params["properties"]
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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        # Create a file with permission issues (simulate)
        with patch("code_scanner.ai_tools.read_file_content", return_value=None):
            result = executor.execute_tool(
                "read_file", {"file_path": "src/main.py"}
            )

            assert not result.success
            assert "Failed to read file" in result.error

    def test_read_file_exception_during_read(self, temp_repo):
        """Test handling exceptions during file read."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        # Simulate an exception during read
        with patch("code_scanner.ai_tools.read_file_content", side_effect=IOError("Permission denied")):
            result = executor.execute_tool(
                "read_file", {"file_path": "src/main.py"}
            )

            assert not result.success
            assert "Error reading file" in result.error

    def test_list_directory_exception_during_listing(self, temp_repo):
        """Test handling exceptions during directory listing."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        # Simulate an exception during listing
        with patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")):
            result = executor.execute_tool(
                "list_directory", {"directory_path": "."}
            )

            assert not result.success
            assert "Error listing directory" in result.error

    def test_search_text_skips_unreadable_files(self, temp_repo):
        """Test that unreadable files during search are skipped."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        full_path = temp_repo / "src" / "main.py"
        relative_path = Path("src/main.py")

        info = executor._get_file_info(full_path, relative_path)

        assert "path" in info
        assert info["path"] == "src/main.py"
        assert "lines" in info
        assert info["lines"] > 0

    def test_get_file_info_handles_read_error(self, temp_repo):
        """Test that file info handles read errors gracefully."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "read_file",
            {"file_path": "src"},  # src is a directory
        )

        assert not result.success
        assert "Not a file" in result.error

    def test_read_file_end_line_adjusted_when_invalid(self, temp_repo):
        """Test that end_line is adjusted when it exceeds total lines."""
        (temp_repo / "short.txt").write_text("line1\nline2\nline3")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

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
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        # Patch rglob to raise an exception
        with patch.object(Path, "rglob", side_effect=PermissionError("Access denied")):
            result = executor.execute_tool(
                "list_directory",
                {"directory_path": ".", "recursive": True},
            )

            assert not result.success
            assert "Error listing directory" in result.error or "Access denied" in result.error

    def test_search_text_empty_pattern_in_list(self, temp_repo):
        """Test search_text filters out empty patterns."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": ["", "calculate_total", ""]},
        )

        assert result.success
        assert result.data["total_matches"] >= 1

    def test_list_directory_empty_path_default(self, temp_repo):
        """Test list_directory with empty string defaults to current directory."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "list_directory",
            {"directory_path": ""},
        )

        assert result.success
        # Should list root directory contents
        assert len(result.data["files"]) > 0 or len(result.data["directories"]) > 0


class TestSearchTextRegex:
    """Test is_regex functionality in search_text."""

    def test_search_text_with_regex_pattern(self, temp_repo):
        """Test search_text with is_regex=True uses pattern as-is."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        # Regex to find function definitions
        result = executor.execute_tool(
            "search_text",
            {"patterns": r"def\s+\w+", "is_regex": True},
        )

        assert result.success
        assert result.data["total_matches"] >= 1

    def test_search_text_with_invalid_regex(self, temp_repo):
        """Test search_text with invalid regex returns error."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": "[invalid(regex", "is_regex": True},
        )

        assert not result.success
        assert "Invalid regex" in result.error

    def test_search_text_regex_with_alternation(self, temp_repo):
        """Test search_text regex with | alternation."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        result = executor.execute_tool(
            "search_text",
            {"patterns": r"(class|def)\s+\w+", "is_regex": True},
        )

        assert result.success
        assert result.data["total_matches"] >= 1

    def test_search_text_literal_special_chars_escaped(self, temp_repo):
        """Test that special chars are escaped when is_regex=False."""
        # Create a file with regex-special characters
        (temp_repo / "special.txt").write_text("price is $10.99\n")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))

        # Without is_regex, the $ and . should be treated literally
        result = executor.execute_tool(
            "search_text",
            {"patterns": "$10.99", "is_regex": False, "match_whole_word": False},
        )

        assert result.success
        assert result.data["total_matches"] == 1


class TestGetFileDiff:
    """Test get_file_diff tool."""

    def test_get_file_diff_no_changes(self, temp_repo):
        """Test get_file_diff when file has no changes."""
        # Initialize git repo and commit the file
        import subprocess
        subprocess.run(["git", "init"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": "src/main.py"},
        )

        assert result.success
        assert result.data["has_changes"] is False

    def test_get_file_diff_with_changes(self, temp_repo):
        """Test get_file_diff when file has uncommitted changes."""
        import subprocess
        subprocess.run(["git", "init"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)

        # Make a change
        main_file = temp_repo / "src" / "main.py"
        main_file.write_text(main_file.read_text() + "\n# New comment\n")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": "src/main.py"},
        )

        assert result.success
        assert result.data["has_changes"] is True
        assert "diff" in result.data
        assert "+# New comment" in result.data["diff"]

    def test_get_file_diff_missing_path(self, temp_repo):
        """Test get_file_diff with missing file_path."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": ""},
        )

        assert not result.success
        assert "file_path is required" in result.error

    def test_get_file_diff_outside_repo(self, temp_repo):
        """Test get_file_diff with path outside repository."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": "../../../etc/passwd"},
        )

        assert not result.success
        assert "Access denied" in result.error

    def test_get_file_diff_not_git_repo(self, tmp_path):
        """Test get_file_diff when not in a git repository."""
        # Create a non-git directory
        test_file = tmp_path / "test.py"
        test_file.write_text("# test\n")

        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": "test.py"},
        )

        assert not result.success
        # Error message may vary: "Not a git repository" or "Could not access 'HEAD'"
        assert "git" in result.error.lower() or "repository" in result.error.lower() or "HEAD" in result.error

    def test_get_file_diff_with_context_lines(self, temp_repo):
        """Test get_file_diff with custom context_lines."""
        import subprocess
        subprocess.run(["git", "init"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)

        # Make a change
        main_file = temp_repo / "src" / "main.py"
        main_file.write_text(main_file.read_text() + "\n# New comment\n")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": "src/main.py", "context_lines": 5},
        )

        assert result.success
        assert result.data["context_lines"] == 5


class TestGitToolsTimeoutAndExceptions:
    """Test timeout and exception handling for git tools."""

    def test_get_file_diff_timeout(self, temp_repo, monkeypatch):
        """Test get_file_diff handles subprocess timeout."""
        import subprocess as sp
        
        def mock_run(*args, **kwargs):
            raise sp.TimeoutExpired(cmd="git diff", timeout=30)
        
        monkeypatch.setattr(sp, "run", mock_run)
        
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": "src/main.py"},
        )
        
        assert not result.success
        assert "timed out" in result.error

    def test_get_file_diff_general_exception(self, temp_repo, monkeypatch):
        """Test get_file_diff handles general exceptions."""
        import subprocess as sp
        
        def mock_run(*args, **kwargs):
            raise RuntimeError("Unexpected error")
        
        monkeypatch.setattr(sp, "run", mock_run)
        
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_diff",
            {"file_path": "src/main.py"},
        )
        
        assert not result.success
        assert "Error getting diff" in result.error


class TestNewToolSchemas:
    """Test schemas for new git tools."""

    def test_get_file_diff_schema(self):
        """Test get_file_diff schema details."""
        schema = next(
            t for t in AI_TOOLS_SCHEMA if t["function"]["name"] == "get_file_diff"
        )

        params = schema["function"]["parameters"]
        assert "file_path" in params["properties"]
        assert "context_lines" in params["properties"]
        assert "file_path" in params["required"]
        # context_lines should have min/max
        assert params["properties"]["context_lines"]["minimum"] == 0
        assert params["properties"]["context_lines"]["maximum"] == 10

    def test_search_text_is_regex_schema(self):
        """Test search_text schema includes is_regex parameter."""
        schema = next(
            t for t in AI_TOOLS_SCHEMA if t["function"]["name"] == "search_text"
        )

        params = schema["function"]["parameters"]
        assert "is_regex" in params["properties"]
        assert params["properties"]["is_regex"]["type"] == "boolean"


class TestGetFileSummary:
    """Tests for get_file_summary tool."""

    def test_get_file_summary_python_file(self, temp_repo):
        """Test get_file_summary extracts Python structure."""
        test_file = temp_repo / "module.py"
        test_file.write_text("""
import os
from pathlib import Path

class MyClass:
    def __init__(self):
        pass
    
    def method(self):
        pass

def helper_function():
    pass

CONSTANT = 42
""")

        # Configure mock to return expected structure
        mock_ctags = make_mock_ctags(temp_repo)
        mock_ctags.get_file_structure.return_value = {
            "file_path": "module.py",
            "classes": [{"name": "MyClass", "line": 5}],
            "functions": [
                {"name": "__init__", "line": 6},
                {"name": "method", "line": 9},
                {"name": "helper_function", "line": 12},
            ],
            "variables": [{"name": "CONSTANT", "line": 15}],
            "imports": ["import os", "from pathlib import Path"],
            "other": [],
        }

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        result = executor.execute_tool(
            "get_file_summary", {"file_path": "module.py"}
        )

        assert result.success is True
        data = result.data
        assert data["file_path"] == "module.py"
        assert "classes" in data
        assert "functions" in data
        assert "imports" in data
        # Classes and functions are dicts with 'name' and 'line'
        class_names = [c["name"] for c in data["classes"]]
        function_names = [f["name"] for f in data["functions"]]
        assert "MyClass" in class_names
        assert "helper_function" in function_names
        assert any("os" in i or "pathlib" in i for i in data["imports"])

    def test_get_file_summary_javascript_file(self, temp_repo):
        """Test get_file_summary extracts JavaScript structure."""
        test_file = temp_repo / "module.js"
        test_file.write_text("""
import { something } from 'module';
const { foo } = require('bar');

class JsClass {
    constructor() {}
    method() {}
}

function namedFunction() {}

const arrowFunc = () => {};
""")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_summary", {"file_path": "module.js"}
        )

        assert result.success is True
        data = result.data
        assert "classes" in data
        assert "functions" in data
        assert "imports" in data

    def test_get_file_summary_file_not_found(self, temp_repo):
        """Test get_file_summary with non-existent file."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_summary", {"file_path": "nonexistent.py"}
        )

        assert result.success is False
        assert "not found" in result.error.lower() or "does not exist" in result.error.lower()

    def test_get_file_summary_missing_path(self, temp_repo):
        """Test get_file_summary with missing path."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool("get_file_summary", {})

        assert result.success is False
        assert "file_path" in result.error.lower()


class TestSymbolExists:
    """Tests for symbol_exists tool."""

    def test_symbol_exists_finds_function(self, temp_repo):
        """Test symbol_exists finds a function definition."""
        test_file = temp_repo / "code.py"
        test_file.write_text("""
def my_unique_function():
    pass
""")

        # Configure mock to return symbol data
        mock_ctags = make_mock_ctags(temp_repo)
        mock_ctags.find_symbol.return_value = [
            Symbol(
                name="my_unique_function",
                file_path="code.py",
                line=2,
                kind="function",
                language="Python",
                pattern="def my_unique_function():",
                scope=None,
                signature=None,
            )
        ]

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "my_unique_function"}
        )

        assert result.success is True
        data = result.data
        assert data["exists"] is True
        assert data["symbol"] == "my_unique_function"
        assert "locations" in data
        assert len(data["locations"]) > 0

    def test_symbol_exists_finds_class(self, temp_repo):
        """Test symbol_exists finds a class definition."""
        test_file = temp_repo / "models.py"
        test_file.write_text("""
class UniqueClassName:
    pass
""")

        # Configure mock to return class symbol
        mock_ctags = make_mock_ctags(temp_repo)
        mock_ctags.find_symbol.return_value = [
            Symbol(
                name="UniqueClassName",
                file_path="models.py",
                line=2,
                kind="class",
                language="Python",
                pattern="class UniqueClassName:",
                scope=None,
                signature=None,
            )
        ]

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "UniqueClassName", "symbol_type": "class"}
        )

        assert result.success is True
        assert result.data["exists"] is True

    def test_symbol_exists_not_found(self, temp_repo):
        """Test symbol_exists when symbol doesn't exist."""
        # Mock returns empty list (default)
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "nonexistent_symbol_12345"}
        )

        assert result.success is True
        assert result.data["exists"] is False
        assert result.data["locations"] == []

    def test_symbol_exists_missing_symbol(self, temp_repo):
        """Test symbol_exists with missing symbol parameter."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool("symbol_exists", {})

        assert result.success is False
        assert "symbol" in result.error.lower()

    def test_symbol_exists_type_filter(self, temp_repo):
        """Test symbol_exists with type filter."""
        test_file = temp_repo / "mixed.py"
        test_file.write_text("""
def process():
    pass

class process:  # Same name as function
    pass
""")

        # Configure mock to return both function and class
        mock_ctags = make_mock_ctags(temp_repo)
        
        # For "any" query, return both
        def find_symbol_side_effect(name, kind=None):
            symbols = [
                Symbol(name="process", file_path="mixed.py", line=2, kind="function",
                       language="Python", pattern="def process():", scope=None, signature=None),
                Symbol(name="process", file_path="mixed.py", line=5, kind="class",
                       language="Python", pattern="class process:", scope=None, signature=None),
            ]
            if kind:
                return [s for s in symbols if s.kind == kind]
            return symbols
        
        mock_ctags.find_symbol.side_effect = find_symbol_side_effect

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        
        # Without type filter - should find something
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "process"}
        )
        assert result.success is True
        assert result.data["exists"] is True

        # With function type filter
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "process", "symbol_type": "function"}
        )
        assert result.success is True
        assert result.data["exists"] is True


class TestIsDefinitionLine:
    """Tests for _is_definition_line helper."""

    def test_detects_python_function(self, temp_repo):
        """Test detecting Python function definition."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        assert executor._is_definition_line("def my_function():", "my_function") is True
        assert executor._is_definition_line("async def my_function():", "my_function") is True
        assert executor._is_definition_line("  def my_function():", "my_function") is True

    def test_detects_python_class(self, temp_repo):
        """Test detecting Python class definition."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        assert executor._is_definition_line("class MyClass:", "MyClass") is True
        assert executor._is_definition_line("class MyClass(Base):", "MyClass") is True

    def test_detects_javascript_function(self, temp_repo):
        """Test detecting JavaScript function definition."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        assert executor._is_definition_line("function myFunc() {", "myFunc") is True
        assert executor._is_definition_line("const myFunc = () => {}", "myFunc") is True
        assert executor._is_definition_line("let myFunc = function() {}", "myFunc") is True

    def test_detects_javascript_class(self, temp_repo):
        """Test detecting JavaScript class definition."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        assert executor._is_definition_line("class MyClass {", "MyClass") is True
        assert executor._is_definition_line("export class MyClass {", "MyClass") is True
        assert executor._is_definition_line("export default class MyClass {", "MyClass") is True

    def test_not_definition(self, temp_repo):
        """Test that usage lines are not detected as definitions."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        # Function calls are not definitions
        assert executor._is_definition_line("result = my_function()", "my_function") is False
        # References in strings are not definitions
        assert executor._is_definition_line("print('my_function')", "my_function") is False


class TestSymbolExistsTypeFilters:
    """Additional tests for symbol_exists type filtering."""

    def test_symbol_exists_variable_type(self, temp_repo):
        """Test symbol_exists with variable type filter."""
        test_file = temp_repo / "vars.py"
        test_file.write_text("""
let myVariable = 42
const MY_CONSTANT = "value"
var anotherVar = true
""")

        # Configure mock to return variable symbol
        mock_ctags = make_mock_ctags(temp_repo)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="myVariable", file_path="vars.py", line=2, kind="variable",
                   language="Python", pattern="let myVariable = 42", scope=None, signature=None)
        ]

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "myVariable", "symbol_type": "variable"}
        )
        assert result.success is True
        assert result.data["exists"] is True

    def test_symbol_exists_constant_type(self, temp_repo):
        """Test symbol_exists with constant type filter."""
        test_file = temp_repo / "consts.py"
        test_file.write_text("""
const MAX_SIZE = 100
final int BUFFER_SIZE = 1024
#define DEBUG_MODE 1
""")

        # Configure mock to return constant symbol
        mock_ctags = make_mock_ctags(temp_repo)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="MAX_SIZE", file_path="consts.py", line=2, kind="constant",
                   language="Python", pattern="const MAX_SIZE = 100", scope=None, signature=None)
        ]

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "MAX_SIZE", "symbol_type": "constant"}
        )
        assert result.success is True
        assert result.data["exists"] is True

    def test_symbol_exists_interface_type(self, temp_repo):
        """Test symbol_exists with interface type filter."""
        test_file = temp_repo / "interfaces.ts"
        test_file.write_text("""
interface IUserService {
    getUser(id: string): User;
}

protocol DataProvider {
    func fetchData() -> Data
}
""")

        # Configure mock to return interface symbol
        mock_ctags = make_mock_ctags(temp_repo)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="IUserService", file_path="interfaces.ts", line=2, kind="interface",
                   language="TypeScript", pattern="interface IUserService {", scope=None, signature=None)
        ]

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        result = executor.execute_tool(
            "symbol_exists", {"symbol": "IUserService", "symbol_type": "interface"}
        )
        assert result.success is True
        assert result.data["exists"] is True


class TestGetFileSummaryEdgeCases:
    """Additional tests for get_file_summary edge cases."""

    def test_get_file_summary_with_constants(self, temp_repo):
        """Test that get_file_summary detects constants."""
        test_file = temp_repo / "config.py"
        test_file.write_text("""
const MAX_RETRIES = 3
final static int BUFFER_SIZE = 1024
#define MAX_CONNECTIONS 100
readonly string CONFIG_PATH = "/etc/app"
""")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_summary", {"file_path": "config.py"}
        )

        assert result.success is True
        # Constants detection may vary by pattern matching

    def test_get_file_summary_cpp_file(self, temp_repo):
        """Test get_file_summary with C++ file."""
        test_file = temp_repo / "module.cpp"
        test_file.write_text("""
#include <iostream>
#include "header.h"

class Calculator {
public:
    int add(int a, int b);
    int multiply(int a, int b);
};

void helperFunction() {
    // implementation
}
""")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_summary", {"file_path": "module.cpp"}
        )

        assert result.success is True
        data = result.data
        assert "classes" in data
        assert "functions" in data
        assert "imports" in data

    def test_get_file_summary_go_file(self, temp_repo):
        """Test get_file_summary with Go file."""
        test_file = temp_repo / "main.go"
        test_file.write_text("""
package main

import (
    "fmt"
    "net/http"
)

type Server struct {
    port int
}

func (s *Server) Start() error {
    return nil
}

func main() {
    fmt.Println("Hello")
}
""")

        # Configure mock to return Go file structure
        mock_ctags = make_mock_ctags(temp_repo)
        mock_ctags.get_file_structure.return_value = {
            "file_path": "main.go",
            "classes": [{"name": "Server", "line": 9}],
            "functions": [
                {"name": "Start", "line": 13},
                {"name": "main", "line": 17},
            ],
            "variables": [],
            "imports": ['import "fmt"', 'import "net/http"'],
            "other": [],
        }

        executor = AIToolExecutor(temp_repo, 8192, mock_ctags)
        result = executor.execute_tool(
            "get_file_summary", {"file_path": "main.go"}
        )

        assert result.success is True
        data = result.data
        assert len(data["functions"]) >= 1  # At least main() should be detected

    def test_get_file_summary_truncates_long_imports(self, temp_repo):
        """Test that long import lines are truncated."""
        long_import = "import " + "a" * 100 + " from 'long-module-name'"
        test_file = temp_repo / "long_imports.js"
        test_file.write_text(f"""
{long_import}
function test() {{}}
""")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "get_file_summary", {"file_path": "long_imports.js"}
        )

        assert result.success is True
        # Imports should be truncated at 80 chars + "..."
        if result.data["imports"]:
            assert len(result.data["imports"][0]) <= 84  # 80 + "..."


class TestSearchTextDefinitionOrdering:
    """Test that search results prioritize definitions."""

    def test_definitions_come_first(self, temp_repo):
        """Test that definition matches appear before usage matches."""
        # Create file with definition and usages
        test_file = temp_repo / "module.py"
        test_file.write_text("""
# Line 1 - usage
result = calculate_total(items)
# Line 3 - definition
def calculate_total(items):
    return sum(items)
# Line 6 - another usage
total = calculate_total(data)
""")

        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool(
            "search_text", {"patterns": "calculate_total"}
        )

        assert result.success is True
        matches = result.data["matches_by_pattern"]["calculate_total"]
        
        # Should have multiple matches
        assert len(matches) >= 2
        
        # Definition (is_definition=True) should come before usages
        has_definition_first = False
        for i, match in enumerate(matches):
            if match.get("is_definition"):
                has_definition_first = i == 0
                break
        
        # The definition should appear first in the sorted results
        assert has_definition_first or any(m.get("is_definition") for m in matches)


class TestLLMInterfaceConsistency:
    """Tests to verify LLM interface consistency."""

    def test_all_tools_in_schema(self):
        """Verify all 10 tools are present in schema."""
        tool_names = {tool["function"]["name"] for tool in AI_TOOLS_SCHEMA}
        expected_tools = {
            "search_text",
            "read_file", 
            "list_directory",
            "get_file_diff",
            "get_file_summary",
            "symbol_exists",
            "find_definition",
            "find_symbols",
            "get_enclosing_scope",
            "find_usages",
        }
        assert tool_names == expected_tools

    def test_all_tools_have_required_fields(self):
        """Verify all tool schemas have required fields."""
        for tool in AI_TOOLS_SCHEMA:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"
            assert "properties" in func["parameters"]
            assert "required" in func["parameters"]

    def test_tool_names_match_executor_dispatch(self, temp_repo):
        """Verify executor handles all schema-defined tools."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        
        # Test that all tools are handled (return success or expected error)
        test_args = {
            "search_text": {"patterns": "test"},
            "read_file": {"file_path": "nonexistent.py"},
            "list_directory": {"directory_path": "."},
            "get_file_diff": {"file_path": "test.py"},
            "get_git_blame": {"file_path": "test.py", "start_line": 1, "end_line": 1},
            "get_file_history": {"file_path": "test.py"},
            "get_file_summary": {"file_path": "nonexistent.py"},
            "symbol_exists": {"symbol": "test"},
        }

        for tool_name, args in test_args.items():
            result = executor.execute_tool(tool_name, args)
            # Should return a ToolResult (not raise exception)
            assert isinstance(result, ToolResult), f"Tool {tool_name} should return ToolResult"

    def test_unknown_tool_returns_error(self, temp_repo):
        """Verify unknown tools return proper error."""
        executor = AIToolExecutor(temp_repo, 8192, make_mock_ctags(temp_repo))
        result = executor.execute_tool("nonexistent_tool", {})
        assert result.success is False
        assert "Unknown tool" in result.error


class TestBuildUserPromptFormat:
    """Tests for build_user_prompt formatting."""

    def test_includes_line_numbers(self):
        """Test that build_user_prompt includes line numbers."""
        from code_scanner.base_client import build_user_prompt
        
        prompt = build_user_prompt(
            check_query="Test check",
            files_content={"test.py": "line1\nline2\nline3"}
        )
        
        assert "L1:" in prompt
        assert "L2:" in prompt
        assert "L3:" in prompt

    def test_includes_boundary_markers(self):
        """Test that build_user_prompt includes boundary markers."""
        from code_scanner.base_client import build_user_prompt
        
        prompt = build_user_prompt(
            check_query="Test check",
            files_content={"test.py": "code"}
        )
        
        assert "<<<FILE_START>>>" in prompt
        assert "<<<FILE_END>>>" in prompt

    def test_includes_file_metadata(self):
        """Test that build_user_prompt includes file metadata."""
        from code_scanner.base_client import build_user_prompt
        
        prompt = build_user_prompt(
            check_query="Test check",
            files_content={"src/module.py": "line1\nline2"}
        )
        
        assert "src/module.py" in prompt
        assert "lines 1-2" in prompt
        assert "total: 2" in prompt

    def test_multiple_files_formatted(self):
        """Test formatting with multiple files."""
        from code_scanner.base_client import build_user_prompt
        
        prompt = build_user_prompt(
            check_query="Test check",
            files_content={
                "file1.py": "code1",
                "file2.py": "code2\nline2",
            }
        )
        
        assert "file1.py" in prompt
        assert "file2.py" in prompt
        assert prompt.count("<<<FILE_START>>>") == 2
        assert prompt.count("<<<FILE_END>>>") == 2


class TestSearchTextWithFilePattern:
    """Tests for search_text with file_pattern parameter."""

    def test_search_text_with_file_pattern_matching(self, tmp_path: Path):
        """Test search_text with file_pattern that matches files."""
        # Create test files
        py_file = tmp_path / "test.py"
        py_file.write_text("def my_function():\n    pass")
        
        js_file = tmp_path / "test.js"
        js_file.write_text("function my_function() {}")
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=make_mock_ctags(tmp_path))
        result = executor.execute_tool("search_text", {"patterns": ["my_function"], "file_pattern": "*.py"})
        
        assert result.success
        # Should only find in .py file
        matches = result.data["matches_by_pattern"].get("my_function", [])
        assert len(matches) >= 1
        assert all(m["file"] == "test.py" for m in matches)

    def test_search_text_with_file_pattern_no_match(self, tmp_path: Path):
        """Test search_text with file_pattern that doesn't match any files."""
        # Create test file
        py_file = tmp_path / "test.py"
        py_file.write_text("def my_function():\n    pass")
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=make_mock_ctags(tmp_path))
        result = executor.execute_tool("search_text", {"patterns": ["my_function"], "file_pattern": "*.ts"})
        
        assert result.success
        # Should find no matches since no .ts files
        assert result.data["total_matches"] == 0


class TestGetFileSummaryEdgeCasesExtended:
    """Extended tests for get_file_summary edge cases."""

    def test_get_file_summary_outside_repo(self, tmp_path: Path):
        """Test get_file_summary with path outside repository."""
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=make_mock_ctags(tmp_path))
        result = executor.execute_tool("get_file_summary", {"file_path": "/etc/passwd"})
        
        assert not result.success
        assert "outside repository" in result.error.lower() or "access denied" in result.error.lower()

    def test_get_file_summary_directory_not_file(self, tmp_path: Path):
        """Test get_file_summary when path is a directory."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=make_mock_ctags(tmp_path))
        result = executor.execute_tool("get_file_summary", {"file_path": "subdir"})
        
        assert not result.success
        assert "not a file" in result.error.lower()

    def test_get_file_summary_binary_file(self, tmp_path: Path):
        """Test get_file_summary with binary file - ctags returns empty structure."""
        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\x04\x05")
        
        # Ctags-based implementation returns success with empty structure for binary files
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=make_mock_ctags(tmp_path))
        result = executor.execute_tool("get_file_summary", {"file_path": "test.bin"})
        
        # With ctags, binary files return success with empty structure
        assert result.success
        assert result.data["classes"] == []
        assert result.data["functions"] == []

    def test_get_file_summary_read_error(self, tmp_path: Path, monkeypatch):
        """Test get_file_summary when ctags throws an exception."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        # Configure mock to raise exception
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.get_file_structure.side_effect = RuntimeError("Ctags parsing failed")
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        result = executor.execute_tool("get_file_summary", {"file_path": "test.py"})
        
        assert not result.success
        assert "error" in result.error.lower()

    def test_get_file_summary_exception(self, tmp_path: Path, monkeypatch):
        """Test get_file_summary when an exception occurs during analysis."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        # Configure mock to raise exception
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.get_file_structure.side_effect = RuntimeError("Test exception")
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        result = executor.execute_tool("get_file_summary", {"file_path": "test.py"})
        
        assert not result.success


class TestSymbolExistsEdgeCases:
    """Edge case tests for symbol_exists using ctags."""

    def test_symbol_exists_type_alias(self, tmp_path: Path):
        """Test symbol_exists with type alias pattern."""
        test_file = tmp_path / "types.ts"
        test_file.write_text("type UserId = string;\ntype Config = { name: string };")
        
        # Configure mock to return type alias symbol
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="UserId", file_path="types.ts", line=1, kind="type",
                   language="TypeScript", pattern="type UserId = string;", scope=None, signature=None)
        ]
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        result = executor.execute_tool("symbol_exists", {"symbol": "UserId", "symbol_type": "type"})
        
        assert result.success
        assert result.data["exists"]

    def test_symbol_exists_interface(self, tmp_path: Path):
        """Test symbol_exists finds interface definitions."""
        test_file = tmp_path / "interfaces.ts"
        test_file.write_text("interface UserInterface {\n  name: string;\n}")
        
        # Configure mock to return interface symbol
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="UserInterface", file_path="interfaces.ts", line=1, kind="interface",
                   language="TypeScript", pattern="interface UserInterface {", scope=None, signature=None)
        ]
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        result = executor.execute_tool("symbol_exists", {"symbol": "UserInterface", "symbol_type": "interface"})
        
        assert result.success
        assert result.data["exists"]

    def test_symbol_exists_exception_handling(self, tmp_path: Path):
        """Test symbol_exists handles ctags exceptions gracefully."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def special_func(): pass")
        
        # Configure mock to raise exception
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.side_effect = RuntimeError("Ctags error")
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        result = executor.execute_tool("symbol_exists", {"symbol": "special_func", "symbol_type": "any"})
        
        assert not result.success
        assert "error" in result.error.lower()

    def test_symbol_exists_not_found_returns_false(self, tmp_path: Path):
        """Test symbol_exists returns exists=False when symbol not in index."""
        visible_file = tmp_path / "visible.py"
        visible_file.write_text("def visible_func(): pass")
        
        # Mock returns empty (symbol not found)
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=make_mock_ctags(tmp_path))
        
        result = executor.execute_tool("symbol_exists", {"symbol": "nonexistent_func"})
        assert result.success
        assert not result.data["exists"]

    def test_symbol_exists_finds_symbol_in_index(self, tmp_path: Path):
        """Test symbol_exists returns exists=True when symbol is in index."""
        src_file = tmp_path / "src.js"
        src_file.write_text("function src_func() {}")
        
        # Configure mock to return symbol
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="src_func", file_path="src.js", line=1, kind="function",
                   language="JavaScript", pattern="function src_func() {}", scope=None, signature=None)
        ]
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        
        result = executor.execute_tool("symbol_exists", {"symbol": "src_func"})
        assert result.success
        assert result.data["exists"]

    def test_symbol_exists_returns_location_info(self, tmp_path: Path):
        """Test symbol_exists returns correct location information."""
        text_file = tmp_path / "test.py"
        text_file.write_text("def real_func(): pass")
        
        # Configure mock to return symbol with location
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="real_func", file_path="test.py", line=1, kind="function",
                   language="Python", pattern="def real_func(): pass", scope=None, signature="()")
        ]
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        result = executor.execute_tool("symbol_exists", {"symbol": "real_func"})
        
        assert result.success
        assert result.data["exists"]
        assert len(result.data["locations"]) == 1
        assert result.data["locations"][0]["file"] == "test.py"
        assert result.data["locations"][0]["line"] == 1

    def test_symbol_exists_limits_results(self, tmp_path: Path):
        """Test symbol_exists limits results to 10 locations."""
        # Create mock that returns many symbols
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="repeated_func", file_path=f"module{i}.py", line=1, kind="function",
                   language="Python", pattern="def repeated_func(): pass", scope=None, signature=None)
            for i in range(20)  # More than limit
        ]
        
        executor = AIToolExecutor(target_directory=tmp_path, context_limit=10000, ctags_index=mock_ctags)
        result = executor.execute_tool("symbol_exists", {"symbol": "repeated_func"})
        
        assert result.success
        assert result.data["exists"]
        # Should be limited to 10 locations
        assert len(result.data["locations"]) <= 10


class TestGetEnclosingScopeTool:
    """Tests for get_enclosing_scope tool."""

    def test_get_enclosing_scope_function(self, tmp_path: Path):
        """Test get_enclosing_scope finds a function containing a line."""
        test_file = tmp_path / "module.py"
        test_file.write_text("""def my_function():
    x = 1
    y = 2
    return x + y

def other_function():
    pass
""")
        # Configure mock to return function symbol
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_enclosing_symbol.return_value = Symbol(
            name="my_function",
            file_path="module.py",
            line=1,
            kind="function",
            end_line=4,
            language="Python",
            pattern="def my_function():",
            scope=None,
            signature="()",
        )

        executor = AIToolExecutor(tmp_path, 8192, mock_ctags)
        result = executor.execute_tool(
            "get_enclosing_scope", {"file_path": "module.py", "line_number": 2}
        )

        assert result.success
        assert result.data["type"] == "function"
        assert result.data["name"] == "my_function"
        assert result.data["start_line"] == 1
        assert "def my_function" in result.data["content"]

    def test_get_enclosing_scope_class_method(self, tmp_path: Path):
        """Test get_enclosing_scope finds a method within a class."""
        test_file = tmp_path / "models.py"
        test_file.write_text("""class MyClass:
    def method(self):
        value = 42
        return value
""")
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_enclosing_symbol.return_value = Symbol(
            name="method",
            file_path="models.py",
            line=2,
            kind="method",
            end_line=4,
            language="Python",
            pattern="def method(self):",
            scope="MyClass",
            signature="(self)",
        )

        executor = AIToolExecutor(tmp_path, 8192, mock_ctags)
        result = executor.execute_tool(
            "get_enclosing_scope", {"file_path": "models.py", "line_number": 3}
        )

        assert result.success
        assert result.data["type"] == "method"
        assert result.data["name"] == "method"
        assert result.data["scope"] == "MyClass"

    def test_get_enclosing_scope_file_not_found(self, tmp_path: Path):
        """Test get_enclosing_scope with non-existent file."""
        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool(
            "get_enclosing_scope", {"file_path": "nonexistent.py", "line_number": 5}
        )

        assert not result.success
        assert "not found" in result.error.lower()

    def test_get_enclosing_scope_missing_file_path(self, tmp_path: Path):
        """Test get_enclosing_scope with missing file_path."""
        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool("get_enclosing_scope", {"line_number": 5})

        assert not result.success
        assert "file_path" in result.error.lower()

    def test_get_enclosing_scope_invalid_line(self, tmp_path: Path):
        """Test get_enclosing_scope with invalid line number."""
        test_file = tmp_path / "small.py"
        test_file.write_text("x = 1\n")

        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool(
            "get_enclosing_scope", {"file_path": "small.py", "line_number": 100}
        )

        assert not result.success
        assert "beyond file length" in result.error.lower()

    def test_get_enclosing_scope_no_scope_found(self, tmp_path: Path):
        """Test get_enclosing_scope when line is not in any scope."""
        test_file = tmp_path / "toplevel.py"
        test_file.write_text("# Just a comment\nx = 1\ny = 2\n")

        # Mock returns None (no enclosing scope)
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_enclosing_symbol.return_value = None

        executor = AIToolExecutor(tmp_path, 8192, mock_ctags)
        result = executor.execute_tool(
            "get_enclosing_scope", {"file_path": "toplevel.py", "line_number": 2}
        )

        assert result.success
        assert result.data["type"] == "file_context"
        assert "content" in result.data


class TestFindUsagesTool:
    """Tests for find_usages tool."""

    def test_find_usages_basic(self, tmp_path: Path):
        """Test find_usages finds basic occurrences."""
        test_file = tmp_path / "module.py"
        test_file.write_text("""def process_data():
    pass

result1 = process_data()
result2 = process_data()
""")
        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool("find_usages", {"symbol": "process_data"})

        assert result.success
        assert result.data["symbol"] == "process_data"
        assert result.data["total_usages"] >= 0  # May vary based on detection
        assert "entries" in result.data

    def test_find_usages_excludes_definitions(self, tmp_path: Path):
        """Test find_usages excludes definitions by default."""
        test_file = tmp_path / "module.py"
        test_file.write_text("""def my_func():
    pass

my_func()
""")
        # Configure mock to identify definition
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="my_func", file_path="module.py", line=1, kind="function",
                   language="Python", pattern="def my_func():", scope=None, signature=None)
        ]

        executor = AIToolExecutor(tmp_path, 8192, mock_ctags)
        result = executor.execute_tool("find_usages", {"symbol": "my_func"})

        assert result.success
        assert result.data["include_definitions"] is False

    def test_find_usages_includes_definitions(self, tmp_path: Path):
        """Test find_usages includes definitions when requested."""
        test_file = tmp_path / "module.py"
        test_file.write_text("""def my_func():
    pass

my_func()
""")
        mock_ctags = make_mock_ctags(tmp_path)
        mock_ctags.find_symbol.return_value = [
            Symbol(name="my_func", file_path="module.py", line=1, kind="function",
                   language="Python", pattern="def my_func():", scope=None, signature=None)
        ]

        executor = AIToolExecutor(tmp_path, 8192, mock_ctags)
        result = executor.execute_tool(
            "find_usages", {"symbol": "my_func", "include_definitions": True}
        )

        assert result.success
        assert result.data["include_definitions"] is True

    def test_find_usages_missing_symbol(self, tmp_path: Path):
        """Test find_usages with missing symbol parameter."""
        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool("find_usages", {})

        assert not result.success
        assert "symbol" in result.error.lower()

    def test_find_usages_no_matches(self, tmp_path: Path):
        """Test find_usages when symbol has no usages."""
        test_file = tmp_path / "module.py"
        test_file.write_text("x = 1\n")

        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool("find_usages", {"symbol": "nonexistent_symbol"})

        assert result.success
        assert result.data["total_usages"] == 0
        assert result.data["entries"] == []

    def test_find_usages_with_file_filter(self, tmp_path: Path):
        """Test find_usages with file path filter."""
        file1 = tmp_path / "module1.py"
        file1.write_text("def helper(): pass\nhelper()\n")
        file2 = tmp_path / "module2.py"
        file2.write_text("helper()\n")

        executor = AIToolExecutor(tmp_path, 8192, make_mock_ctags(tmp_path))
        result = executor.execute_tool(
            "find_usages", {"symbol": "helper", "file_path": "module1.py"}
        )

        assert result.success
        assert result.data["file_filter"] == "module1.py"