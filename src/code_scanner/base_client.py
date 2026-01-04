"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod
from typing import Any


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
    ) -> dict[str, Any]:
        """Send a query to the LLM and get JSON response.

        Args:
            system_prompt: System instructions for the LLM.
            user_prompt: User message with code context.
            max_retries: Maximum number of retries for malformed responses.

        Returns:
            Parsed JSON response from the LLM.

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
SYSTEM_PROMPT_TEMPLATE = """You are a code analysis assistant. Your task is to analyze source code and identify issues based on specific checks.

CRITICAL: Your response must be ONLY a valid JSON object. Do NOT include:
- Markdown code fences (```)
- Explanations or comments before/after the JSON
- Any text outside the JSON object

REQUIRED OUTPUT FORMAT (copy this structure exactly):
{"issues": [{"file": "path/to/file.ext", "line_number": 42, "description": "Issue description", "suggested_fix": "How to fix it", "code_snippet": "problematic code"}]}

Each issue in the array must have these exact keys:
- "file": string - the file path where the issue was found
- "line_number": integer - the line number (1-based)
- "description": string - clear description of the issue
- "suggested_fix": string - the suggested fix
- "code_snippet": string - the problematic code snippet

If no issues are found, return exactly: {"issues": []}

Be precise with line numbers. Only report actual issues, not potential or hypothetical ones."""


def build_user_prompt(check_query: str, files_content: dict[str, str]) -> str:
    """Build the user prompt with file contents.

    Args:
        check_query: The check/query to run against the code.
        files_content: Dictionary mapping file paths to their content.

    Returns:
        Formatted user prompt.
    """
    prompt_parts = [
        f"## Check to perform:\n{check_query}\n",
        "## Files to analyze:\n",
    ]

    for file_path, content in files_content.items():
        prompt_parts.append(f"### File: {file_path}\n```\n{content}\n```\n")

    return "\n".join(prompt_parts)
