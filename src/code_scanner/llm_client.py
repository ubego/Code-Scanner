"""LM Studio API client using OpenAI-compatible interface."""

import json
import logging
import time
from typing import Any, Optional

from openai import OpenAI, APIConnectionError, APIError

from .models import LLMConfig

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Error communicating with LM Studio."""

    pass


class LLMClient:
    """Client for communicating with LM Studio via OpenAI-compatible API."""

    def __init__(self, config: LLMConfig):
        """Initialize the LLM client.

        Args:
            config: LLM configuration with host, port, etc.
        """
        self.config = config
        self._client: Optional[OpenAI] = None
        self._context_limit: Optional[int] = None
        self._model_id: Optional[str] = None
        self._supports_json_format: bool = True  # Assume supported, fallback if not

    def connect(self) -> None:
        """Establish connection to LM Studio and get model info.

        Raises:
            LLMClientError: If connection fails or context limit unavailable.
        """
        logger.info(f"Connecting to LM Studio at {self.config.base_url}")

        try:
            self._client = OpenAI(
                base_url=self.config.base_url,
                api_key="lm-studio",  # LM Studio doesn't require a real key
                timeout=self.config.timeout,
            )

            # Get available models
            models = self._client.models.list()
            if not models.data:
                raise LLMClientError("No models available in LM Studio")

            # Use first model or configured model
            if self.config.model:
                model_ids = [m.id for m in models.data]
                if self.config.model not in model_ids:
                    raise LLMClientError(
                        f"Model '{self.config.model}' not found. "
                        f"Available: {model_ids}"
                    )
                self._model_id = self.config.model
            else:
                self._model_id = models.data[0].id

            logger.info(f"Using model: {self._model_id}")

            # Get context limit from config or model metadata
            if self.config.context_limit:
                self._context_limit = self.config.context_limit
                logger.info(f"Using configured context limit: {self._context_limit} tokens")
            else:
                self._context_limit = self._get_context_limit()
                if self._context_limit is not None:
                    logger.info(f"Context window size: {self._context_limit} tokens")
                else:
                    logger.warning(
                        "Could not determine context limit from LM Studio API. "
                        "Context limit must be set manually."
                    )

        except APIConnectionError as e:
            raise LLMClientError(
                f"Could not connect to LM Studio at {self.config.base_url}. "
                f"Please ensure LM Studio is running. Error: {e}"
            )
        except APIError as e:
            raise LLMClientError(f"LM Studio API error: {e}")

    def _get_context_limit(self) -> Optional[int]:
        """Get context limit from model metadata.

        Returns:
            Context limit in tokens, or None if unavailable.
        """
        if self._client is None:
            return None

        try:
            # Try to get model info
            models = self._client.models.list()
            for model in models.data:
                if model.id == self._model_id:
                    # LM Studio may provide context length in different fields
                    if hasattr(model, "context_length"):
                        return model.context_length
                    if hasattr(model, "max_tokens"):
                        return model.max_tokens
                    # Check in model metadata if available
                    if hasattr(model, "metadata"):
                        metadata = model.metadata or {}
                        if "context_length" in metadata:
                            return metadata["context_length"]

            # Fallback: try a test request to see what the model reports
            # Some LM Studio versions include context info in completions
            return self._probe_context_limit()

        except Exception as e:
            logger.warning(f"Error getting context limit: {e}")
            return None

    def _probe_context_limit(self) -> Optional[int]:
        """Probe the model to determine context limit.

        Returns:
            Estimated context limit, or None.
        """
        # LM Studio typically exposes this via the /v1/models endpoint
        # If not available, we cannot proceed (per PRD requirements)
        try:
            import urllib.request
            import urllib.error

            url = f"{self.config.base_url}/models"
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())
                for model in data.get("data", []):
                    if model.get("id") == self._model_id:
                        # Check various possible fields
                        for field in ["context_length", "max_context_length", "n_ctx"]:
                            if field in model:
                                return model[field]
        except Exception:
            pass

        return None

    @property
    def context_limit(self) -> int:
        """Get the context limit in tokens.

        Raises:
            LLMClientError: If not connected or limit unavailable.
        """
        if self._context_limit is None:
            raise LLMClientError("Not connected or context limit unavailable")
        return self._context_limit

    @property
    def model_id(self) -> str:
        """Get the model ID being used.

        Raises:
            LLMClientError: If not connected.
        """
        if self._model_id is None:
            raise LLMClientError("Not connected")
        return self._model_id

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
        """
        if self._client is None:
            raise LLMClientError("Not connected")

        for attempt in range(max_retries):
            try:
                logger.debug(f"Sending query (attempt {attempt + 1}/{max_retries})")

                # Build request parameters
                request_params = {
                    "model": self._model_id,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,  # Low temperature for consistent output
                }

                # Request high reasoning effort for better analysis
                # This is supported by LM Studio and some other providers
                request_params["reasoning_effort"] = "high"

                # Only add response_format if supported
                if self._supports_json_format:
                    request_params["response_format"] = {"type": "json_object"}

                response = self._client.chat.completions.create(**request_params)

                content = response.choices[0].message.content
                if not content:
                    logger.warning(f"Empty response from LLM (attempt {attempt + 1})")
                    continue

                # Parse JSON response
                try:
                    result = json.loads(content)
                    logger.debug("Successfully parsed JSON response")
                    return result
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Malformed JSON response (attempt {attempt + 1}): {e}"
                    )
                    logger.debug(f"Raw response: {content[:500]}...")
                    continue

            except APIConnectionError as e:
                # Connection lost mid-session - this needs special handling
                raise LLMClientError(f"Lost connection to LM Studio: {e}")
            except APIError as e:
                error_msg = str(e)
                # Check if this is a response_format not supported error
                if "response_format" in error_msg.lower() or "json_object" in error_msg.lower():
                    logger.info(
                        "[OK] Model doesn't support response_format='json_object' parameter (this is normal for many models). "
                        "Using prompt-based JSON formatting instead. This does not affect functionality."
                    )
                    self._supports_json_format = False
                    # Don't count this as a failed attempt, retry immediately
                    continue
                logger.warning(f"API error (attempt {attempt + 1}): {e}")
                continue

        raise LLMClientError(
            f"Failed to get valid JSON response after {max_retries} attempts"
        )

    def wait_for_connection(self, retry_interval: int = 10) -> None:
        """Wait for LM Studio to become available.

        Retries connection every `retry_interval` seconds until successful.

        Args:
            retry_interval: Seconds between retry attempts.
        """
        logger.info("Waiting for LM Studio connection...")

        while True:
            try:
                self.connect()
                logger.info("LM Studio connection restored")
                return
            except LLMClientError as e:
                logger.warning(f"Connection failed: {e}")
                logger.info(f"Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)

    def is_connected(self) -> bool:
        """Check if client is connected.

        Returns:
            True if connected, False otherwise.
        """
        return self._client is not None

    def is_ready(self) -> bool:
        """Check if client is ready for queries (connected and has context limit).

        Returns:
            True if ready, False otherwise.
        """
        return self._client is not None and self._context_limit is not None

    def needs_context_limit(self) -> bool:
        """Check if context limit needs to be set manually.

        Returns:
            True if context limit is not set, False otherwise.
        """
        return self._client is not None and self._context_limit is None

    def set_context_limit(self, limit: int) -> None:
        """Manually set the context limit.

        Args:
            limit: Context limit in tokens.

        Raises:
            ValueError: If limit is not positive.
        """
        if limit <= 0:
            raise ValueError("Context limit must be a positive integer")
        self._context_limit = limit
        logger.info(f"Context limit manually set to: {limit} tokens")


# System prompt template for code analysis
SYSTEM_PROMPT_TEMPLATE = """You are a code analysis assistant. Your task is to analyze source code and identify issues based on specific checks.

IMPORTANT: You must respond with a JSON object containing an "issues" array. Each issue must have:
- "file": the file path where the issue was found
- "line_number": the line number (1-based)
- "description": a clear description of the issue
- "suggested_fix": the suggested fix as code
- "code_snippet": the problematic code snippet (for context)

If no issues are found, return: {"issues": []}

Example response format:
{
  "issues": [
    {
      "file": "src/main.cpp",
      "line_number": 42,
      "description": "Heap allocation used where stack allocation would suffice",
      "suggested_fix": "MyClass obj;  // Use stack allocation instead",
      "code_snippet": "MyClass* obj = new MyClass();"
    }
  ]
}

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
