"""Integration tests for testagent.analyzer.JavaAnalyzer."""

from pathlib import Path

import pytest

from testagent.analyzer import JavaAnalyzer
from testagent.models import AnalysisContext, TargetMethod, Dependency


class TestJavaAnalyzer:
    def test_analyze_calculator_add(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        ctx = analyzer.analyze("com.example.Calculator", "add")

        assert isinstance(ctx, AnalysisContext)
        assert ctx.target.class_name == "com.example.Calculator"
        assert ctx.target.method_name == "add"
        assert "return a + b" in ctx.target.method_signature
        assert "Calculator" in ctx.target.class_source
        assert ctx.package == "com.example"
        # Calculator has no project-local dependencies (only primitives).
        assert ctx.dependencies == []

    def test_analyze_order_service_process(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        ctx = analyzer.analyze("com.example.service.OrderService", "process")

        assert ctx.target.method_name == "process"
        assert ctx.package == "com.example.service"

        # Should have resolved Order, OrderDao, BaseService, Processable
        dep_names = {d.qualified_name for d in ctx.dependencies}
        assert "com.example.model.Order" in dep_names
        assert "com.example.dao.OrderDao" in dep_names
        # BaseService and Processable are in the same package
        assert "com.example.service.BaseService" in dep_names
        assert "com.example.service.Processable" in dep_names

    def test_analyze_order_service_find_order(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        ctx = analyzer.analyze("com.example.service.OrderService", "findOrder")

        assert "findById" in ctx.target.method_signature
        dep_names = {d.qualified_name for d in ctx.dependencies}
        assert "com.example.dao.OrderDao" in dep_names

    def test_analyze_preserves_imports(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        ctx = analyzer.analyze("com.example.service.OrderService", "process")

        assert len(ctx.imports) >= 2
        assert any("com.example.model.Order" in imp for imp in ctx.imports)
        assert any("com.example.dao.OrderDao" in imp for imp in ctx.imports)

    def test_analyze_dependency_kinds(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        ctx = analyzer.analyze("com.example.service.OrderService", "process")

        kinds = {d.qualified_name: d.kind for d in ctx.dependencies}
        assert kinds["com.example.model.Order"] == "class"
        assert kinds["com.example.dao.OrderDao"] == "interface"
        assert kinds["com.example.service.Processable"] == "interface"
        assert kinds["com.example.service.BaseService"] == "class"

    def test_analyze_dependency_sources_not_empty(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        ctx = analyzer.analyze("com.example.service.OrderService", "process")

        for dep in ctx.dependencies:
            assert len(dep.source) > 0
            assert dep.file_path.is_file()

    def test_file_not_found_error(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        with pytest.raises(FileNotFoundError):
            analyzer.analyze("com.example.NoSuchClass", "method")

    def test_method_not_found_error(self, sample_project):
        analyzer = JavaAnalyzer(sample_project)
        with pytest.raises(ValueError, match="not found"):
            analyzer.analyze("com.example.Calculator", "nonexistent")
