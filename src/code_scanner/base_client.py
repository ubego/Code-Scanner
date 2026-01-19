"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMClientError(Exception):
    """Error communicating with LLM backend."""

    pass


class ContextOverflowError(LLMClientError):
    """Fatal error when model context length is exceeded.
    
    This error should not be caught by retry logic - it requires
    user intervention to fix (change model settings or config).
    """

    pass


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients.
    
    Both LMStudioClient and OllamaClient must implement this interface
    to ensure interchangeable usage by the Scanner.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the LLM backend and get model info.

        Raises:
            LLMClientError: If connection fails.
        """
        pass

    @abstractmethod
    def query(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Send a query to the LLM and get JSON response.

        Args:
            system_prompt: System instructions for the LLM.
            user_prompt: User message with code context.
            max_retries: Maximum number of retries for malformed responses.
            tools: Optional list of tool definitions for function calling.

        Returns:
            Parsed JSON response from the LLM. If tools are provided and LLM 
            requests tool calls, response includes 'tool_calls' key with list 
            of {tool_name, arguments} dicts.

        Raises:
            LLMClientError: If query fails after all retries.
            ContextOverflowError: If context limit is exceeded.
        """
        pass

    @property
    @abstractmethod
    def context_limit(self) -> int:
        """Get the context limit in tokens.

        Returns:
            Context limit in tokens.

        Raises:
            LLMClientError: If not connected or limit unavailable.
        """
        pass

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Get the model ID being used.

        Returns:
            Model identifier string.

        Raises:
            LLMClientError: If not connected.
        """
        pass

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Get the human-readable backend name for logging.

        Returns:
            Backend name (e.g., "LM Studio", "Ollama").
        """
        pass



    @abstractmethod
    def wait_for_connection(self, retry_interval: int = 10) -> None:
        """Wait for LLM backend to become available.

        Retries connection every `retry_interval` seconds until successful.

        Args:
            retry_interval: Seconds between retry attempts.
        """
        pass

    @abstractmethod
    def set_context_limit(self, limit: int) -> None:
        """Manually set the context limit.

        Args:
            limit: Context limit in tokens.

        Raises:
            ValueError: If limit is not positive.
        """
        pass


# System prompt template for code analysis (shared across all backends)
SYSTEM_PROMPT_TEMPLATE = """You are an expert code analysis assistant. Your task is to find real, actionable issues in the provided code.

## RULES

1. **STAY ON TOPIC** - Only report issues matching the check query. Ignore unrelated problems.
2. **USE TOOLS** - Verify findings with available tools before reporting.
3. **USE EXACT FILE INFO** - Only reference files and lines from "Files to analyze" section.

## OUTPUT FORMAT (strict JSON, no markdown)

{"issues": [{"file": "path", "line_number": 42, "description": "...", "suggested_fix": "...", "code_snippet": "..."}]}

No issues found: {"issues": []}"""


def build_user_prompt(check_query: str, files_content: dict[str, str]) -> str:
    """Build the user prompt with file contents.

    Files are formatted with line numbers and boundary markers to prevent
    hallucination and ensure precise line number references.

    Args:
        check_query: The check/query to run against the code.
        files_content: Dictionary mapping file paths to their content.

    Returns:
        Formatted user prompt.
    """
    prompt_parts = [
        f"## Check to perform:\n{check_query}\n",
        "## Files to analyze:\n"
    ]

    for file_path, content in files_content.items():
        lines = content.split('\n')
        total_lines = len(lines)
        
        # Add line numbers to each line
        numbered_lines = []
        for i, line in enumerate(lines, start=1):
            numbered_lines.append(f"L{i}: {line}")
        numbered_content = '\n'.join(numbered_lines)
        
        # Format with boundary markers and metadata
        prompt_parts.append(
            f"### File: {file_path} (lines 1-{total_lines}, total: {total_lines})\n"
            f"<<<FILE_START>>>\n{numbered_content}\n<<<FILE_END>>>\n"
        )

    return "\n".join(prompt_parts)
