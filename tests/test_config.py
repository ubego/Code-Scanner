"""Tests for configuration module."""

import pytest
from pathlib import Path
import tempfile

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.config import load_config, ConfigError, get_default_config_path


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
host = "192.168.1.100"
port = 8080
""")
        
        config = load_config(temp_dir, config_file)
        
        assert config.target_directory == temp_dir
        assert config.config_file == config_file
        assert len(config.checks) == 2
        assert config.checks[0] == "Check for errors"
        assert config.llm.host == "192.168.1.100"
        assert config.llm.port == 8080

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

    def test_default_llm_settings(self, temp_dir: Path):
        """Test that LLM settings have correct defaults."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('checks = ["test check"]')
        
        config = load_config(temp_dir, config_file)
        
        assert config.llm.host == "localhost"
        assert config.llm.port == 1234
        assert config.llm.model is None
        assert config.llm.timeout == 120

    def test_commit_hash_passed_through(self, temp_dir: Path):
        """Test that commit hash is passed through to config."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('checks = ["test"]')
        
        config = load_config(temp_dir, config_file, commit_hash="abc123")
        
        assert config.commit_hash == "abc123"

    def test_output_paths(self, temp_dir: Path):
        """Test that output paths are correctly constructed."""
        config_file = temp_dir / "config.toml"
        config_file.write_text('checks = ["test"]')
        
        config = load_config(temp_dir, config_file)
        
        assert config.output_path == temp_dir / "code_scanner_results.md"
        assert config.log_path == temp_dir / "code_scanner.log"
        assert config.lock_path == temp_dir / ".code_scanner.lock"
