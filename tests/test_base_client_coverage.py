import pytest
from unittest.mock import MagicMock, patch
from code_scanner.base_client import BaseLLMClient, build_user_prompt
from code_scanner.models import Issue

class ConcreteLLMClient(BaseLLMClient):
    """Concrete implementation for testing abstract base class."""
    def __init__(self, config):
        self.config = config
        self._context_limit = 4096

    def connect(self) -> None:
        pass

    def query(self, system_prompt, user_prompt, max_retries=3, expected_schema=None, tools=None):
        return {"issues": []}

    @property
    def context_limit(self) -> int:
        return self._context_limit

    @property
    def model_id(self) -> str:
        return "test-model"

    @property
    def backend_name(self) -> str:
        return "TestBackend"

    def wait_for_connection(self, retry_interval: int = 10) -> None:
        pass

    def set_context_limit(self, limit: int) -> None:
        self._context_limit = limit

class TestBaseClientCoverage:
    """Test suite for base_client.py coverage."""

    def test_abstract_class_instantiation(self):
        """Test that BaseLLMClient cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseLLMClient()

    def test_concrete_implementation(self):
        """Test that concrete implementation works."""
        client = ConcreteLLMClient(config=MagicMock())
        assert client is not None

    def test_build_user_prompt_structure(self):
        """Test build_user_prompt formats content correctly."""
        check = "Check for bugs"
        batch = {
            "file1.py": "def foo(): pass",
            "file2.py": "class Bar: pass"
        }
        
        prompt = build_user_prompt(check, batch)
        
        assert "## Check to perform:\nCheck for bugs" in prompt
        assert "file1.py" in prompt
        assert "L1: def foo(): pass" in prompt
        assert "file2.py" in prompt
        assert "L1: class Bar: pass" in prompt

    def test_build_user_prompt_treats_all_files_equally(self):
        """Test that what were 'core files' are now treated as regular files."""
        check = "Check logic"
        batch = {
            "src/main.py": "print('hello')",
            "models.py": "class Issue: pass",
            "base_client.py": "class Base: pass"
        }
        
        prompt = build_user_prompt(check, batch)
        
        # Core files section should NOT be present
        assert "## Core definition files" not in prompt
        
        # All files should be under "Files to analyze"
        assert "## Files to analyze:" in prompt
        assert "src/main.py" in prompt
        assert "models.py" in prompt
        assert "base_client.py" in prompt

    def test_build_user_prompt_empty_batch(self):
        """Test build_user_prompt with empty batch."""
        prompt = build_user_prompt("Check", {})
        assert "Check" in prompt
        assert "## Files to analyze:" in prompt

    def test_context_limit_property(self):
        """Test context_limit property access."""
        mock_config = MagicMock()
        mock_config.context_limit = 4096
        client = ConcreteLLMClient(config=mock_config)
        assert client.context_limit == 4096
