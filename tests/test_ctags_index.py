"""Tests for ctags_index module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from code_scanner.ctags_index import (
    CtagsIndex,
    CtagsNotFoundError,
    CtagsError,
    Symbol,
    KIND_MAP,
)


class TestSymbol:
    """Tests for Symbol dataclass."""

    def test_symbol_creation(self):
        """Test basic Symbol creation."""
        symbol = Symbol(
            name="my_func",
            file_path="./src/main.py",
            line=10,
            kind="function",
        )
        assert symbol.name == "my_func"
        assert symbol.file_path == "./src/main.py"
        assert symbol.line == 10
        assert symbol.kind == "function"
        assert symbol.scope is None
        assert symbol.signature is None

    def test_symbol_with_all_fields(self):
        """Test Symbol with all optional fields."""
        symbol = Symbol(
            name="method",
            file_path="./src/class.py",
            line=20,
            kind="method",
            scope="MyClass",
            scope_kind="class",
            signature="(self, arg1, arg2)",
            access="public",
            language="Python",
            pattern="/^    def method/",
            extras={"typeref": "int"},
        )
        assert symbol.scope == "MyClass"
        assert symbol.scope_kind == "class"
        assert symbol.signature == "(self, arg1, arg2)"
        assert symbol.access == "public"
        assert symbol.language == "Python"
        assert symbol.pattern == "/^    def method/"
        assert symbol.extras == {"typeref": "int"}

    def test_symbol_from_ctags_json(self):
        """Test creating Symbol from ctags JSON output."""
        ctags_data = {
            "_type": "tag",
            "name": "calculate",
            "path": "./math.py",
            "line": 5,
            "kind": "f",
            "scope": "Calculator",
            "scopeKind": "c",
            "signature": "(a, b)",
            "access": "public",
            "language": "Python",
            "pattern": "/^def calculate/",
        }
        symbol = Symbol.from_ctags_json(ctags_data)
        assert symbol.name == "calculate"
        assert symbol.file_path == "./math.py"
        assert symbol.line == 5
        assert symbol.kind == "f"
        assert symbol.scope == "Calculator"
        assert symbol.scope_kind == "c"
        assert symbol.signature == "(a, b)"

    def test_symbol_from_ctags_json_minimal(self):
        """Test Symbol from minimal ctags output."""
        ctags_data = {
            "name": "var",
            "path": "./test.py",
            "line": 1,
        }
        symbol = Symbol.from_ctags_json(ctags_data)
        assert symbol.name == "var"
        assert symbol.file_path == "./test.py"
        assert symbol.line == 1
        assert symbol.kind == "unknown"

    def test_symbol_from_ctags_json_extra_fields(self):
        """Test that extra fields are captured."""
        ctags_data = {
            "name": "func",
            "path": "./test.py",
            "line": 10,
            "kind": "f",
            "custom_field": "value",
            "another": 123,
        }
        symbol = Symbol.from_ctags_json(ctags_data)
        assert symbol.extras == {"custom_field": "value", "another": 123}


class TestKindMap:
    """Tests for KIND_MAP constant."""

    def test_common_kinds_mapped(self):
        """Test that common kind abbreviations are mapped."""
        assert KIND_MAP["f"] == "function"
        assert KIND_MAP["c"] == "class"
        assert KIND_MAP["m"] == "method"
        assert KIND_MAP["v"] == "variable"

    def test_all_kinds_are_strings(self):
        """Test that all mapped values are strings."""
        for key, value in KIND_MAP.items():
            assert isinstance(key, str)
            assert isinstance(value, str)


class TestCtagsIndexInit:
    """Tests for CtagsIndex initialization."""

    @patch("shutil.which")
    def test_ctags_not_found(self, mock_which):
        """Test error when ctags is not installed."""
        mock_which.return_value = None
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(Path("/tmp/repo"))
        
        assert "UNIVERSAL CTAGS NOT FOUND" in str(exc_info.value)
        assert "sudo apt install" in str(exc_info.value)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_wrong_ctags_version(self, mock_run, mock_which):
        """Test error when Exuberant Ctags is installed instead."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Exuberant Ctags 5.8",
            stderr="",
            returncode=0,
        )
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(Path("/tmp/repo"))
        
        assert "WRONG CTAGS VERSION" in str(exc_info.value)
        assert "Universal Ctags" in str(exc_info.value)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_ctags_version_check_timeout(self, mock_run, mock_which):
        """Test error when ctags version check times out."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ctags", timeout=10)
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(Path("/tmp/repo"))
        
        assert "timed out" in str(exc_info.value).lower()

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_ctags_version_check_subprocess_error(self, mock_run, mock_which):
        """Test error when ctags subprocess fails."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.side_effect = subprocess.SubprocessError("Process error")
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(Path("/tmp/repo"))
        
        assert "Failed to run ctags" in str(exc_info.value)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_successful_init(self, mock_run, mock_which):
        """Test successful initialization with Universal Ctags."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index = CtagsIndex(Path("/tmp/repo"))
        
        assert index.repo_path == Path("/tmp/repo").resolve()
        assert index._ctags_path == "/usr/bin/ctags"
        assert index._is_indexed is False


class TestCtagsIndexGenerateIndex:
    """Tests for CtagsIndex.generate_index method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_generate_index_success(self, mock_run, mock_which):
        """Test successful index generation."""
        mock_which.return_value = "/usr/bin/ctags"
        
        # First call: version check
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        # Second call: actual indexing
        ctags_output = (
            '{"_type": "tag", "name": "my_func", "path": "./test.py", "line": 5, "kind": "f"}\n'
            '{"_type": "tag", "name": "MyClass", "path": "./test.py", "line": 10, "kind": "c"}\n'
        )
        index_result = MagicMock(
            stdout=ctags_output,
            stderr="",
            returncode=0,
        )
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        count = index.generate_index()
        
        assert count == 2
        assert index.is_indexed is True
        assert index.symbol_count == 2
        assert index.file_count == 1

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_generate_index_skips_non_tag_entries(self, mock_run, mock_which):
        """Test that non-tag entries are skipped."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        # Include metadata entries
        ctags_output = (
            '{"_type": "program", "name": "ctags", "version": "6.0.0"}\n'
            '{"_type": "tag", "name": "func", "path": "./test.py", "line": 1, "kind": "f"}\n'
            '{"_type": "ptag", "name": "!_TAG_KIND", "path": "meta"}\n'
        )
        index_result = MagicMock(
            stdout=ctags_output,
            stderr="",
            returncode=0,
        )
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        count = index.generate_index()
        
        assert count == 1  # Only the tag entry

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_generate_index_handles_malformed_json(self, mock_run, mock_which):
        """Test that malformed JSON lines are skipped."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "func", "path": "./test.py", "line": 1, "kind": "f"}\n'
            'not valid json\n'
            '{"_type": "tag", "name": "other", "path": "./test.py", "line": 5, "kind": "f"}\n'
        )
        index_result = MagicMock(
            stdout=ctags_output,
            stderr="",
            returncode=0,
        )
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        count = index.generate_index()
        
        assert count == 2  # Malformed line skipped

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_generate_index_ctags_fails(self, mock_run, mock_which):
        """Test error when ctags command fails."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index_result = MagicMock(
            stdout="",
            stderr="Error: something went wrong",
            returncode=1,
        )
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        
        with pytest.raises(CtagsError) as exc_info:
            index.generate_index()
        
        assert "exit code 1" in str(exc_info.value)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_generate_index_timeout(self, mock_run, mock_which):
        """Test error when ctags times out."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        mock_run.side_effect = [version_result, subprocess.TimeoutExpired(cmd="ctags", timeout=300)]
        
        index = CtagsIndex(Path("/tmp/repo"))
        
        with pytest.raises(CtagsError) as exc_info:
            index.generate_index()
        
        assert "timed out" in str(exc_info.value).lower()


class TestCtagsIndexFindSymbol:
    """Tests for CtagsIndex.find_symbol method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_symbol_not_indexed(self, mock_run, mock_which):
        """Test find_symbol returns empty when not indexed."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index = CtagsIndex(Path("/tmp/repo"))
        result = index.find_symbol("my_func")
        
        assert result == []

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_symbol_case_insensitive(self, mock_run, mock_which):
        """Test find_symbol is case-insensitive by default."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = '{"_type": "tag", "name": "MyFunc", "path": "./test.py", "line": 5, "kind": "f"}\n'
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.find_symbol("myfunc")
        assert len(result) == 1
        assert result[0].name == "MyFunc"

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_symbol_case_sensitive(self, mock_run, mock_which):
        """Test find_symbol with case-sensitive matching."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = '{"_type": "tag", "name": "MyFunc", "path": "./test.py", "line": 5, "kind": "f"}\n'
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        # Case-sensitive search - should find
        result = index.find_symbol("MyFunc", case_sensitive=True)
        assert len(result) == 1
        
        # Case-sensitive search - wrong case
        result = index.find_symbol("myfunc", case_sensitive=True)
        assert len(result) == 0

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_symbol_with_kind_filter(self, mock_run, mock_which):
        """Test find_symbol with kind filter."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "Test", "path": "./test.py", "line": 5, "kind": "c"}\n'
            '{"_type": "tag", "name": "test", "path": "./test.py", "line": 10, "kind": "f"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        # Find only classes
        result = index.find_symbol("test", kind="class")
        assert len(result) == 1
        assert result[0].kind == "c"


class TestCtagsIndexGetSymbolsInFile:
    """Tests for CtagsIndex.get_symbols_in_file method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_symbols_in_file(self, mock_run, mock_which):
        """Test getting symbols from a specific file."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "func1", "path": "./src/main.py", "line": 5, "kind": "f"}\n'
            '{"_type": "tag", "name": "func2", "path": "./src/main.py", "line": 10, "kind": "f"}\n'
            '{"_type": "tag", "name": "other", "path": "./src/other.py", "line": 1, "kind": "f"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.get_symbols_in_file("src/main.py")
        assert len(result) == 2
        assert result[0].line < result[1].line  # Sorted by line

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_symbols_in_file_not_found(self, mock_run, mock_which):
        """Test getting symbols from non-existent file."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = '{"_type": "tag", "name": "func", "path": "./test.py", "line": 5, "kind": "f"}\n'
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.get_symbols_in_file("nonexistent.py")
        assert result == []


class TestCtagsIndexFindSymbolsByPattern:
    """Tests for CtagsIndex.find_symbols_by_pattern method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_symbols_by_pattern_wildcard(self, mock_run, mock_which):
        """Test finding symbols with wildcard pattern."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "test_func1", "path": "./test.py", "line": 5, "kind": "f"}\n'
            '{"_type": "tag", "name": "test_func2", "path": "./test.py", "line": 10, "kind": "f"}\n'
            '{"_type": "tag", "name": "other_func", "path": "./test.py", "line": 15, "kind": "f"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.find_symbols_by_pattern("test_*")
        assert len(result) == 2
        assert all(s.name.startswith("test_") for s in result)


class TestCtagsIndexGetClassMembers:
    """Tests for CtagsIndex.get_class_members method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_class_members(self, mock_run, mock_which):
        """Test getting class members."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "MyClass", "path": "./test.py", "line": 1, "kind": "c"}\n'
            '{"_type": "tag", "name": "__init__", "path": "./test.py", "line": 2, "kind": "m", "scope": "MyClass"}\n'
            '{"_type": "tag", "name": "method", "path": "./test.py", "line": 5, "kind": "m", "scope": "MyClass"}\n'
            '{"_type": "tag", "name": "other_method", "path": "./test.py", "line": 10, "kind": "m", "scope": "OtherClass"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.get_class_members("MyClass")
        assert len(result) == 2
        assert all(s.scope == "MyClass" for s in result)


class TestCtagsIndexGetFileStructure:
    """Tests for CtagsIndex.get_file_structure method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_file_structure(self, mock_run, mock_which):
        """Test getting file structure."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "MyClass", "path": "./test.py", "line": 5, "kind": "c"}\n'
            '{"_type": "tag", "name": "__init__", "path": "./test.py", "line": 6, "kind": "m", "scope": "MyClass"}\n'
            '{"_type": "tag", "name": "helper_func", "path": "./test.py", "line": 15, "kind": "f"}\n'
            '{"_type": "tag", "name": "CONSTANT", "path": "./test.py", "line": 1, "kind": "v"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.get_file_structure("test.py")
        
        assert result["file_path"] == "test.py"
        assert len(result["classes"]) == 1
        assert result["classes"][0]["name"] == "MyClass"
        assert len(result["functions"]) == 1
        assert result["functions"][0]["name"] == "helper_func"
        assert len(result["variables"]) == 1

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_file_structure_empty(self, mock_run, mock_which):
        """Test file structure for file with no symbols."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index_result = MagicMock(stdout="", stderr="", returncode=0)
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.get_file_structure("empty.py")
        
        assert result["classes"] == []
        assert result["functions"] == []
        assert result["variables"] == []


class TestCtagsIndexGetStats:
    """Tests for CtagsIndex.get_stats method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_stats_not_indexed(self, mock_run, mock_which):
        """Test stats before indexing."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index = CtagsIndex(Path("/tmp/repo"))
        stats = index.get_stats()
        
        assert stats["indexed"] is False

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_stats_after_indexing(self, mock_run, mock_which):
        """Test stats after indexing."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "func1", "path": "./a.py", "line": 1, "kind": "f", "language": "Python"}\n'
            '{"_type": "tag", "name": "func2", "path": "./b.py", "line": 1, "kind": "f", "language": "Python"}\n'
            '{"_type": "tag", "name": "Class1", "path": "./a.py", "line": 5, "kind": "c", "language": "Python"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        stats = index.get_stats()
        
        assert stats["indexed"] is True
        assert stats["total_symbols"] == 3
        assert stats["total_files"] == 2
        assert "by_kind" in stats
        assert "by_language" in stats


class TestCtagsIndexMatchesKind:
    """Tests for CtagsIndex._matches_kind method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_matches_kind_direct_match(self, mock_run, mock_which):
        """Test direct kind matching."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index = CtagsIndex(Path("/tmp/repo"))
        
        assert index._matches_kind("function", "function") is True
        assert index._matches_kind("Function", "function") is True
        assert index._matches_kind("FUNCTION", "function") is True

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_matches_kind_abbreviation(self, mock_run, mock_which):
        """Test kind abbreviation matching."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index = CtagsIndex(Path("/tmp/repo"))
        
        assert index._matches_kind("f", "function") is True
        assert index._matches_kind("c", "class") is True
        assert index._matches_kind("m", "method") is True

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_matches_kind_aliases(self, mock_run, mock_which):
        """Test kind aliases."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index = CtagsIndex(Path("/tmp/repo"))
        
        # Method can match function filter
        assert index._matches_kind("method", "function") is True
        # Struct can match class filter
        assert index._matches_kind("struct", "class") is True

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_matches_kind_empty(self, mock_run, mock_which):
        """Test empty kind matching returns True."""
        mock_which.return_value = "/usr/bin/ctags"
        mock_run.return_value = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        index = CtagsIndex(Path("/tmp/repo"))
        
        assert index._matches_kind("", "function") is True
        assert index._matches_kind("function", "") is True


class TestCtagsIndexGetSymbolsByKind:
    """Tests for CtagsIndex.get_symbols_by_kind method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_get_symbols_by_kind(self, mock_run, mock_which):
        """Test getting all symbols of a specific kind."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = (
            '{"_type": "tag", "name": "func1", "path": "./a.py", "line": 1, "kind": "f"}\n'
            '{"_type": "tag", "name": "Class1", "path": "./a.py", "line": 5, "kind": "c"}\n'
            '{"_type": "tag", "name": "func2", "path": "./b.py", "line": 1, "kind": "f"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        functions = index.get_symbols_by_kind("function")
        assert len(functions) == 2
        
        classes = index.get_symbols_by_kind("class")
        assert len(classes) == 1


class TestCtagsIndexFindDefinitions:
    """Tests for CtagsIndex.find_definitions method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_definitions(self, mock_run, mock_which):
        """Test finding definitions."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(
            stdout="Universal Ctags 6.0.0",
            stderr="",
            returncode=0,
        )
        
        ctags_output = '{"_type": "tag", "name": "my_func", "path": "./test.py", "line": 5, "kind": "f"}\n'
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        result = index.find_definitions("my_func")
        assert len(result) == 1
        assert result[0].name == "my_func"


class TestCtagsIndexFindEnclosingSymbol:
    """Tests for CtagsIndex.find_enclosing_symbol method."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_enclosing_symbol_basic(self, mock_run, mock_which):
        """Test finding enclosing symbol for simple function."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(stdout="Universal Ctags 6.0.0", stderr="", returncode=0)
        
        # Function defined at line 5, ends at line 10
        ctags_output = (
            '{"_type": "tag", "name": "my_func", "path": "./test.py", "line": 5, "kind": "f", "end": 10}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        # Line 7 is inside
        result = index.find_enclosing_symbol("test.py", 7)
        assert result is not None
        assert result.name == "my_func"
        
        # Line 12 is outside
        result = index.find_enclosing_symbol("test.py", 12)
        assert result is None

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_enclosing_symbol_nested(self, mock_run, mock_which):
        """Test finding enclosing symbol specifically picks innermost."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(stdout="Universal Ctags 6.0.0", stderr="", returncode=0)
        
        # Class contains method
        ctags_output = (
            '{"_type": "tag", "name": "MyClass", "path": "./test.py", "line": 1, "kind": "c", "end": 20}\n'
            '{"_type": "tag", "name": "method", "path": "./test.py", "line": 5, "kind": "m", "end": 10}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        # Inside method (line 7) - should be method is innermost
        result = index.find_enclosing_symbol("test.py", 7)
        assert result is not None
        assert result.name == "method"
        
        # Inside class but outside method (line 15)
        result = index.find_enclosing_symbol("test.py", 15)
        assert result is not None
        assert result.name == "MyClass"

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_find_enclosing_symbol_no_end_line(self, mock_run, mock_which):
        """Test behavior when ctags doesn't provide end lines."""
        mock_which.return_value = "/usr/bin/ctags"
        
        version_result = MagicMock(stdout="Universal Ctags 6.0.0", stderr="", returncode=0)
        
        ctags_output = (
            '{"_type": "tag", "name": "func1", "path": "./test.py", "line": 5, "kind": "f"}\n'
            '{"_type": "tag", "name": "func2", "path": "./test.py", "line": 15, "kind": "f"}\n'
        )
        index_result = MagicMock(stdout=ctags_output, stderr="", returncode=0)
        
        mock_run.side_effect = [version_result, index_result]
        
        index = CtagsIndex(Path("/tmp/repo"))
        index.generate_index()
        
        # Should fallback to checking if line is after start
        # Without explicit end, it assumes validity until next symbol? 
        # Actually logic is: if no end_line, it's considered valid if line >= line
        # But find_enclosing_symbol implementation filters by scope range.
        # If end_line is None, the current implementation skips it or treats it as strictly checking start.
        # Let's verify implementation logic: 
        # "if s.end_line and not (s.line <= line_number <= s.end_line): continue"
        # "if not s.end_line and s.line > line_number: continue"
        # So if no end line, it matches anything after start line in the file.
        
        # Line 7 is after func1 start (5) - should match func1
        # But wait, func2 starts at 15. The implementation sorts by line number and picks last one <= line_number?
        # Implementation says: "closest = None... for s in symbols: ... if s.line <= line_number: closest = s"
        # So "last" symbol that starts before line_number is the inner-most candidate if spans are not explicit.
        
        result = index.find_enclosing_symbol("test.py", 7)
        assert result is not None
        assert result.name == "func1"
        
        result = index.find_enclosing_symbol("test.py", 20)
        assert result is not None
        assert result.name == "func2"

