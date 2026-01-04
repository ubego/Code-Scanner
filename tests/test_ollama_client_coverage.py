
import pytest
from unittest.mock import patch, MagicMock
import json
import urllib.error
from code_scanner.ollama_client import OllamaClient, LLMClientError, ContextOverflowError
from code_scanner.models import LLMConfig

class TestOllamaClientCoverage:
    """Additional tests for OllamaClient execution coverage."""

    @pytest.fixture
    def ollama_config(self) -> LLMConfig:
        return LLMConfig(
            backend="ollama",
            host="localhost",
            port=11434,
            model="llama3",
            timeout=120,
        )

    @patch("code_scanner.ollama_client.urllib.request.urlopen")
    def test_get_model_context_limit_alternatives(self, mock_urlopen, ollama_config):
        """Test getting context limit from different fields in the response."""
        # Setup common mocks
        tags_response = MagicMock()
        tags_response.read.return_value = json.dumps({"models": [{"name": "llama3:latest"}]}).encode()
        tags_response.__enter__ = MagicMock(return_value=tags_response)
        tags_response.__exit__ = MagicMock(return_value=False)
        
        # Scenario 1: context_length in modelinfo
        resp1 = MagicMock()
        resp1.read.return_value = json.dumps({"modelinfo": {"context_length": 4096}}).encode()
        resp1.__enter__ = MagicMock(return_value=resp1)
        resp1.__exit__ = MagicMock(return_value=False)
        
        # Scenario 2: n_ctx in details
        resp2 = MagicMock()
        resp2.read.return_value = json.dumps({"details": {"n_ctx": 2048}}).encode()
        resp2.__enter__ = MagicMock(return_value=resp2)
        resp2.__exit__ = MagicMock(return_value=False)
        
        # Scenario 3: parameters string
        resp3 = MagicMock()
        resp3.read.return_value = json.dumps({
            "parameters": "stop \"<|end|>\"\nnum_ctx 1024\ntemperature 0.7"
        }).encode()
        resp3.__enter__ = MagicMock(return_value=resp3)
        resp3.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [tags_response, resp1, tags_response, resp2, tags_response, resp3]

        # Test Case 1
        client1 = OllamaClient(ollama_config)
        client1.connect()
        assert client1.context_limit == 4096

        # Test Case 2
        client2 = OllamaClient(ollama_config)
        client2.connect()
        assert client2.context_limit == 2048

        # Test Case 3
        client3 = OllamaClient(ollama_config)
        client3.connect()
        assert client3.context_limit == 1024

    @patch("code_scanner.ollama_client.time.sleep")
    @patch("code_scanner.ollama_client.urllib.request.urlopen")
    def test_wait_for_connection(self, mock_urlopen, mock_sleep, ollama_config):
        """Test wait_for_connection re-tries."""
        # First call raises URLError, second call succeeds
        error_side_effect = urllib.error.URLError("Connection refused")
        
        # Success mocks
        tags_response = MagicMock()
        tags_response.read.return_value = json.dumps({"models": [{"name": "llama3:latest"}]}).encode()
        tags_response.__enter__ = MagicMock(return_value=tags_response)
        tags_response.__exit__ = MagicMock(return_value=False)
        
        show_response = MagicMock()
        show_response.read.return_value = json.dumps({"modelinfo": {"num_ctx": 4096}}).encode()
        show_response.__enter__ = MagicMock(return_value=show_response)
        show_response.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [error_side_effect, tags_response, show_response]
        
        client = OllamaClient(ollama_config)
        client.wait_for_connection(retry_interval=1)
        
        assert mock_sleep.call_count == 1

    @patch("code_scanner.ollama_client.urllib.request.urlopen")
    def test_query_json_fix_mechanism(self, mock_urlopen, ollama_config):
        """Test that malformed JSON is auto-fixed."""
        client = OllamaClient(ollama_config)
        client._connected = True
        client._model_id = "llama3"
        client._context_limit = 4096

        # 1. Malformed response
        malformed_resp = MagicMock()
        malformed_resp.read.return_value = json.dumps({
            "message": {"content": "Here is the code: {issues: []"} # invalid json
        }).encode()
        malformed_resp.__enter__ = MagicMock(return_value=malformed_resp)
        malformed_resp.__exit__ = MagicMock(return_value=False)

        # 2. Fix response from LLM
        fixed_resp = MagicMock()
        fixed_resp.read.return_value = json.dumps({
            "message": {"content": "{\"issues\": []}"}
        }).encode()
        fixed_resp.__enter__ = MagicMock(return_value=fixed_resp)
        fixed_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [malformed_resp, fixed_resp]

        result = client.query("sys", "user")
        assert result == {"issues": []}
        
    @patch("code_scanner.ollama_client.urllib.request.urlopen")
    def test_query_context_overflow_error(self, mock_urlopen, ollama_config):
        """Test handling of context overflow HTTP error."""
        client = OllamaClient(ollama_config)
        client._connected = True
        client._model_id = "llama3"
        client._context_limit = 4096

        # HTTP Error with context overflow message
        err_fp = MagicMock()
        err_fp.read.return_value = b'{"error": "model requires more context, context length exceeds limit"}'
        
        http_error = urllib.error.HTTPError(
            url="http://localhost",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=err_fp
        )
        
        mock_urlopen.side_effect = http_error

        with pytest.raises(ContextOverflowError) as exc_info:
            client.query("sys", "user")
        
        assert "context limit" in str(exc_info.value).lower()
