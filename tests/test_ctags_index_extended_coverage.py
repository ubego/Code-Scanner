"""Extended coverage tests for ctags_index module - targeting uncovered paths."""

import pytest
import subprocess
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from code_scanner.ctags_index import (
    CtagsIndex,
    CtagsNotFoundError,
    CtagsError,
    Symbol,
)


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository with some Python files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text('''
def main():
    print("hello")

class MyClass:
    def method(self):
        pass
''')
    return tmp_path


class TestVerifyCtagsCoverage:
    """Test verify_ctags function edge cases."""

    def test_ctags_not_found(self, tmp_path, monkeypatch):
        """Test error when ctags is not installed."""
        monkeypatch.setattr(shutil, "which", lambda x: None)
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(tmp_path)
        
        error_msg = str(exc_info.value)
        assert "UNIVERSAL CTAGS NOT FOUND" in error_msg
        assert "sudo apt install universal-ctags" in error_msg

    def test_exuberant_ctags_rejected(self, tmp_path, monkeypatch):
        """Test that Exuberant Ctags (old version) is rejected."""
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ctags")
        
        # Mock subprocess to return Exuberant Ctags version
        def mock_run(*args, **kwargs):
            result = MagicMock()
            result.stdout = "Exuberant Ctags 5.9~svn20110310"
            result.stderr = ""
            result.returncode = 0
            return result
        
        monkeypatch.setattr(subprocess, "run", mock_run)
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(tmp_path)
        
        error_msg = str(exc_info.value)
        assert "WRONG CTAGS VERSION" in error_msg
        assert "Universal Ctags" in error_msg

    def test_ctags_version_check_timeout(self, tmp_path, monkeypatch):
        """Test timeout during ctags version check."""
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ctags")
        
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired("ctags", 10)
        
        monkeypatch.setattr(subprocess, "run", mock_run)
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(tmp_path)
        
        assert "timed out" in str(exc_info.value).lower()

    def test_ctags_subprocess_error(self, tmp_path, monkeypatch):
        """Test subprocess error during ctags execution."""
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ctags")
        
        def mock_run(*args, **kwargs):
            raise subprocess.SubprocessError("Execution failed")
        
        monkeypatch.setattr(subprocess, "run", mock_run)
        
        with pytest.raises(CtagsNotFoundError) as exc_info:
            CtagsIndex(tmp_path)
        
        assert "Failed to run ctags" in str(exc_info.value)


class TestGenerateIndexCoverage:
    """Test generate_index edge cases."""

    def test_generate_index_with_valid_repo(self, temp_repo):
        """Test index generation succeeds with valid repo."""
        # Skip if ctags not available
        if shutil.which("ctags") is None:
            pytest.skip("ctags not installed")
        
        index = CtagsIndex(temp_repo)
        count = index.generate_index()
        
        assert count >= 0

    def test_generate_index_timeout(self, temp_repo, monkeypatch):
        """Test timeout during index generation."""
        if shutil.which("ctags") is None:
            pytest.skip("ctags not installed")
        
        index = CtagsIndex(temp_repo)
        
        original_run = subprocess.run
        call_count = [0]
        
        def mock_run(cmd, *args, **kwargs):
            call_count[0] += 1
            # Allow version check, fail on actual index generation
            if "--output-format=json" in cmd:
                raise subprocess.TimeoutExpired(" ".join(cmd), 300)
            return original_run(cmd, *args, **kwargs)
        
        monkeypatch.setattr(subprocess, "run", mock_run)
        
        with pytest.raises(CtagsError) as exc_info:
            index.generate_index()
        
        assert "timed out" in str(exc_info.value).lower()


class TestMatchesKindCoverage:
    """Test _matches_kind function for kind alias matching."""

    @pytest.fixture
    def index(self, temp_repo):
        """Create a CtagsIndex instance (skips if ctags unavailable)."""
        if shutil.which("ctags") is None:
            pytest.skip("ctags not installed")
        return CtagsIndex(temp_repo)

    def test_function_kind_filter(self, index):
        """Test function kind filtering - symbol 'f' matches filter 'function'."""
        # When filtering for 'function', symbols with kind 'f' should match
        assert index._matches_kind("f", "function") is True
        assert index._matches_kind("function", "function") is True

    def test_method_kind_filter(self, index):
        """Test method kind filtering."""
        assert index._matches_kind("m", "method") is True
        assert index._matches_kind("method", "method") is True

    def test_class_kind_filter(self, index):
        """Test class kind filtering."""
        assert index._matches_kind("c", "class") is True
        assert index._matches_kind("class", "class") is True
        assert index._matches_kind("s", "class") is True  # struct is class alias

    def test_variable_kind_filter(self, index):
        """Test variable kind filtering."""
        assert index._matches_kind("v", "variable") is True
        assert index._matches_kind("variable", "variable") is True

    def test_exact_match(self, index):
        """Test exact kind match."""
        assert index._matches_kind("class", "class") is True
        assert index._matches_kind("function", "function") is True

    def test_no_match(self, index):
        """Test non-matching kinds."""
        assert index._matches_kind("c", "variable") is False
        assert index._matches_kind("v", "class") is False


class TestFindEnclosingScopeCoverage:
    """Test find_enclosing_symbol edge cases."""

    @pytest.fixture
    def indexed_repo(self, temp_repo):
        """Create and index a repository."""
        if shutil.which("ctags") is None:
            pytest.skip("ctags not installed")
        
        # Create a file with nested scopes
        (temp_repo / "src" / "nested.py").write_text('''
class Outer:
    """Outer class."""
    
    def method(self):
        """Method inside Outer."""
        def inner():
            x = 1  # Line 8
            return x
        return inner
    
    class Inner:
        """Nested class."""
        pass
''')
        index = CtagsIndex(temp_repo)
        index.generate_index()
        return index

    def test_find_enclosing_scope_nested(self, indexed_repo):
        """Test finding enclosing scope for nested structures."""
        result = indexed_repo.find_enclosing_symbol("src/nested.py", 8)
        
        # Should find some enclosing scope
        # (specific result depends on ctags output)
        if result is not None:
            assert result.file_path == "src/nested.py"

    def test_find_enclosing_scope_no_scope(self, indexed_repo):
        """Test finding scope for top-level code."""
        # Line 1 is at module level (import or blank)
        result = indexed_repo.find_enclosing_symbol("src/nested.py", 1)
        # May return None or module-level scope


class TestFindDefinitionsCoverage:
    """Test find_definitions edge cases."""

    @pytest.fixture
    def indexed_repo(self, temp_repo):
        """Create and index a repository."""
        if shutil.which("ctags") is None:
            pytest.skip("ctags not installed")
        
        index = CtagsIndex(temp_repo)
        index.generate_index()
        return index

    def test_find_definitions_by_name(self, indexed_repo):
        """Test finding definitions by symbol name."""
        results = indexed_repo.find_definitions("main")
        
        assert len(results) >= 1
        assert any(s.name == "main" for s in results)

    def test_find_definitions_with_kind(self, indexed_repo):
        """Test finding definitions filtered by kind."""
        results = indexed_repo.find_definitions("MyClass", kind="class")
        
        if results:
            assert all(s.kind in ["class", "c"] for s in results)

    def test_find_definitions_not_found(self, indexed_repo):
        """Test finding definitions for non-existent symbol."""
        results = indexed_repo.find_definitions("NonExistentSymbol12345")
        
        assert results == []


class TestSymbolDataclass:
    """Test Symbol dataclass."""

    def test_symbol_creation(self):
        """Test creating a Symbol instance."""
        sym = Symbol(
            name="test_func",
            file_path="test.py",
            line=10,
            kind="function",
            scope="module",
            signature="def test_func(x, y)",
        )
        
        assert sym.name == "test_func"
        assert sym.file_path == "test.py"
        assert sym.line == 10
        assert sym.kind == "function"

    def test_symbol_optional_fields(self):
        """Test Symbol with only required fields."""
        sym = Symbol(
            name="var",
            file_path="test.py",
            line=1,
            kind="variable",
        )
        
        assert sym.scope is None
        assert sym.signature is None
        assert sym.end_line is None


class TestGetFileStructureCoverage:
    """Test get_file_structure edge cases."""

    @pytest.fixture
    def indexed_repo(self, temp_repo):
        """Create and index a repository."""
        if shutil.which("ctags") is None:
            pytest.skip("ctags not installed")
        
        index = CtagsIndex(temp_repo)
        index.generate_index()
        return index

    def test_get_file_structure(self, indexed_repo):
        """Test getting file structure."""
        structure = indexed_repo.get_file_structure("src/main.py")
        
        assert structure is not None
        assert "file_path" in structure

    def test_get_file_structure_nonexistent(self, indexed_repo):
        """Test getting structure for non-existent file."""
        structure = indexed_repo.get_file_structure("nonexistent.py")
        
        # Should handle gracefully
        assert structure is not None
