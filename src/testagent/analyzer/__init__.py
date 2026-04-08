"""Program analysis module — Java source parsing and dependency extraction."""

from __future__ import annotations

from pathlib import Path

from testagent.analyzer.dependency import resolve_dependencies
from testagent.analyzer.java_parser import all_referenced_types, parse_target
from testagent.models import AnalysisContext, TargetMethod


class JavaAnalyzer:
    """Facade that analyses a Java method and its project-local dependencies.

    Usage::

        analyzer = JavaAnalyzer(Path("/path/to/java-project"))
        ctx = analyzer.analyze("com.example.MyService", "processOrder")
    """

    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path

    def analyze(self, class_name: str, method_name: str) -> AnalysisContext:
        """Parse *class_name* and extract context for *method_name*.

        Raises
        ------
        FileNotFoundError
            If the .java file for *class_name* cannot be located.
        ValueError
            If the class or method cannot be found inside the file.
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
