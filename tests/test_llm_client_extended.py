"""Additional tests for LLM client functionality."""

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from code_scanner.llm_client import (
    LLMClient,
    LLMClientError,
    SYSTEM_PROMPT_TEMPLATE,
    build_user_prompt,
)
from code_scanner.models import LLMConfig


class TestBuildUserPrompt:
    """Tests for build_user_prompt function."""

    def test_single_file(self):
        """Build prompt with single file."""
        prompt = build_user_prompt("Check for errors", {"test.py": "print('hello')"})
        assert "Check for errors" in prompt
        assert "test.py" in prompt
        assert "print('hello')" in prompt

    def test_multiple_files(self):
        """Build prompt with multiple files."""
        files = {"a.py": "code a", "b.py": "code b"}
        prompt = build_user_prompt("Check code", files)
        assert "a.py" in prompt
        assert "b.py" in prompt
        assert "code a" in prompt
        assert "code b" in prompt

    def test_empty_files(self):
        """Build prompt with no files."""
        prompt = build_user_prompt("Check", {})
        assert "Check" in prompt


class TestStripMarkdownFences:
    """Tests for _strip_markdown_fences method."""

    def test_strip_json_fence(self):
        """Strip ```json ... ``` fences."""
        config = LLMConfig()
        client = LLMClient(config)
        
        content = '```json\n{"issues": []}\n```'
        result = client._strip_markdown_fences(content)
        assert result == '{"issues": []}'

    def test_strip_plain_fence(self):
        """Strip ``` ... ``` fences without language."""
        config = LLMConfig()
        client = LLMClient(config)
        
        content = '```\n{"issues": []}\n```'
        result = client._strip_markdown_fences(content)
        assert result == '{"issues": []}'

    def test_no_fence_unchanged(self):
        """Content without fences unchanged."""
        config = LLMConfig()
        client = LLMClient(config)
        
        content = '{"issues": []}'
        result = client._strip_markdown_fences(content)
        assert result == '{"issues": []}'

    def test_whitespace_handling(self):
        """Handles whitespace around fences."""
        config = LLMConfig()
        client = LLMClient(config)
        
        content = '  ```json\n{"issues": []}\n```  '
        result = client._strip_markdown_fences(content)
        assert result == '{"issues": []}'

    def test_case_insensitive(self):
        """Case insensitive fence detection."""
        config = LLMConfig()
        client = LLMClient(config)
        
        content = '```JSON\n{"issues": []}\n```'
        result = client._strip_markdown_fences(content)
        assert result == '{"issues": []}'


class TestLLMClientProperties:
    """Tests for LLMClient property methods."""

    def test_context_limit_not_connected(self):
        """context_limit raises error when not connected."""
        config = LLMConfig()
        client = LLMClient(config)
        
        with pytest.raises(LLMClientError, match="Not connected"):
            _ = client.context_limit

    def test_model_id_not_connected(self):
        """model_id raises error when not connected."""
        config = LLMConfig()
        client = LLMClient(config)
        
        with pytest.raises(LLMClientError, match="Not connected"):
            _ = client.model_id

    def test_is_connected_false_initially(self):
        """is_connected returns False initially."""
        config = LLMConfig()
        client = LLMClient(config)
        assert client.is_connected() is False

    def test_is_ready_false_initially(self):
        """is_ready returns False initially."""
        config = LLMConfig()
        client = LLMClient(config)
        assert client.is_ready() is False


class TestLLMClientQuery:
    """Tests for LLMClient query functionality."""

    def test_query_retry_on_empty_response(self):
        """Query retries on empty response."""
        config = LLMConfig()
        client = LLMClient(config)
        client._client = MagicMock()
        client._model_id = "test-model"
        client._context_limit = 8192
        
        # First response empty, second response valid
        mock_response_empty = MagicMock()
        mock_response_empty.choices = [MagicMock()]
        mock_response_empty.choices[0].message.content = ""
        
        mock_response_valid = MagicMock()
        mock_response_valid.choices = [MagicMock()]
        mock_response_valid.choices[0].message.content = '{"issues": []}'
        
        client._client.chat.completions.create.side_effect = [
            mock_response_empty,
            mock_response_valid,
        ]
        
        result = client.query("system", "user", max_retries=3)
        assert result == {"issues": []}
        assert client._client.chat.completions.create.call_count == 2

    def test_query_max_retries_exceeded(self):
        """Query raises error after max retries."""
        config = LLMConfig()
        client = LLMClient(config)
        client._client = MagicMock()
        client._model_id = "test-model"
        client._context_limit = 8192
        
        # All responses empty
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        
        client._client.chat.completions.create.return_value = mock_response
        
        with pytest.raises(LLMClientError, match="Failed to get valid JSON"):
            client.query("system", "user", max_retries=3)


class TestTryFixJsonResponse:
    """Tests for _try_fix_json_response method."""

    def test_fix_returns_none_when_not_connected(self):
        """Returns None when client not connected."""
        config = LLMConfig()
        client = LLMClient(config)
        
        result = client._try_fix_json_response("malformed", {})
        assert result is None

    def test_fix_succeeds_with_valid_response(self):
        """Successfully fixes malformed JSON."""
        config = LLMConfig()
        client = LLMClient(config)
        client._client = MagicMock()
        client._model_id = "test-model"
        client._supports_json_format = True
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"issues": []}'
        client._client.chat.completions.create.return_value = mock_response
        
        result = client._try_fix_json_response("broken json", {})
        assert result == {"issues": []}

    def test_fix_returns_none_on_exception(self):
        """Returns None when fix attempt raises exception."""
        config = LLMConfig()
        client = LLMClient(config)
        client._client = MagicMock()
        client._model_id = "test-model"
        
        client._client.chat.completions.create.side_effect = Exception("API error")
        
        result = client._try_fix_json_response("broken", {})
        assert result is None


class TestSystemPromptTemplate:
    """Tests for system prompt template."""

    def test_prompt_contains_json_instructions(self):
        """System prompt contains JSON format instructions."""
        assert "JSON" in SYSTEM_PROMPT_TEMPLATE
        assert "issues" in SYSTEM_PROMPT_TEMPLATE

    def test_prompt_forbids_markdown(self):
        """System prompt forbids markdown fences."""
        assert "```" in SYSTEM_PROMPT_TEMPLATE or "markdown" in SYSTEM_PROMPT_TEMPLATE.lower()

    def test_prompt_specifies_required_fields(self):
        """System prompt specifies required issue fields."""
        assert "file" in SYSTEM_PROMPT_TEMPLATE
        assert "line_number" in SYSTEM_PROMPT_TEMPLATE
        assert "description" in SYSTEM_PROMPT_TEMPLATE
