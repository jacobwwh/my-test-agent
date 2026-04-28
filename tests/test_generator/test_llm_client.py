# -*- coding: utf-8 -*-
"""Tests for LLM client (mocked OpenAI API)."""

from unittest.mock import MagicMock, patch

import pytest

from testagent.generator.llm_client import LLMClient, LLMConnectionError, LLMAPIError


@pytest.fixture
def mock_openai_response():
    """Create a mock ChatCompletion response."""
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = "```java\npublic class FooTest {}\n```"
    response.choices = [choice]
    return response


class TestLLMClient:
    @patch("testagent.generator.llm_client.OpenAI")
    def test_chat_returns_response_content(self, mock_openai_cls, mock_openai_response):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_openai_response
        mock_openai_cls.return_value = mock_client

        client = LLMClient(
            api_base_url="https://api.example.com/v1",
            api_key="test-key",
            model="test-model",
        )
        result = client.chat([{"role": "user", "content": "hello"}])

        assert "FooTest" in result
        mock_client.chat.completions.create.assert_called_once_with(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

    @patch("testagent.generator.llm_client.OpenAI")
    def test_chat_returns_empty_on_none_content(self, mock_openai_cls):
        response = MagicMock()
        choice = MagicMock()
        choice.message.content = None
        response.choices = [choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = response
        mock_openai_cls.return_value = mock_client

        client = LLMClient(api_base_url="https://api.example.com/v1", api_key="k")
        assert client.chat([{"role": "user", "content": "hi"}]) == ""

    @patch("testagent.generator.llm_client.OpenAI")
    def test_connection_error_raises_llm_connection_error(self, mock_openai_cls):
        from openai import APIConnectionError

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APIConnectionError(
            request=MagicMock()
        )
        mock_client.base_url = "https://api.example.com/v1"
        mock_openai_cls.return_value = mock_client

        client = LLMClient(api_base_url="https://api.example.com/v1", api_key="k")
        # Overwrite the internal _client reference since we mocked the class
        client._client = mock_client

        with pytest.raises(LLMConnectionError, match="Cannot connect"):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("testagent.generator.llm_client.OpenAI")
    def test_timeout_error_raises_llm_connection_error(self, mock_openai_cls):
        from openai import APITimeoutError

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            request=MagicMock()
        )
        mock_client.base_url = "https://api.example.com/v1"
        mock_openai_cls.return_value = mock_client

        client = LLMClient(api_base_url="https://api.example.com/v1", api_key="k")
        client._client = mock_client

        with pytest.raises(LLMConnectionError, match="timed out"):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("testagent.generator.llm_client.OpenAI")
    def test_api_status_error_raises_llm_api_error(self, mock_openai_cls):
        from openai import APIStatusError

        mock_client = MagicMock()
        error = APIStatusError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        )
        error.status_code = 429
        mock_client.chat.completions.create.side_effect = error
        mock_client.base_url = "https://api.example.com/v1"
        mock_openai_cls.return_value = mock_client

        client = LLMClient(api_base_url="https://api.example.com/v1", api_key="k")
        client._client = mock_client

        with pytest.raises(LLMAPIError, match="429"):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("testagent.generator.llm_client.OpenAI")
    def test_passes_correct_params_to_constructor(self, mock_openai_cls):
        LLMClient(
            api_base_url="https://yunwu.ai/v1",
            api_key="my-key",
            model="qwen3.5-397b-a17b",
            timeout=60,
        )
        mock_openai_cls.assert_called_once_with(
            base_url="https://yunwu.ai/v1",
            api_key="my-key",
            timeout=60,
        )
