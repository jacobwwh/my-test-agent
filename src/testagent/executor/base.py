# -*- coding: utf-8 -*-
"""Abstract base class for language-specific test executors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from testagent.models import AnalysisContext, GeneratedTest, TestResult


class BaseExecutor(ABC):
    """测试执行器抽象基类。

    功能简介：
        定义执行器的统一接口，各语言的具体执行器需继承此类并实现 `execute` 方法。

    使用示例：
        >>> class JavaTestExecutor(BaseExecutor):
        ...     def execute(self, test, context):
        ...         ...
    """

    def __init__(
        self,
        project_path: Path,
        reports_dir: Path | None = None,
        keep_test: bool = False,
        build_timeout: int = 300,
    ) -> None:
        """初始化执行器。

        输入参数：
            project_path:
                被测项目的根目录。
            reports_dir:
                覆盖率报告输出目录；为 `None` 时由子类决定默认值。
            keep_test:
                执行结束后是否保留写入或合并到项目中的测试文件；具体清理、
                删除或恢复策略由各语言执行器决定。
            build_timeout:
                构建命令的超时时间，单位为秒。
        """
        self.project_path = project_path
        self.reports_dir = reports_dir
        self.keep_test = keep_test
        self.build_timeout = build_timeout

    @abstractmethod
    def execute(self, test: GeneratedTest, context: AnalysisContext) -> TestResult:
        """执行生成的测试并返回结构化结果。

        输入参数：
            test:
                待执行的测试代码对象。
            context:
                分析上下文，用于提供目标类名、方法名等信息。

        返回值：
            TestResult:
                结构化执行结果，包含编译状态、失败信息和覆盖率。
        """
