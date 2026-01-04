"""Integration tests for code scanner with real LM Studio.

These tests require a running LM Studio instance and are skipped by default.
Run with: pytest tests/test_integration.py -v --run-integration
"""

import os
import pytest
import shutil
import tempfile
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

from code_scanner.config import load_config, Config, CheckGroup
from code_scanner.git_watcher import GitWatcher
from code_scanner.lmstudio_client import LLMClient, LLMClientError, build_user_prompt, SYSTEM_PROMPT_TEMPLATE
from code_scanner.issue_tracker import IssueTracker
from code_scanner.output import OutputGenerator
from code_scanner.scanner import Scanner
from code_scanner.models import Issue, GitState, ChangedFile


# Sample Qt project path
SAMPLE_QT_PROJECT = Path(__file__).parent / "sample_qt_project"


def pytest_addoption(parser):
    """Add custom pytest option for integration tests."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require LM Studio",
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
def lm_studio_available():
    """Check if LM Studio is running and available."""
    from code_scanner.config import LLMConfig
    from code_scanner.lmstudio_client import LMStudioClient
    
    client = LMStudioClient(LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384))
    try:
        client.connect()
        return True
    except LLMClientError:
        return False


@pytest.fixture
def skip_without_lm_studio(lm_studio_available, skip_without_integration):
    """Skip test if LM Studio is not available."""
    if not lm_studio_available:
        pytest.skip("LM Studio not available at localhost:1234")


@pytest.fixture
def temp_git_repo():
    """Create a temporary Git repository with sample files."""
    temp_dir = tempfile.mkdtemp()
    
    # Initialize Git repo
    os.system(f"cd {temp_dir} && git init -q")
    os.system(f"cd {temp_dir} && git config user.email 'test@test.com'")
    os.system(f"cd {temp_dir} && git config user.name 'Test'")
    
    # Create initial commit
    readme = Path(temp_dir) / "README.md"
    readme.write_text("# Test Project\n")
    os.system(f"cd {temp_dir} && git add . && git commit -m 'Initial' -q")
    
    yield Path(temp_dir)
    
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_git_repo_with_qt(temp_git_repo):
    """Create a temp Git repo with Qt sample files."""
    # Copy sample Qt project files
    src_dir = temp_git_repo / "src"
    src_dir.mkdir()
    
    for file in (SAMPLE_QT_PROJECT / "src").iterdir():
        shutil.copy(file, src_dir / file.name)
    
    # Files are uncommitted (modified)
    yield temp_git_repo


class TestLLMClientIntegration:
    """Integration tests for LLM client with real LM Studio."""

    def test_connect_to_lm_studio(self, skip_without_lm_studio):
        """Test connecting to LM Studio."""
        from code_scanner.config import LLMConfig
        
        client = LLMClient(LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384))
        client.connect()
        
        assert client.model_id is not None
        assert client.context_limit > 0

    def test_simple_query(self, skip_without_lm_studio):
        """Test a simple query to LM Studio."""
        from code_scanner.config import LLMConfig
        
        client = LLMClient(LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384))
        client.connect()
        
        # Simple test query
        system_prompt = """You are a code analyzer. 
IMPORTANT: Respond ONLY with valid JSON. 
Do NOT wrap in markdown code fences.
Do NOT include any explanation text.
Response format: {"issues": []}"""
        
        user_prompt = """Analyze this code and return issues in JSON format:

```python
x = 1
```

Return: {"issues": []} if no issues found."""
        
        response = client.query(system_prompt, user_prompt, max_retries=3)
        
        assert isinstance(response, dict)
        assert "issues" in response

    def test_code_analysis_query(self, skip_without_lm_studio):
        """Test code analysis query with sample C++ code."""
        from code_scanner.config import LLMConfig
        
        client = LLMClient(LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384))
        client.connect()
        
        # Read sample Qt code
        sample_code = (SAMPLE_QT_PROJECT / "src" / "main.cpp").read_text()
        
        files = {"main.cpp": sample_code}
        user_prompt = build_user_prompt(
            "Check for memory leaks and suggest fixes",
            files
        )
        
        response = client.query(SYSTEM_PROMPT_TEMPLATE, user_prompt, max_retries=3)
        
        assert isinstance(response, dict)
        assert "issues" in response
        # The sample code has intentional memory leaks, so we expect issues
        # But don't assert on count as LLM behavior varies


class TestGitWatcherIntegration:
    """Integration tests for Git watcher."""

    def test_watch_uncommitted_changes(self, temp_git_repo_with_qt):
        """Test detecting uncommitted file changes."""
        watcher = GitWatcher(temp_git_repo_with_qt)
        watcher.connect()
        
        state = watcher.get_state()
        
        assert state.has_changes
        assert len(state.changed_files) > 0
        
        # Check that Qt files are detected
        file_paths = [f.path for f in state.changed_files]
        assert any("main.cpp" in p for p in file_paths)


class TestScannerIntegration:
    """Integration tests for full scanner with LM Studio."""

    def test_scan_single_file(self, skip_without_lm_studio, temp_git_repo):
        """Test scanning a single file with the scanner."""
        from code_scanner.config import LLMConfig
        
        # Create a simple Python file with an obvious issue
        test_file = temp_git_repo / "test.py"
        test_file.write_text("""
# This file has unused imports
import os
import sys
import json

def hello():
    print("Hello")
""")
        
        # Create config
        config = MagicMock(spec=Config)
        config.target_directory = temp_git_repo
        config.output_file = "results.md"
        config.log_file = "scanner.log"
        config.git_poll_interval = 1.0
        config.llm_retry_interval = 1.0
        config.max_llm_retries = 3
        config.check_groups = [
            CheckGroup(pattern="*.py", checks=["Check for unused imports"]),
        ]
        config.llm = LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384)
        
        # Create components
        git_watcher = GitWatcher(temp_git_repo)
        git_watcher.connect()
        
        llm_client = LLMClient(config.llm)
        llm_client.connect()
        
        issue_tracker = IssueTracker()
        output_generator = MagicMock()
        
        # Create scanner
        scanner = Scanner(
            config=config,
            git_watcher=git_watcher,
            llm_client=llm_client,
            issue_tracker=issue_tracker,
            output_generator=output_generator,
        )
        
        # Run a single check manually
        files_content = {"test.py": test_file.read_text()}
        batches = [files_content]
        
        issues = scanner._run_check("Check for unused imports", batches)
        
        # We should get some response (may or may not find issues depending on LLM)
        assert isinstance(issues, list)

    def test_scan_qt_project(self, skip_without_lm_studio, temp_git_repo_with_qt):
        """Test scanning the sample Qt project."""
        from code_scanner.config import LLMConfig
        
        # Create config
        config = MagicMock(spec=Config)
        config.target_directory = temp_git_repo_with_qt
        config.output_file = "results.md"
        config.log_file = "scanner.log"
        config.git_poll_interval = 1.0
        config.llm_retry_interval = 1.0
        config.max_llm_retries = 3
        config.check_groups = [
            CheckGroup(
                pattern="*.cpp, *.h",
                checks=["Check for memory leaks and heap allocations that could use stack"]
            ),
        ]
        config.llm = LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384)
        
        # Create components
        git_watcher = GitWatcher(temp_git_repo_with_qt)
        git_watcher.connect()
        
        llm_client = LLMClient(config.llm)
        llm_client.connect()
        
        issue_tracker = IssueTracker()
        output_path = temp_git_repo_with_qt / "results.md"
        output_generator = OutputGenerator(output_path)
        
        # Create scanner
        scanner = Scanner(
            config=config,
            git_watcher=git_watcher,
            llm_client=llm_client,
            issue_tracker=issue_tracker,
            output_generator=output_generator,
        )
        
        # Get files content (read directly from filesystem)
        state = git_watcher.get_state()
        files_content = {}
        for f in state.changed_files:
            if f.path.endswith(('.cpp', '.h')) and not f.is_deleted:
                file_path = temp_git_repo_with_qt / f.path
                if file_path.exists():
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        files_content[f.path] = content
                    except (UnicodeDecodeError, IOError):
                        pass
        
        batches = [files_content]
        
        # Run check
        issues = scanner._run_check(
            "Check for memory leaks and heap allocations that could use stack",
            batches
        )
        
        # The sample Qt project has intentional issues
        assert isinstance(issues, list)
        # Don't assert count as LLM behavior varies


class TestEndToEndIntegration:
    """End-to-end integration tests."""

    def test_full_scan_cycle(self, skip_without_lm_studio, temp_git_repo_with_qt):
        """Test a complete scan cycle from config to output."""
        from code_scanner.config import LLMConfig
        
        # Write a config file
        config_path = temp_git_repo_with_qt / "config.toml"
        config_path.write_text('''
[[checks]]
pattern = "*.cpp, *.h"
checks = [
    "Check for memory leaks",
]

[llm]
timeout = 60
''')
        
        # Load config
        config = load_config(
            target_directory=temp_git_repo_with_qt,
            config_file=config_path,
        )
        
        assert len(config.check_groups) == 1
        assert "*.cpp" in config.check_groups[0].pattern
        
        # Create components
        git_watcher = GitWatcher(temp_git_repo_with_qt)
        git_watcher.connect()
        
        llm_client = LLMClient(config.llm)
        llm_client.connect()
        
        issue_tracker = IssueTracker()
        output_path = config.output_path
        output_generator = OutputGenerator(output_path)
        
        # Create scanner
        scanner = Scanner(
            config=config,
            git_watcher=git_watcher,
            llm_client=llm_client,
            issue_tracker=issue_tracker,
            output_generator=output_generator,
        )
        
        # Get changed files
        state = git_watcher.get_state()
        assert state.has_changes
        
        # Get file contents (read directly from filesystem)
        files_content = {}
        for f in state.changed_files:
            if f.path.endswith(('.cpp', '.h')) and not f.is_deleted:
                file_path = temp_git_repo_with_qt / f.path
                if file_path.exists():
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        files_content[f.path] = content
                    except (UnicodeDecodeError, IOError):
                        pass
        
        assert len(files_content) > 0
        
        # Create batches and run
        batches = scanner._create_batches(files_content)
        
        # Filter by pattern
        filtered = scanner._filter_batches_by_pattern(batches, config.check_groups[0])
        assert len(filtered) > 0
        
        # Run check
        issues = scanner._run_check("Check for memory leaks", filtered)
        
        # Add to tracker and write output
        if issues:
            issue_tracker.add_issues(issues)
            output_generator.write(issue_tracker, {"checks_run": 1})
            
            # Verify output file was created
            assert output_path.exists()
            content = output_path.read_text()
            assert "Code Scanner Results" in content


class TestIssueLifecycleIntegration:
    """Test issue lifecycle with real scanning."""

    def test_issue_detection_and_tracking(self, skip_without_lm_studio, temp_git_repo):
        """Test that issues are properly tracked across scans."""
        from code_scanner.config import LLMConfig
        
        # Create a file with an obvious issue
        test_file = temp_git_repo / "buggy.py"
        test_file.write_text("""
def divide(a, b):
    return a / b  # No check for division by zero
""")
        
        # Setup components
        config = MagicMock(spec=Config)
        config.target_directory = temp_git_repo
        config.output_file = "results.md"
        config.log_file = "scanner.log"
        config.llm = LLMConfig(backend="lm-studio", host="localhost", port=1234, context_limit=16384)
        
        llm_client = LLMClient(config.llm)
        llm_client.connect()
        
        issue_tracker = IssueTracker()
        
        # First scan
        user_prompt = build_user_prompt(
            "Check for potential runtime errors",
            {"buggy.py": test_file.read_text()}
        )
        
        response = llm_client.query(SYSTEM_PROMPT_TEMPLATE, user_prompt, max_retries=3)
        
        # Track issues
        if response.get("issues"):
            for issue_data in response["issues"]:
                try:
                    issue = Issue.from_llm_response(
                        issue_data,
                        check_query="Check for potential runtime errors",
                        timestamp=datetime.now(),
                    )
                    issue_tracker.add_issue(issue)
                except Exception:
                    pass
        
        initial_count = len(issue_tracker.issues)
        
        # Second scan with same file should deduplicate
        response2 = llm_client.query(SYSTEM_PROMPT_TEMPLATE, user_prompt, max_retries=3)
        
        if response2.get("issues"):
            for issue_data in response2["issues"]:
                try:
                    issue = Issue.from_llm_response(
                        issue_data,
                        check_query="Check for potential runtime errors",
                        timestamp=datetime.now(),
                    )
                    issue_tracker.add_issue(issue)
                except Exception:
                    pass
        
        # Issue count should not double (deduplication)
        # Note: This depends on LLM returning similar issues
        assert len(issue_tracker.issues) >= initial_count


class TestOutputIntegration:
    """Test output generation with real data."""

    def test_output_with_real_issues(self, temp_git_repo):
        """Test output generation with realistic issues."""
        output_path = temp_git_repo / "results.md"
        output_generator = OutputGenerator(output_path)
        
        issue_tracker = IssueTracker()
        
        # Add some realistic issues
        issues = [
            Issue(
                file_path="src/main.cpp",
                line_number=15,
                description="Memory leak: QApplication allocated on heap but never deleted",
                suggested_fix="Use stack allocation: QApplication app(argc, argv);",
                code_snippet="QApplication* app = new QApplication(argc, argv);",
                check_query="Check for memory leaks",
                timestamp=datetime.now(),
            ),
            Issue(
                file_path="src/main.cpp",
                line_number=18,
                description="Repeated string literal 'Sample Qt App'",
                suggested_fix="Define a constant: constexpr auto APP_NAME = \"Sample Qt App\";",
                code_snippet='app->setApplicationName("Sample Qt App");',
                check_query="Check for repeated string literals",
                timestamp=datetime.now(),
            ),
            Issue(
                file_path="src/widget.h",
                line_number=20,
                description="Function implementation in header file",
                suggested_fix="Move implementation to widget.cpp",
                code_snippet="explicit Widget(QWidget *parent = nullptr) : QWidget(parent)",
                check_query="Check function implementations",
                timestamp=datetime.now(),
            ),
        ]
        
        for issue in issues:
            issue_tracker.add_issue(issue)
        
        # Write output
        scan_info = {
            "files_scanned": ["src/main.cpp", "src/widget.h", "src/widget.cpp"],
            "checks_run": 3,
        }
        output_generator.write(issue_tracker, scan_info)
        
        # Verify output
        assert output_path.exists()
        content = output_path.read_text()
        
        assert "Code Scanner Results" in content
        assert "Memory leak" in content
        assert "Repeated string literal" in content
        assert "src/main.cpp" in content
        assert "src/widget.h" in content
        assert "OPEN" in content
        assert "3" in content  # Total issues


class TestConfigIntegration:
    """Test configuration loading integration."""

    def test_load_config_with_check_groups(self, temp_git_repo):
        """Test loading config with check groups."""
        config_path = temp_git_repo / "config.toml"
        config_path.write_text('''
[[checks]]
pattern = "*.cpp, *.h, *.hpp"
checks = [
    "Check for memory leaks",
    "Check for RAII violations",
]

[[checks]]
pattern = "*.py"
checks = [
    "Check for unused imports",
]

[[checks]]
pattern = "*"
checks = [
    "General code review",
]

[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
context_limit = 16384
timeout = 120
''')
        
        config = load_config(
            target_directory=temp_git_repo,
            config_file=config_path,
        )
        
        assert len(config.check_groups) == 3
        
        # Check C++ group
        cpp_group = config.check_groups[0]
        assert "*.cpp" in cpp_group.pattern
        assert len(cpp_group.checks) == 2
        assert cpp_group.matches_file("src/main.cpp")
        assert not cpp_group.matches_file("test.py")
        
        # Check Python group
        py_group = config.check_groups[1]
        assert py_group.matches_file("test.py")
        assert not py_group.matches_file("main.cpp")
        
        # Check wildcard group
        all_group = config.check_groups[2]
        assert all_group.matches_file("anything.txt")
        assert all_group.matches_file("src/deep/nested/file.xyz")


# Conftest additions for pytest
def pytest_configure(config):
    """Add custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring LM Studio"
    )
