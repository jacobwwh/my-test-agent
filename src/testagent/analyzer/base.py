# -*- coding: utf-8 -*-
"""Abstract base class for language-specific analyzers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from testagent.models import AnalysisContext


class BaseAnalyzer(ABC):
    """语言分析器抽象基类。

    功能简介：
        定义分析器的统一接口，各语言的具体分析器需继承此类并实现 `analyze` 方法。

    使用示例：
        >>> class JavaAnalyzer(BaseAnalyzer):
        ...     def analyze(self, class_name, method_name):
        ...         ...
    """

    def __init__(self, project_path: Path) -> None:
        """初始化分析器。

        输入参数：
            project_path:
                被测项目的根目录。
        """
        self.project_path = project_path

    @abstractmethod
    def analyze(self, class_name: str, method_name: str) -> AnalysisContext:
        """分析目标方法并返回上下文。

        输入参数：
            class_name:
                目标类的全限定名（或语言等价标识）。
            method_name:
                目标方法（或函数）名。

        返回值：
            AnalysisContext:
                包含目标方法、依赖、imports 等信息的分析上下文。
        """

    def list_testable_methods(self) -> list[tuple[str, str]]:
        """列出当前项目中可作为测试目标的方法。

        功能简介：
            各语言分析器可按自身规则实现该方法，用于批量测试生成入口。
            默认实现表示当前语言尚不支持自动发现。

        返回值：
            list[tuple[str, str]]:
                `(class_name, method_name)` 形式的目标方法列表。

        异常：
            NotImplementedError:
                当前语言分析器未实现自动发现时抛出。
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support testable method discovery."
        )
