"""Tests for the unified FileFilter class."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from code_scanner.file_filter import FileFilter


class TestFileFilterBasic:
    """Basic FileFilter functionality tests."""

    def test_init_with_defaults(self, tmp_path):
        """Test FileFilter initializes with default values."""
        filter = FileFilter(repo_path=tmp_path)
        
        assert filter.repo_path == tmp_path
        assert filter.scanner_files == set()
        assert filter.config_patterns == []

    def test_init_with_scanner_files(self, tmp_path):
        """Test FileFilter with scanner files."""
        scanner_files = {"results.md", "scanner.log"}
        filter = FileFilter(
            repo_path=tmp_path,
            scanner_files=scanner_files,
        )
        
        assert filter.scanner_files == scanner_files

    def test_init_with_config_patterns(self, tmp_path):
        """Test FileFilter with config ignore patterns."""
        patterns = ["*.md", "*.txt", "*.json"]
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=patterns,
        )
        
        assert filter.config_patterns == patterns


class TestFileFilterShouldSkip:
    """Tests for should_skip method."""

    def test_skip_scanner_file_exact_match(self, tmp_path):
        """Scanner files are skipped (exact match)."""
        filter = FileFilter(
            repo_path=tmp_path,
            scanner_files={"results.md", "scanner.log"},
        )
        
        should_skip, reason = filter.should_skip("results.md")
        assert should_skip is True
        assert reason == "scanner_file"

    def test_skip_scanner_file_basename_match(self, tmp_path):
        """Scanner files are skipped (basename match in path)."""
        filter = FileFilter(
            repo_path=tmp_path,
            scanner_files={"results.md"},
        )
        
        # Even if path contains directory, basename match should work
        should_skip, reason = filter.should_skip("subdir/results.md")
        assert should_skip is True
        assert reason == "scanner_file"

    def test_skip_config_pattern_match(self, tmp_path):
        """Files matching config patterns are skipped."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["*.md", "*.txt"],
            load_gitignore=False,
        )
        
        should_skip, reason = filter.should_skip("README.md")
        assert should_skip is True
        assert "config_pattern" in reason
        assert "*.md" in reason

    def test_skip_config_pattern_txt(self, tmp_path):
        """TXT files matching config patterns are skipped."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["*.md", "*.txt"],
            load_gitignore=False,
        )
        
        should_skip, reason = filter.should_skip("notes.txt")
        assert should_skip is True
        assert "*.txt" in reason

    def test_no_skip_unmatched_file(self, tmp_path):
        """Files not matching any pattern are not skipped."""
        filter = FileFilter(
            repo_path=tmp_path,
            scanner_files={"results.md"},
            config_ignore_patterns=["*.md", "*.txt"],
            load_gitignore=False,
        )
        
        should_skip, reason = filter.should_skip("main.cpp")
        assert should_skip is False
        assert reason == ""

    def test_skip_priority_scanner_file_first(self, tmp_path):
        """Scanner file check is done before config patterns."""
        filter = FileFilter(
            repo_path=tmp_path,
            scanner_files={"results.md"},
            config_ignore_patterns=["*.md"],
            load_gitignore=False,
        )
        
        # results.md matches both scanner_files and *.md pattern
        # Scanner file check should be reported as reason
        should_skip, reason = filter.should_skip("results.md")
        assert should_skip is True
        assert reason == "scanner_file"  # Not config_pattern

    def test_skip_config_pattern_full_path(self, tmp_path):
        """Config patterns can match full paths (like 'docs/*')."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["docs/*"],
            load_gitignore=False,
        )
        
        # Full path match for docs/file.txt
        should_skip, reason = filter.should_skip("docs/readme.txt")
        assert should_skip is True
        assert "docs/*" in reason

    def test_skip_config_pattern_nested_path(self, tmp_path):
        """Config patterns match nested directory patterns."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["**/test/**"],
            load_gitignore=False,
        )
        
        # Should match nested test directories
        should_skip, reason = filter.should_skip("src/test/unit/file.py")
        assert should_skip is True

    def test_skip_directory_pattern_tests(self, tmp_path):
        """Directory patterns like /*tests*/ match files in tests directories."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["/*tests*/"],
            load_gitignore=False,
        )
        
        # Should match files in 'tests' directory
        should_skip, reason = filter.should_skip("tests/test_main.py")
        assert should_skip is True
        assert "/*tests*/" in reason
        
        # Should match files in nested tests directory
        should_skip, reason = filter.should_skip("src/tests/test_utils.py")
        assert should_skip is True
        
        # Should not match files not in tests directory
        should_skip, reason = filter.should_skip("src/main.py")
        assert should_skip is False

    def test_skip_directory_pattern_vendor(self, tmp_path):
        """Directory patterns like /*vendor*/ match vendor directories."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["/*vendor*/"],
            load_gitignore=False,
        )
        
        # Should match files in vendor directory
        should_skip, reason = filter.should_skip("vendor/lib/file.js")
        assert should_skip is True
        
        # Should match nested vendor directories
        should_skip, reason = filter.should_skip("packages/vendor/dep.js")
        assert should_skip is True
        
        # Should not match non-vendor paths
        should_skip, reason = filter.should_skip("src/utils.js")
        assert should_skip is False

    def test_skip_directory_pattern_with_wildcard(self, tmp_path):
        """Directory patterns with wildcards like /*cmake-build-*/ work."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["/*cmake-build-*/"],
            load_gitignore=False,
        )
        
        # Should match cmake-build-debug
        should_skip, reason = filter.should_skip("cmake-build-debug/CMakeCache.txt")
        assert should_skip is True
        
        # Should match cmake-build-release
        should_skip, reason = filter.should_skip("cmake-build-release/output.o")
        assert should_skip is True
        
        # Should not match other directories
        should_skip, reason = filter.should_skip("build/output.o")
        assert should_skip is False

    def test_skip_multiple_directory_patterns(self, tmp_path):
        """Multiple directory patterns all work correctly."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["/*tests*/", "/*test*/", "/*vendor*/", "/*3rdparty*/"],
            load_gitignore=False,
        )
        
        # tests directory
        should_skip, _ = filter.should_skip("tests/test_main.py")
        assert should_skip is True
        
        # test directory (singular)
        should_skip, _ = filter.should_skip("test/unit_test.py")
        assert should_skip is True
        
        # vendor directory
        should_skip, _ = filter.should_skip("vendor/jquery.js")
        assert should_skip is True
        
        # 3rdparty directory
        should_skip, _ = filter.should_skip("3rdparty/boost/header.hpp")
        assert should_skip is True
        
        # Regular source files should not be skipped
        should_skip, _ = filter.should_skip("src/main.cpp")
        assert should_skip is False


class TestFileFilterGitignore:
    """Tests for gitignore pattern matching."""

    def test_load_gitignore(self, tmp_path):
        """FileFilter loads .gitignore patterns."""
        # Create .gitignore file
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\nbuild/\n")
        
        filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
        
        assert filter._gitignore_spec is not None

    def test_skip_gitignored_file(self, tmp_path):
        """Gitignored files are skipped."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n")
        
        filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
        
        should_skip, reason = filter.should_skip("module.pyc")
        assert should_skip is True
        assert reason == "gitignore"

    def test_no_gitignore_file(self, tmp_path):
        """Handles missing .gitignore gracefully."""
        filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
        
        # No .gitignore exists, should not crash
        should_skip, reason = filter.should_skip("something.pyc")
        assert should_skip is False

    def test_is_gitignored_method(self, tmp_path):
        """is_gitignored method works correctly."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n*.o\n")
        
        filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
        
        assert filter.is_gitignored("file.pyc") is True
        assert filter.is_gitignored("file.o") is True
        assert filter.is_gitignored("file.cpp") is False

    def test_disabled_gitignore_loading(self, tmp_path):
        """Can disable gitignore loading."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")
        
        filter = FileFilter(repo_path=tmp_path, load_gitignore=False)
        
        assert filter._gitignore_spec is None
        assert filter.is_gitignored("file.pyc") is False


class TestFileFilterFilterPaths:
    """Tests for filter_paths method."""

    def test_filter_paths_splits_correctly(self, tmp_path):
        """filter_paths correctly splits kept and skipped files."""
        filter = FileFilter(
            repo_path=tmp_path,
            scanner_files={"results.md"},
            config_ignore_patterns=["*.txt"],
            load_gitignore=False,
        )
        
        paths = ["main.cpp", "results.md", "notes.txt", "helper.h"]
        kept, skipped = filter.filter_paths(paths)
        
        assert kept == ["main.cpp", "helper.h"]
        assert "results.md" in skipped
        assert "notes.txt" in skipped
        assert skipped["results.md"] == "scanner_file"
        assert "config_pattern" in skipped["notes.txt"]

    def test_filter_paths_empty_input(self, tmp_path):
        """filter_paths handles empty input."""
        filter = FileFilter(repo_path=tmp_path)
        
        kept, skipped = filter.filter_paths([])
        
        assert kept == []
        assert skipped == {}

    def test_filter_paths_all_kept(self, tmp_path):
        """filter_paths when no files match patterns."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["*.md"],
            load_gitignore=False,
        )
        
        paths = ["main.cpp", "helper.h", "util.py"]
        kept, skipped = filter.filter_paths(paths)
        
        assert kept == paths
        assert skipped == {}

    def test_filter_paths_all_skipped(self, tmp_path):
        """filter_paths when all files match patterns."""
        filter = FileFilter(
            repo_path=tmp_path,
            config_ignore_patterns=["*.md", "*.txt"],
            load_gitignore=False,
        )
        
        paths = ["README.md", "NOTES.md", "TODO.txt"]
        kept, skipped = filter.filter_paths(paths)
        
        assert kept == []
        assert len(skipped) == 3


class TestFileFilterMutations:
    """Tests for add_* and reload methods."""

    def test_add_scanner_files(self, tmp_path):
        """Can add scanner files dynamically."""
        filter = FileFilter(repo_path=tmp_path, scanner_files={"a.md"})
        
        filter.add_scanner_files("b.md", "c.log")
        
        assert "a.md" in filter.scanner_files
        assert "b.md" in filter.scanner_files
        assert "c.log" in filter.scanner_files

    def test_add_config_patterns(self, tmp_path):
        """Can add config patterns dynamically."""
        filter = FileFilter(repo_path=tmp_path, config_ignore_patterns=["*.md"])
        
        filter.add_config_patterns("*.txt", "*.json")
        
        assert filter.config_patterns == ["*.md", "*.txt", "*.json"]

    def test_reload_gitignore(self, tmp_path):
        """Can reload gitignore patterns."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")
        
        filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
        assert filter.is_gitignored("file.pyc") is True
        assert filter.is_gitignored("file.o") is False
        
        # Update .gitignore
        gitignore.write_text("*.o\n")
        filter.reload_gitignore()
        
        # Now .o is ignored, .pyc is not
        assert filter.is_gitignored("file.o") is True
        assert filter.is_gitignored("file.pyc") is False


class TestFileFilterWithoutPathspec:
    """Tests for graceful degradation without pathspec."""

    def test_handles_missing_pathspec(self, tmp_path):
        """FileFilter works without pathspec installed."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")
        
        with patch("code_scanner.file_filter.HAS_PATHSPEC", False):
            filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
            
            # Should not crash, gitignore just won't work
            assert filter._gitignore_spec is None
            
            # Should still filter by scanner_files and config_patterns
            filter.scanner_files = {"results.md"}
            should_skip, reason = filter.should_skip("results.md")
            assert should_skip is True


class TestFileFilterErrorHandling:
    """Tests for error handling in FileFilter."""

    def test_gitignore_read_oserror(self, tmp_path):
        """Handle OSError when reading .gitignore."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")
        
        # Mock OSError when reading gitignore
        with patch.object(Path, 'read_text', side_effect=OSError("Permission denied")):
            filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
            # Should handle the error gracefully
            # Gitignore won't be loaded but should not crash
            assert filter._gitignore_spec is None

    def test_gitignore_parse_error(self, tmp_path):
        """Handle exception when parsing .gitignore patterns."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")
        
        # Mock PathSpec.from_lines to raise an exception
        with patch("code_scanner.file_filter.pathspec.PathSpec.from_lines", 
                   side_effect=Exception("Parse error")):
            filter = FileFilter(repo_path=tmp_path, load_gitignore=True)
            # Should handle the error gracefully
            assert filter._gitignore_spec is None
