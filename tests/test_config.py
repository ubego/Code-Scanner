"""Tests for configuration module."""

import pytest
from pathlib import Path
import tempfile

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.config import load_config, ConfigError, get_default_config_path
from code_scanner.models import CheckGroup


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(self, temp_dir: Path):
        """Test loading a valid configuration file."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
checks = [
    "Check for errors",
    "Check for style issues"
]

[llm]
backend = "lm-studio"
host = "192.168.1.100"
port = 8080
""")
        
        config = load_config(temp_dir, config_file)
        
        assert config.target_directory == temp_dir
        assert config.config_file == config_file
        # Legacy format creates one group with pattern "*"
        assert len(config.check_groups) == 1
        assert config.check_groups[0].pattern == "*"
        assert len(config.check_groups[0].checks) == 2
        assert config.check_groups[0].checks[0] == "Check for errors"
        assert config.llm.host == "192.168.1.100"
        assert config.llm.port == 8080
        assert config.llm.backend == "lm-studio"

    def test_missing_config_file_raises_error(self, temp_dir: Path):
        """Test that missing config file raises ConfigError."""
        non_existent = temp_dir / "nonexistent.toml"
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, non_existent)
        
        assert "not found" in str(exc_info.value)

    def test_empty_checks_raises_error(self, temp_dir: Path):
        """Test that empty checks list raises ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
checks = []
""")
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "No checks defined" in str(exc_info.value)

    def test_missing_checks_raises_error(self, temp_dir: Path):
        """Test that missing checks key raises ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
[llm]
host = "localhost"
""")
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "No checks defined" in str(exc_info.value)

    def test_invalid_toml_raises_error(self, temp_dir: Path):
        """Test that invalid TOML raises ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
checks = [
    "unclosed string
]
""")
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "Invalid TOML" in str(exc_info.value)

    def test_nonexistent_target_directory_raises_error(self, temp_dir: Path):
        """Test that nonexistent target directory raises ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('checks = ["test"]')
        
        non_existent_dir = temp_dir / "nonexistent"
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(non_existent_dir, config_file)
        
        assert "does not exist" in str(exc_info.value)

    def test_missing_backend_raises_error(self, temp_dir: Path):
        """Test that missing backend raises ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('''
checks = ["test check"]

[llm]
host = "localhost"
port = 1234
''')
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "backend" in str(exc_info.value).lower()

    def test_llm_context_limit_from_config(self, temp_dir: Path):
        """Test that context_limit can be set in config."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
checks = ["test check"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
context_limit = 16384
""")
        
        config = load_config(temp_dir, config_file)
        
        assert config.llm.context_limit == 16384

    def test_commit_hash_passed_through(self, temp_dir: Path):
        """Test that commit hash is passed through to config."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('''checks = ["test"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
''')
        
        config = load_config(temp_dir, config_file, commit_hash="abc123")
        
        assert config.commit_hash == "abc123"

    def test_output_paths(self, temp_dir: Path):
        """Test that output paths are correctly constructed."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('''checks = ["test"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
''')
        
        config = load_config(temp_dir, config_file)
        
        assert config.output_path == temp_dir / "code_scanner_results.md"
        assert config.log_path == temp_dir / "code_scanner.log"
        # Lock file is in scanner's script directory, not target directory
        assert config.lock_path.name == ".code_scanner.lock"

    def test_unsupported_section_raises_error(self, temp_dir: Path):
        """Test that unsupported top-level sections raise ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('''
checks = ["test"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234

[scan]
include_dirs = ["src"]
''')
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "Unsupported configuration section" in str(exc_info.value)
        assert "scan" in str(exc_info.value)

    def test_unsupported_llm_param_raises_error(self, temp_dir: Path):
        """Test that unsupported LLM parameters raise ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('''
checks = ["test"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
unsupported_param = "value"
''')
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "Unsupported parameter" in str(exc_info.value)
        assert "llm" in str(exc_info.value).lower()
        assert "unsupported_param" in str(exc_info.value)

    def test_unsupported_check_param_raises_error(self, temp_dir: Path):
        """Test that unsupported check parameters raise ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('''
[[checks]]
pattern = "*.py"
checks = ["test"]
name = "Test Check"
query = "some query"

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
''')
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "Unsupported parameter" in str(exc_info.value)
        assert "checks" in str(exc_info.value).lower()


class TestCheckGroupFormat:
    """Tests for new [[checks]] table format."""

    def test_load_new_format_single_group(self, temp_dir: Path):
        """Test loading new format with single check group."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
[[checks]]
pattern = "*.cpp, *.h"
checks = ["Check for errors", "Check for memory leaks"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
""")
        
        config = load_config(temp_dir, config_file)
        
        assert len(config.check_groups) == 1
        assert config.check_groups[0].pattern == "*.cpp, *.h"
        assert len(config.check_groups[0].checks) == 2
        assert config.check_groups[0].checks[0] == "Check for errors"

    def test_load_new_format_multiple_groups(self, temp_dir: Path):
        """Test loading new format with multiple check groups."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
[[checks]]
pattern = "*.cpp, *.h"
checks = ["Check C++ code"]

[[checks]]
pattern = "*.py"
checks = ["Check Python code"]

[[checks]]
pattern = "*"
checks = ["Check all files"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
""")
        
        config = load_config(temp_dir, config_file)
        
        assert len(config.check_groups) == 3
        assert config.check_groups[0].pattern == "*.cpp, *.h"
        assert config.check_groups[1].pattern == "*.py"
        assert config.check_groups[2].pattern == "*"

    def test_new_format_empty_rules_raises_error(self, temp_dir: Path):
        """Test that empty checks list raises ConfigError."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
[[checks]]
pattern = "*.cpp"
checks = []

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
""")
        
        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_dir, config_file)
        
        assert "checks" in str(exc_info.value).lower()

    def test_new_format_missing_pattern_uses_default(self, temp_dir: Path):
        """Test that missing pattern defaults to '*'."""
        config_file = temp_dir / "config.toml"
        config_file.write_text("""
[[checks]]
checks = ["Check for errors"]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
""")
        
        config = load_config(temp_dir, config_file)
        
        assert config.check_groups[0].pattern == "*"


class TestCheckGroupPatternMatching:
    """Tests for CheckGroup.matches_file() pattern matching."""

    def test_single_extension_matches(self):
        """Test matching single extension pattern."""
        group = CheckGroup(pattern="*.cpp", checks=["test"])
        
        assert group.matches_file("main.cpp") is True
        assert group.matches_file("src/main.cpp") is True
        assert group.matches_file("main.h") is False
        assert group.matches_file("main.py") is False

    def test_multiple_extensions_match(self):
        """Test matching multiple extension patterns."""
        group = CheckGroup(pattern="*.cpp, *.h, *.hpp", checks=["test"])
        
        assert group.matches_file("main.cpp") is True
        assert group.matches_file("header.h") is True
        assert group.matches_file("template.hpp") is True
        assert group.matches_file("main.py") is False

    def test_wildcard_matches_all(self):
        """Test that '*' matches all files."""
        group = CheckGroup(pattern="*", checks=["test"])
        
        assert group.matches_file("main.cpp") is True
        assert group.matches_file("readme.md") is True
        assert group.matches_file("src/deep/nested/file.txt") is True

    def test_pattern_with_path(self):
        """Test that pattern can match full paths."""
        group = CheckGroup(pattern="src/*.cpp", checks=["test"])
        
        assert group.matches_file("src/main.cpp") is True
        # Note: filename-only match also works
        assert group.matches_file("main.cpp") is False

    def test_pattern_whitespace_handling(self):
        """Test that patterns handle whitespace correctly."""
        group = CheckGroup(pattern="  *.cpp ,  *.h  ", checks=["test"])
        
        assert group.matches_file("main.cpp") is True
        assert group.matches_file("header.h") is True
