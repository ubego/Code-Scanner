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
SYSTEM_PROMPT_TEMPLATE = """You are a code analysis assistant. Your task is to analyze source code and identify issues based on specific checks.

CRITICAL RULES FOR ACCURATE ANALYSIS:

1. ONLY analyze files that are EXPLICITLY provided in the "Files to analyze" section below. Do NOT report issues for files not shown.

2. If you only see a PARTIAL file (e.g., starting at line 100), do NOT assume code is missing. Use read_file to check other parts of the file if needed.

3. DO NOT hallucinate issues:
   - Only report issues you can VERIFY from the provided code
   - If code is incomplete/partial, acknowledge limitations rather than guessing
   - Use tools to verify assumptions before reporting

4. Before flagging something as "undefined" or "missing", use search_text to search for its definition in the codebase.

OUTPUT FORMAT - Your response must be ONLY a valid JSON object (no markdown, no code fences, no ``` backticks):
{"issues": [{"file": "path/to/file.ext", "line_number": 42, "description": "Issue description", "suggested_fix": "How to fix it", "code_snippet": "problematic code"}]}

Each issue in the array must have these exact keys:
- "file": string - the file path where the issue was found (MUST be one of the provided files)
- "line_number": integer - the line number (1-based)
- "description": string - clear description of the issue
- "suggested_fix": string - the suggested fix
- "code_snippet": string - the problematic code snippet

If no issues are found, return exactly: {"issues": []}

Be precise with line numbers. Only report VERIFIED issues, not potential or hypothetical ones.

AVAILABLE TOOLS - Use them to verify before reporting issues:

1. search_text - Search the repository for text patterns
   USE WHEN: Verifying if a function/class/variable is defined, finding usages, checking imports

2. read_file - Read content of any file in the repository
   USE WHEN: Seeing full file content, checking imports at file beginning, examining related code

3. list_directory - List files and subdirectories
   USE WHEN: Verifying if a referenced file exists, understanding project structure

TOOL USAGE GUIDELINES:
- Use tools BEFORE reporting issues about missing definitions or imports
- If search_text returns results, the symbol IS defined - do not report as missing
- If you're unsure about something, use a tool to verify rather than guessing
- Tools return paginated results - check "has_more" field and use "offset" for more results"""


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
