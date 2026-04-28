# -*- coding: utf-8 -*-
"""Test execution module — language-specific test compilation, execution, and coverage collection."""

from __future__ import annotations

from pathlib import Path

from testagent.executor.base import BaseExecutor


def create_executor(language: str, project_path: Path, **kwargs) -> BaseExecutor:
    """按语言创建对应的测试执行器实例。

    功能简介：
        根据指定语言从注册表中查找对应的执行器类，实例化后返回。
        当前仅支持 `java`；其他语言会抛出 `ValueError`。

    输入参数：
        language:
            目标语言标识符，例如 `java`。
        project_path:
            被测项目的根目录。
        **kwargs:
            传递给执行器构造函数的额外关键字参数，例如 `reports_dir`、
            `keep_test`、`build_timeout`。`keep_test` 的具体清理/恢复语义
            由语言执行器实现。

    返回值：
        BaseExecutor:
            对应语言的测试执行器实例。

    使用示例：
        >>> executor = create_executor("java", Path("/repo/demo"), keep_test=True)
        >>> type(executor).__name__
        'JavaTestExecutor'

    异常：
        ValueError:
            当指定语言不在支持列表中时抛出。
    """
    from testagent.executor.java import JavaTestExecutor

    registry: dict[str, type[BaseExecutor]] = {
        "java": JavaTestExecutor,
    }
    cls = registry.get(language)
    if cls is None:
        raise ValueError(
            f"Unsupported language: {language!r}. Supported: {sorted(registry)}"
        )
    return cls(project_path, **kwargs)


# Backward-compatibility re-export: existing code using
# ``from testagent.executor import TestExecutor`` continues to work.
from testagent.executor.java import TestExecutor  # noqa: E402
