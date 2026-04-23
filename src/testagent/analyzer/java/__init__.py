"""Java-specific analyzer implementation."""

from __future__ import annotations

from pathlib import Path

from testagent.analyzer.base import BaseAnalyzer
from testagent.analyzer.java.dependency import resolve_dependencies
from testagent.analyzer.java.java_parser import (
    all_referenced_types,
    list_testable_methods,
    parse_target,
)
from testagent.analyzer.java.test_summary import summarize_existing_test_file
from testagent.models import AnalysisContext, TargetMethod


class JavaAnalyzer(BaseAnalyzer):
    """Java 方法分析器门面类。

    功能简介：
        对外提供统一的分析入口，负责协调源码解析与依赖解析，
        将目标方法转换为生成测试所需的 `AnalysisContext`。若真实项目中
        已存在对应测试文件，还会附加该文件的结构摘要，供生成 prompt
        复用已有 import、字段、helper 和测试方法签名信息。

    使用示例：
        >>> analyzer = JavaAnalyzer(Path("/path/to/java-project"))
        >>> ctx = analyzer.analyze("com.example.MyService", "processOrder")
        >>> ctx.target.method_name
        'processOrder'
    """

    def analyze(self, class_name: str, method_name: str) -> AnalysisContext:
        """分析目标类方法并生成上下文结果。

        功能简介：
            先解析目标类与目标方法，再提取其中引用到的类型，
            并解析这些类型对应的项目内依赖源码；同时尝试查找对应的
            `src/test/java/<package>/<ClassName>Test.java` 并生成摘要，
            最终返回 `AnalysisContext`。

        输入参数：
            class_name:
                目标类的全限定类名，例如 `com.example.Calculator`。
            method_name:
                目标方法名，例如 `add`。

        返回值：
            AnalysisContext:
                包含目标方法、依赖源码、imports、package，以及可选的
                `existing_test_summary`。

        使用示例：
            >>> analyzer = JavaAnalyzer(Path("/repo/demo"))
            >>> ctx = analyzer.analyze("com.example.Calculator", "add")
            >>> ctx.package
            'com.example'

        异常：
            FileNotFoundError:
                当目标类对应的 `.java` 文件不存在时抛出。
            ValueError:
                当目标类或方法在源码中不存在时抛出。
        """
        result = parse_target(self.project_path, class_name, method_name)

        # Resolve project-local dependencies from the collected type references.
        type_names = all_referenced_types(result.type_refs)
        dependencies = resolve_dependencies(
            self.project_path,
            type_names,
            result.imports,
            result.package,
        )

        target = TargetMethod(
            class_name=class_name,
            method_name=method_name,
            method_signature=result.method_source,
            file_path=result.file_path,
            class_source=result.class_source,
        )
        existing_test_summary = summarize_existing_test_file(self.project_path, class_name)

        return AnalysisContext(
            target=target,
            dependencies=dependencies,
            imports=result.imports,
            package=result.package,
            existing_test_summary=existing_test_summary,
        )

    def list_testable_methods(self) -> list[tuple[str, str]]:
        """列出项目中所有可作为测试目标的 Java 方法。

        功能简介：
            委托 Java 解析模块扫描源码目录，返回所有非 private 等可测试
            方法的 `(class_name, method_name)` 列表，供 `test_executor.py --all`
            批量生成测试目标使用。

        返回值：
            list[tuple[str, str]]:
                所有发现的可测试 Java 方法。
        """
        return list_testable_methods(self.project_path)
