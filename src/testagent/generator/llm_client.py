"""Thin wrapper around OpenAI-compatible chat completion API."""

from __future__ import annotations

import logging

from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI 兼容接口的 LLM 客户端。

    功能简介：
        封装底层 OpenAI 兼容聊天补全调用，统一处理模型名称、超时、
        连接失败和 API 状态错误，向上层暴露简洁的 `chat()` 接口。

    使用示例：
        >>> client = LLMClient("https://example.test/v1", "demo-key")
        >>> reply = client.chat([{"role": "user", "content": "hello"}])
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        model: str = "qwen3.5-397b-a17b",
        timeout: int = 120,
    ) -> None:
        """初始化 LLM 客户端。

        功能简介：
            创建一个 OpenAI 兼容客户端实例，并记录默认使用的模型名称。

        输入参数：
            api_base_url:
                OpenAI 兼容接口的基础地址。
            api_key:
                调用接口所需的认证密钥。
            model:
                默认使用的模型标识。
            timeout:
                请求超时时间，单位为秒。

        返回值：
            None:
                构造函数仅完成初始化，不返回业务结果。

        使用示例：
            >>> client = LLMClient("https://example.test/v1", "demo-key", model="demo-model")
        """
        self._model = model
        self._client = OpenAI(
            base_url=api_base_url,
            api_key=api_key,
            timeout=timeout,
        )

    def chat(self, messages: list[dict[str, str]]) -> str:
        """发送聊天补全请求并返回回复文本。

        功能简介：
            调用 OpenAI 兼容聊天接口，返回第一条候选回复的文本内容；
            同时将网络超时、连接失败和 API 错误统一转换为本模块自定义异常。

        输入参数：
            messages:
                聊天消息列表，每个元素应包含 `role` 与 `content` 字段。

        返回值：
            str:
                模型返回的文本内容；若接口返回空内容则返回空字符串。

        使用示例：
            >>> client = LLMClient("https://example.test/v1", "demo-key")
            >>> client.chat([{"role": "user", "content": "generate test"}])

        异常：
            LLMConnectionError:
                当接口超时或网络不可达时抛出。
            LLMAPIError:
                当接口返回非成功状态码时抛出。
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
    """LLM 接口连接异常。

    功能简介：
        表示请求 LLM 接口时出现连接失败或超时等网络层问题。

    输入参数：
        无。

    返回值：
        无。

    使用示例：
        >>> raise LLMConnectionError("Cannot connect")
    """


class LLMAPIError(Exception):
    """LLM 接口业务异常。

    功能简介：
        表示 LLM 服务端返回了错误状态，例如鉴权失败、限流或参数错误。

    输入参数：
        无。

    返回值：
        无。

    使用示例：
        >>> raise LLMAPIError("LLM API returned error 429")
    """
