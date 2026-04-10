"""Program analysis module — Java source parsing and dependency extraction."""

from __future__ import annotations

from pathlib import Path

from testagent.analyzer.dependency import resolve_dependencies
from testagent.analyzer.java_parser import all_referenced_types, parse_target
from testagent.models import AnalysisContext, TargetMethod


class JavaAnalyzer:
    """Java 方法分析器门面类。

    功能简介：
        对外提供统一的分析入口，负责协调源码解析与依赖解析，
        将目标方法转换为生成测试所需的 `AnalysisContext`。

    使用示例：
        >>> analyzer = JavaAnalyzer(Path("/path/to/java-project"))
        >>> ctx = analyzer.analyze("com.example.MyService", "processOrder")
        >>> ctx.target.method_name
        'processOrder'
    """

    def __init__(self, project_path: Path) -> None:
        """初始化分析器。

        功能简介：
            保存项目根目录，供后续定位 Java 源码文件和解析依赖时使用。

        输入参数：
            project_path:
                Java 项目根目录。

        返回值：
            None:
                构造函数仅完成实例初始化，不返回业务结果。

        使用示例：
            >>> analyzer = JavaAnalyzer(Path("/repo/demo"))
            >>> analyzer.project_path
            Path('/repo/demo')
        """
        self.project_path = project_path

    def analyze(self, class_name: str, method_name: str) -> AnalysisContext:
        """分析目标类方法并生成上下文结果。

        功能简介：
            先解析目标类与目标方法，再提取其中引用到的类型，
            并解析这些类型对应的项目内依赖源码，最终返回 `AnalysisContext`。

        输入参数：
            class_name:
                目标类的全限定类名，例如 `com.example.Calculator`。
            method_name:
                目标方法名，例如 `add`。

        返回值：
            AnalysisContext:
                包含目标方法、依赖源码、imports 和 package 的分析上下文。

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

        return AnalysisContext(
            target=target,
            dependencies=dependencies,
            imports=result.imports,
            package=result.package,
        )
