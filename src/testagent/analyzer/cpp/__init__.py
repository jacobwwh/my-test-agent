# -*- coding: utf-8 -*-
"""C++-specific analyzer implementation."""

from __future__ import annotations

from testagent.analyzer.base import BaseAnalyzer
from testagent.analyzer.cpp.cpp_parser import (
    list_testable_methods,
    parse_target,
    resolve_project_dependencies,
)
from testagent.models import AnalysisContext, TargetMethod


class CppAnalyzer(BaseAnalyzer):
    """C++ 方法分析器门面类。

    功能简介：
        解析 C++ 目标类方法、项目内双引号 include 依赖以及同名实现文件，
        并输出与 Java 分析器一致的 `AnalysisContext`，供生成器复用同一
        Analyzer -> Generator -> Executor 流水线。
    """

    def analyze(self, class_name: str, method_name: str) -> AnalysisContext:
        """分析 C++ 目标方法并返回生成上下文。

        输入参数：
            class_name:
                目标类名，可包含命名空间，例如 `shop::PricingService`。
            method_name:
                目标方法名。

        返回值：
            AnalysisContext:
                包含目标方法源码、类声明、include 列表、命名空间和依赖源码。
        """
        parsed = parse_target(self.project_path, class_name, method_name)
        roots = [parsed.file_path]
        if parsed.header_path is not None:
            roots.append(parsed.header_path)
        dependencies = resolve_project_dependencies(self.project_path, roots)

        target = TargetMethod(
            class_name=class_name,
            method_name=method_name,
            method_signature=parsed.method_source,
            file_path=parsed.file_path,
            class_source=parsed.class_source,
        )

        return AnalysisContext(
            target=target,
            dependencies=dependencies,
            imports=parsed.imports,
            package=parsed.namespace,
            existing_test_summary=None,
        )

    def list_testable_methods(self) -> list[tuple[str, str]]:
        """列出 C++ 项目中 public 方法测试目标。"""
        return list_testable_methods(self.project_path)
