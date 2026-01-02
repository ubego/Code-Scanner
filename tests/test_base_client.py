"""Tests for base_client module."""

import pytest
from typing import Any

from code_scanner.base_client import (
    BaseLLMClient,
    LLMClientError,
    ContextOverflowError,
    SYSTEM_PROMPT_TEMPLATE,
    build_user_prompt,
)


class TestLLMClientError:
    """Tests for LLMClientError exception."""

    def test_can_raise(self):
        """Test that exception can be raised."""
        with pytest.raises(LLMClientError) as exc_info:
            raise LLMClientError("Test error")
        
        assert "Test error" in str(exc_info.value)

    def test_can_catch_as_exception(self):
        """Test that it can be caught as base Exception."""
        try:
            raise LLMClientError("Test")
        except Exception as e:
            assert isinstance(e, LLMClientError)


class TestContextOverflowError:
    """Tests for ContextOverflowError exception."""

    def test_can_raise(self):
        """Test that exception can be raised."""
        with pytest.raises(ContextOverflowError) as exc_info:
            raise ContextOverflowError("Context exceeded")
        
        assert "Context exceeded" in str(exc_info.value)

    def test_is_subclass_of_llm_client_error(self):
        """Test that ContextOverflowError is subclass of LLMClientError."""
        assert issubclass(ContextOverflowError, LLMClientError)

    def test_can_catch_as_llm_client_error(self):
        """Test that it can be caught as LLMClientError."""
        with pytest.raises(LLMClientError):
            raise ContextOverflowError("Overflow")

    def test_specific_catch_is_possible(self):
        """Test that specific catch differentiates from base error."""
        # This tests that we can distinguish between the two errors
        try:
            raise ContextOverflowError("Overflow")
        except ContextOverflowError:
            caught_specific = True
        except LLMClientError:
            caught_specific = False
        
        assert caught_specific


class TestBaseLLMClient:
    """Tests for BaseLLMClient abstract base class."""

    def test_cannot_instantiate_directly(self):
        """Test that BaseLLMClient cannot be instantiated."""
        with pytest.raises(TypeError) as exc_info:
            BaseLLMClient()  # type: ignore[abstract]
        
        assert "abstract" in str(exc_info.value).lower()

    def test_subclass_must_implement_connect(self):
        """Test that subclass must implement connect."""
        class PartialClient(BaseLLMClient):
            def query(self, *args, **kwargs) -> dict:
                return {}
            @property
            def context_limit(self) -> int:
                return 0
            @property
            def model_id(self) -> str:
                return ""
            @property
            def backend_name(self) -> str:
                return ""
            def is_connected(self) -> bool:
                return False
            def is_ready(self) -> bool:
                return False
            def wait_for_connection(self, retry_interval: int = 10) -> None:
                pass
            def needs_context_limit(self) -> bool:
                return False
            def set_context_limit(self, limit: int) -> None:
                pass
        
        with pytest.raises(TypeError):
            PartialClient()

    def test_concrete_subclass_can_be_created(self):
        """Test that a complete subclass can be instantiated."""
        class ConcreteClient(BaseLLMClient):
            def connect(self) -> None:
                pass
            def query(self, system_prompt: str, user_prompt: str, max_retries: int = 3) -> dict[str, Any]:
                return {"issues": []}
            @property
            def context_limit(self) -> int:
                return 4096
            @property
            def model_id(self) -> str:
                return "test-model"
            @property
            def backend_name(self) -> str:
                return "Test"
            def is_connected(self) -> bool:
                return True
            def is_ready(self) -> bool:
                return True
            def wait_for_connection(self, retry_interval: int = 10) -> None:
                pass
            def needs_context_limit(self) -> bool:
                return False
            def set_context_limit(self, limit: int) -> None:
                pass
        
        client = ConcreteClient()
        assert client.backend_name == "Test"
        assert client.model_id == "test-model"
        assert client.context_limit == 4096
        assert client.is_connected()


class TestSystemPromptTemplate:
    """Tests for SYSTEM_PROMPT_TEMPLATE."""

    def test_exists_and_not_empty(self):
        """Test that system prompt template exists."""
        assert SYSTEM_PROMPT_TEMPLATE is not None
        assert len(SYSTEM_PROMPT_TEMPLATE) > 0

    def test_contains_json_instruction(self):
        """Test that template mentions JSON format."""
        assert "json" in SYSTEM_PROMPT_TEMPLATE.lower()

    def test_contains_issues_format(self):
        """Test that template describes issues format."""
        assert "issues" in SYSTEM_PROMPT_TEMPLATE.lower()

    def test_contains_required_fields(self):
        """Test that template mentions required issue fields."""
        assert "file" in SYSTEM_PROMPT_TEMPLATE
        assert "line_number" in SYSTEM_PROMPT_TEMPLATE
        assert "description" in SYSTEM_PROMPT_TEMPLATE
        assert "suggested_fix" in SYSTEM_PROMPT_TEMPLATE
        assert "code_snippet" in SYSTEM_PROMPT_TEMPLATE


class TestBuildUserPrompt:
    """Tests for build_user_prompt function."""

    def test_includes_check_query(self):
        """Test that prompt includes the check query."""
        prompt = build_user_prompt(
            check_query="Check for bugs",
            files_content={"test.py": "pass"},
        )
        
        assert "Check for bugs" in prompt

    def test_includes_file_path(self):
        """Test that prompt includes file paths."""
        prompt = build_user_prompt(
            check_query="Check",
            files_content={"src/main.py": "code"},
        )
        
        assert "src/main.py" in prompt

    def test_includes_file_content(self):
        """Test that prompt includes file content."""
        prompt = build_user_prompt(
            check_query="Check",
            files_content={"test.py": "def hello(): print('world')"},
        )
        
        assert "def hello(): print('world')" in prompt

    def test_handles_multiple_files(self):
        """Test that prompt handles multiple files."""
        prompt = build_user_prompt(
            check_query="Check",
            files_content={
                "file1.py": "content1",
                "file2.py": "content2",
            },
        )
        
        assert "file1.py" in prompt
        assert "file2.py" in prompt
        assert "content1" in prompt
        assert "content2" in prompt

    def test_handles_empty_files_dict(self):
        """Test that prompt handles empty files dict."""
        prompt = build_user_prompt(
            check_query="Check",
            files_content={},
        )
        
        assert "Check" in prompt

    def test_formats_as_markdown(self):
        """Test that files are formatted with markdown code blocks."""
        prompt = build_user_prompt(
            check_query="Check",
            files_content={"test.py": "code"},
        )
        
        assert "```" in prompt  # Markdown code fence
