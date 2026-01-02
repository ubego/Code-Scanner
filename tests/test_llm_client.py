"""Tests for LLM client module."""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_scanner.llm_client import LLMClient, LLMClientError, ContextOverflowError
from code_scanner.models import LLMConfig


class TestLLMClient:
    """Tests for LLMClient class."""

    @pytest.fixture
    def llm_config(self) -> LLMConfig:
        """Create LLM config for testing."""
        return LLMConfig(
            host="localhost",
            port=1234,
            model="qwen-coder",
            timeout=120,
        )

    def test_create_client(self, llm_config: LLMConfig):
        """Test creating LLM client."""
        client = LLMClient(llm_config)
        
        assert client.config == llm_config
        assert not client.is_connected()

    @patch('code_scanner.llm_client.OpenAI')
    def test_connect_success(self, mock_openai, llm_config: LLMConfig):
        """Test successful connection to LM Studio."""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Mock successful model list
        mock_models = MagicMock()
        mock_models.data = [MagicMock(id="qwen-coder")]
        mock_client.models.list.return_value = mock_models
        
        client = LLMClient(llm_config)
        client.connect()
        
        assert client.is_connected()
        mock_openai.assert_called_once_with(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            timeout=120,
        )

    @patch('code_scanner.llm_client.OpenAI')
    def test_connect_failure(self, mock_openai, llm_config: LLMConfig):
        """Test connection failure handling."""
        from openai import APIConnectionError
        
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.side_effect = APIConnectionError(request=MagicMock())
        
        client = LLMClient(llm_config)
        
        with pytest.raises(LLMClientError) as exc_info:
            client.connect()
        
        assert "connect" in str(exc_info.value).lower()

    @patch('code_scanner.llm_client.OpenAI')
    def test_query_returns_json(self, mock_openai, llm_config: LLMConfig):
        """Test that query returns parsed JSON."""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.return_value = MagicMock(data=[MagicMock(id="qwen-coder")])
        
        # Mock response
        response_content = json.dumps({
            "issues": [
                {
                    "file": "test.cpp",
                    "line": 10,
                    "severity": "warning",
                    "code_snippet": "int* ptr = new int;",
                    "description": "Heap allocation without smart pointer"
                }
            ]
        })
        mock_message = MagicMock()
        mock_message.content = response_content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        
        client = LLMClient(llm_config)
        client.connect()
        
        result = client.query("Test prompt", "Code context")
        
        assert "issues" in result
        assert len(result["issues"]) == 1
        assert result["issues"][0]["file"] == "test.cpp"

    @patch('code_scanner.llm_client.OpenAI')
    def test_query_without_connection_raises_error(self, mock_openai, llm_config: LLMConfig):
        """Test that query without connection raises error."""
        client = LLMClient(llm_config)
        
        with pytest.raises(LLMClientError) as exc_info:
            client.query("Test prompt", "Code context")
        
        assert "Not connected" in str(exc_info.value) or "connect" in str(exc_info.value).lower()


    @patch('code_scanner.llm_client.OpenAI')
    def test_context_limit_from_config(self, mock_openai):
        """Test that context_limit from config is used when provided."""
        config = LLMConfig(
            host="localhost",
            port=1234,
            model="qwen-coder",
            timeout=120,
            context_limit=16384,
        )
        
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.return_value = MagicMock(data=[MagicMock(id="qwen-coder")])
        
        client = LLMClient(config)
        client.connect()
        
        assert client.context_limit == 16384
        assert client.is_ready()

    @patch('code_scanner.llm_client.OpenAI')
    def test_needs_context_limit_when_not_detected(self, mock_openai, llm_config: LLMConfig):
        """Test that needs_context_limit returns True when context limit unavailable."""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Create a model mock that explicitly doesn't have context_length
        mock_model = MagicMock(spec=['id'])
        mock_model.id = "qwen-coder"
        mock_client.models.list.return_value = MagicMock(data=[mock_model])
        
        client = LLMClient(llm_config)
        client.connect()
        
        # Context limit couldn't be detected
        assert client.needs_context_limit()
        assert not client.is_ready()

    @patch('code_scanner.llm_client.OpenAI')
    def test_set_context_limit_manually(self, mock_openai, llm_config: LLMConfig):
        """Test that context limit can be set manually."""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.return_value = MagicMock(data=[MagicMock(id="qwen-coder")])
        
        client = LLMClient(llm_config)
        client.connect()
        
        client.set_context_limit(8192)
        
        assert client.context_limit == 8192
        assert client.is_ready()
        assert not client.needs_context_limit()

    @patch('code_scanner.llm_client.OpenAI')
    def test_set_context_limit_invalid_value(self, mock_openai, llm_config: LLMConfig):
        """Test that setting invalid context limit raises error."""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.return_value = MagicMock(data=[MagicMock(id="qwen-coder")])
        
        client = LLMClient(llm_config)
        client.connect()
        
        with pytest.raises(ValueError):
            client.set_context_limit(0)
        
        with pytest.raises(ValueError):
            client.set_context_limit(-100)

    @patch('code_scanner.llm_client.OpenAI')
    def test_context_overflow_error_shows_helpful_message(self, mock_openai, llm_config: LLMConfig):
        """Test that context overflow errors provide helpful guidance."""
        from openai import APIError
        import httpx
        
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.return_value = MagicMock(data=[MagicMock(id="qwen-coder")])
        
        # Mock APIError for context overflow
        mock_request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        error_body = {
            'error': 'Trying to keep the first 5650 tokens when context the overflows. '
                     'However, the model is loaded with context length of only 4096 tokens, '
                     'which is not enough. Try to load the model with a larger context length'
        }
        mock_client.chat.completions.create.side_effect = APIError(
            message=str(error_body),
            request=mock_request,
            body=error_body
        )
        
        llm_config.context_limit = 36000  # Config says 36000
        client = LLMClient(llm_config)
        client.connect()
        client.set_context_limit(36000)
        
        # ContextOverflowError is a subclass of LLMClientError but is FATAL
        with pytest.raises(ContextOverflowError) as exc_info:
            client.query("system prompt", "user prompt")
        
        error_msg = str(exc_info.value)
        # Should include helpful guidance
        assert "CONTEXT LENGTH MISMATCH" in error_msg
        assert "4096" in error_msg  # Model's actual context
        assert "LM Studio" in error_msg
        assert "context_limit" in error_msg.lower()


class TestTokenEstimation:
    """Tests for token estimation functionality - skipped since LLMClient doesn't have these methods."""
    pass
