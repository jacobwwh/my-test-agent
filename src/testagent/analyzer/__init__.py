"""Program analysis module — language-specific source parsing and dependency extraction."""

from __future__ import annotations

from pathlib import Path

from testagent.analyzer.base import BaseAnalyzer


def create_analyzer(language: str, project_path: Path) -> BaseAnalyzer:
    """按语言创建对应的分析器实例。

    功能简介：
        根据指定语言从注册表中查找对应的分析器类，实例化后返回。
        当前仅支持 `java`；其他语言会抛出 `ValueError`。

    输入参数：
        language:
            目标语言标识符，例如 `java`。
        project_path:
            被测项目的根目录。

    返回值：
        BaseAnalyzer:
            对应语言的分析器实例。

    使用示例：
        >>> analyzer = create_analyzer("java", Path("/repo/demo"))
        >>> type(analyzer).__name__
        'JavaAnalyzer'

    异常：
        ValueError:
            当指定语言不在支持列表中时抛出。
    """
    from testagent.analyzer.java import JavaAnalyzer

    registry: dict[str, type[BaseAnalyzer]] = {
        "java": JavaAnalyzer,
    }
    cls = registry.get(language)
    if cls is None:
        raise ValueError(
            f"Unsupported language: {language!r}. Supported: {sorted(registry)}"
        )
    return cls(project_path)


# Backward-compatibility re-export: existing code using
# ``from testagent.analyzer import JavaAnalyzer`` continues to work.
from testagent.analyzer.java import JavaAnalyzer  # noqa: E402
