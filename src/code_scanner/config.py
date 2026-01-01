"""Configuration loading and validation."""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .models import LLMConfig

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Configuration error."""

    pass


@dataclass
class Config:
    """Application configuration."""

    target_directory: Path
    config_file: Path
    checks: list[str]
    commit_hash: Optional[str] = None
    llm: LLMConfig = field(default_factory=LLMConfig)

    # Output file names (in target directory)
    output_file: str = "code_scanner_results.md"
    log_file: str = "code_scanner.log"
    lock_file: str = ".code_scanner.lock"

    # Polling intervals
    git_poll_interval: int = 30  # seconds
    llm_retry_interval: int = 10  # seconds

    # Retry limits
    max_llm_retries: int = 3

    @property
    def output_path(self) -> Path:
        """Get full path to output file."""
        return self.target_directory / self.output_file

    @property
    def log_path(self) -> Path:
        """Get full path to log file."""
        return self.target_directory / self.log_file

    @property
    def lock_path(self) -> Path:
        """Get full path to lock file."""
        return self.target_directory / self.lock_file


def load_config(
    target_directory: Path,
    config_file: Optional[Path] = None,
    commit_hash: Optional[str] = None,
) -> Config:
    """Load configuration from TOML file.

    Args:
        target_directory: Path to the target directory to scan.
        config_file: Optional path to config file. If not provided,
                    looks in the script directory.
        commit_hash: Optional commit hash to compare against.

    Returns:
        Loaded and validated Config object.

    Raises:
        ConfigError: If config file is missing, invalid, or has no checks.
    """
    # Resolve target directory
    target_directory = target_directory.resolve()
    if not target_directory.exists():
        raise ConfigError(f"Target directory does not exist: {target_directory}")
    if not target_directory.is_dir():
        raise ConfigError(f"Target path is not a directory: {target_directory}")

    # Find config file
    if config_file is None:
        # Default to script directory
        script_dir = Path(__file__).parent.parent.parent
        config_file = script_dir / "config.toml"

    config_file = config_file.resolve()

    if not config_file.exists():
        raise ConfigError(
            f"Configuration file not found: {config_file}\n"
            "Please provide a config file via --config argument or "
            "create config.toml in the scanner directory."
        )

    # Load TOML
    logger.info(f"Loading configuration from {config_file}")
    try:
        with open(config_file, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in config file: {e}")

    # Extract checks
    checks = data.get("checks", [])
    if not checks:
        raise ConfigError(
            "No checks defined in configuration file.\n"
            "Add checks to your config.toml:\n"
            '  checks = ["Check for errors", "Check for style issues"]'
        )

    if not isinstance(checks, list):
        raise ConfigError("'checks' must be a list of strings")

    for i, check in enumerate(checks):
        if not isinstance(check, str) or not check.strip():
            raise ConfigError(f"Check at index {i} must be a non-empty string")

    # Extract LLM config
    llm_data = data.get("llm", {})
    llm_config = LLMConfig(
        host=llm_data.get("host", "localhost"),
        port=llm_data.get("port", 1234),
        model=llm_data.get("model"),
        timeout=llm_data.get("timeout", 120),
    )

    # Build config
    config = Config(
        target_directory=target_directory,
        config_file=config_file,
        checks=[c.strip() for c in checks],
        commit_hash=commit_hash,
        llm=llm_config,
    )

    logger.info(f"Loaded {len(config.checks)} checks from configuration")
    logger.debug(f"LM Studio endpoint: {config.llm.base_url}")

    return config


def get_default_config_path() -> Path:
    """Get the default config file path (in script directory)."""
    return Path(__file__).parent.parent.parent / "config.toml"
