"""Pytest configuration and fixtures."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from code_scanner.config import Config
from code_scanner.models import LLMConfig, Issue, IssueStatus
from code_scanner.issue_tracker import IssueTracker
from datetime import datetime


def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require LM Studio",
    )


def pytest_configure(config):
    """Add custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring LM Studio"
    )


@pytest.fixture
def integration_enabled(request):
    """Check if integration tests are enabled."""
    return request.config.getoption("--run-integration")


@pytest.fixture
def skip_without_integration(integration_enabled):
    """Skip test if integration tests are not enabled."""
    if not integration_enabled:
        pytest.skip("Integration tests disabled. Use --run-integration to enable.")


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def git_repo(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary Git repository."""
    import subprocess
    
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=temp_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=temp_dir,
        capture_output=True,
    )
    
    # Create initial commit
    readme = temp_dir / "README.md"
    readme.write_text("# Test Project\n")
    subprocess.run(["git", "add", "README.md"], cwd=temp_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=temp_dir,
        capture_output=True,
    )
    
    yield temp_dir


@pytest.fixture
def sample_config(temp_dir: Path) -> Config:
    """Create a sample configuration."""
    config_file = temp_dir / "config.toml"
    config_file.write_text("""
checks = [
    "Check for errors",
    "Check for style issues"
]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
context_limit = 16384
""")
    
    return Config(
        target_directory=temp_dir,
        config_file=config_file,
        checks=["Check for errors", "Check for style issues"],
        llm=LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384),
    )


@pytest.fixture
def lmstudio_config() -> LLMConfig:
    """Create an LM Studio LLMConfig for testing."""
    return LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384)


@pytest.fixture
def ollama_config() -> LLMConfig:
    """Create an Ollama LLMConfig for testing."""
    return LLMConfig(backend="ollama", host="localhost", port=11434, model="llama3", context_limit=16384)


@pytest.fixture
def sample_issue() -> Issue:
    """Create a sample issue."""
    return Issue(
        file_path="src/main.cpp",
        line_number=10,
        description="Heap allocation used where stack would suffice",
        suggested_fix="Use stack allocation: MyClass obj;",
        check_query="Check for heap allocation issues",
        timestamp=datetime.now(),
        status=IssueStatus.OPEN,
        code_snippet="MyClass* obj = new MyClass();",
    )


@pytest.fixture
def issue_tracker() -> IssueTracker:
    """Create an empty issue tracker."""
    return IssueTracker()


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = MagicMock()
    client.is_connected.return_value = True
    client.context_limit = 8000
    client.model_id = "test-model"
    client.query.return_value = {"issues": []}
    return client


@pytest.fixture
def sample_qt_project_path() -> Path:
    """Get path to the sample Qt project."""
    return Path(__file__).parent / "sample_qt_project"


@pytest.fixture
def sample_cpp_files(temp_dir: Path) -> dict[str, str]:
    """Create sample C++ files in temp directory."""
    src_dir = temp_dir / "src"
    src_dir.mkdir()
    
    # Create main.cpp
    main_cpp = src_dir / "main.cpp"
    main_cpp.write_text("""
#include <iostream>

int main() {
    // Create object on heap
    std::string* msg = new std::string("Hello");
    std::cout << *msg << std::endl;
    delete msg;
    return 0;
}
""")
    
    # Create utils.h with implementation
    utils_h = src_dir / "utils.h"
    utils_h.write_text("""
#ifndef UTILS_H
#define UTILS_H

inline int add(int a, int b) {
    return a + b;
}

#endif
""")
    
    return {
        "src/main.cpp": main_cpp.read_text(),
        "src/utils.h": utils_h.read_text(),
    }
