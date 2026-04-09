"""Thin wrapper around OpenAI-compatible chat completion API."""

from __future__ import annotations

import logging

from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for calling LLMs via OpenAI-compatible API.

    Parameters
    ----------
    api_base_url:
        Base URL of the OpenAI-compatible endpoint (e.g. yunwu API URL).
    api_key:
        API key for authentication.
    model:
        Model identifier to use for completions.
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        model: str = "qwen3.5-397b-a17b",
        timeout: int = 120,
    ) -> None:
        self._model = model
        self._client = OpenAI(
            base_url=api_base_url,
            api_key=api_key,
            timeout=timeout,
        )

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat completion request and return the assistant reply.

        Parameters
        ----------
        messages:
            List of message dicts with ``role`` and ``content`` keys,
            following the OpenAI chat format.

        Returns
        -------
        str
            The text content of the first choice in the response.

        Raises
        ------
        LLMConnectionError
            When the API endpoint is unreachable.
        LLMAPIError
            When the API returns an error status.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
            )
        except APITimeoutError as exc:
            raise LLMConnectionError(
                f"Request to LLM API at {self._client.base_url} timed out."
            ) from exc
        except APIConnectionError as exc:
            raise LLMConnectionError(
                f"Cannot connect to LLM API at {self._client.base_url}. "
                "Check the URL and your network connection."
            ) from exc
        except APIStatusError as exc:
            raise LLMAPIError(
                f"LLM API returned error {exc.status_code}: {exc.message}"
            ) from exc

        return response.choices[0].message.content or ""


class LLMConnectionError(Exception):
    """Raised when the LLM API endpoint is unreachable or times out."""


class LLMAPIError(Exception):
    """Raised when the LLM API returns an error status."""
