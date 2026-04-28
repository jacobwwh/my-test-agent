# -*- coding: utf-8 -*-
"""Tests for testagent.analyzer.dependency."""

from pathlib import Path

import pytest

from testagent.analyzer.java.dependency import (
    _build_import_map,
    _detect_kind,
    resolve_dependencies,
    _BUILTIN_TYPES,
)
from testagent.analyzer.java.java_parser import parse_source


# ---------------------------------------------------------------------------
# _build_import_map
# ---------------------------------------------------------------------------

class TestBuildImportMap:
    def test_explicit_import(self):
        imports = ["import com.example.model.Order;"]
        mapping = _build_import_map(imports)
        assert mapping["Order"] == "com.example.model.Order"

    def test_wildcard_import(self):
        imports = ["import com.example.model.*;"]
        mapping = _build_import_map(imports)
        assert "*com.example.model" in mapping
        assert mapping["*com.example.model"] == "com.example.model"

    def test_static_import_skipped(self):
        imports = ["import static org.junit.Assert.assertEquals;"]
        mapping = _build_import_map(imports)
        assert len(mapping) == 0

    def test_mixed_imports(self):
        imports = [
            "import com.example.model.Order;",
            "import com.example.dao.OrderDao;",
            "import java.util.List;",
            "import static org.junit.Assert.*;",
        ]
        mapping = _build_import_map(imports)
        assert mapping["Order"] == "com.example.model.Order"
        assert mapping["OrderDao"] == "com.example.dao.OrderDao"
        assert mapping["List"] == "java.util.List"
        # static import is skipped
        assert "Assert" not in mapping


# ---------------------------------------------------------------------------
# _detect_kind
# ---------------------------------------------------------------------------

class TestDetectKind:
    def test_class(self):
        root = parse_source(b"public class Foo {}")
        assert _detect_kind(root) == "class"

    def test_interface(self):
        root = parse_source(b"public interface Foo {}")
        assert _detect_kind(root) == "interface"

    def test_enum(self):
        root = parse_source(b"public enum Status { ACTIVE, INACTIVE }")
        assert _detect_kind(root) == "enum"


# ---------------------------------------------------------------------------
# resolve_dependencies
# ---------------------------------------------------------------------------

class TestResolveDependencies:
    def test_resolves_imported_class(self, sample_project):
        imports = ["import com.example.model.Order;"]
        deps = resolve_dependencies(
            sample_project,
            type_names={"Order"},
            imports=imports,
            target_package="com.example.service",
        )
        assert len(deps) == 1
        assert deps[0].qualified_name == "com.example.model.Order"
        assert deps[0].kind == "class"
        assert "class Order" in deps[0].source

    def test_resolves_interface(self, sample_project):
        imports = ["import com.example.dao.OrderDao;"]
        deps = resolve_dependencies(
            sample_project,
            type_names={"OrderDao"},
            imports=imports,
            target_package="com.example.service",
        )
        assert len(deps) == 1
        assert deps[0].kind == "interface"

    def test_resolves_same_package(self, sample_project):
        """Types in the same package should be found without an explicit import."""
        deps = resolve_dependencies(
            sample_project,
            type_names={"BaseService"},
            imports=[],
            target_package="com.example.service",
        )
        assert len(deps) == 1
        assert deps[0].qualified_name == "com.example.service.BaseService"

    def test_skips_builtin_types(self, sample_project):
        imports = ["import com.example.model.Order;"]
        deps = resolve_dependencies(
            sample_project,
            type_names={"String", "List", "Order"},
            imports=imports,
            target_package="com.example.service",
        )
        # Only Order should be resolved; String and List are builtins.
        assert len(deps) == 1
        assert deps[0].qualified_name == "com.example.model.Order"

    def test_unresolvable_type_skipped(self, sample_project):
        deps = resolve_dependencies(
            sample_project,
            type_names={"CompletelyUnknownType"},
            imports=[],
            target_package="com.example",
        )
        assert len(deps) == 0

    def test_resolves_multiple_dependencies(self, sample_project):
        imports = [
            "import com.example.model.Order;",
            "import com.example.model.Customer;",
            "import com.example.dao.OrderDao;",
        ]
        deps = resolve_dependencies(
            sample_project,
            type_names={"Order", "Customer", "OrderDao"},
            imports=imports,
            target_package="com.example.service",
        )
        names = {d.qualified_name for d in deps}
        assert "com.example.model.Order" in names
        assert "com.example.model.Customer" in names
        assert "com.example.dao.OrderDao" in names

    def test_no_duplicate_paths(self, sample_project):
        """Even if the same type appears multiple times, it should be resolved once."""
        imports = ["import com.example.model.Order;"]
        deps = resolve_dependencies(
            sample_project,
            type_names={"Order"},
            imports=imports,
            target_package="com.example.model",  # same package as Order
        )
        # Both explicit import and same-package would resolve to the same file.
        assert len(deps) == 1


# ---------------------------------------------------------------------------
# BUILTIN_TYPES coverage
# ---------------------------------------------------------------------------

class TestBuiltinTypes:
    def test_common_types_are_builtin(self):
        for t in ("String", "Integer", "List", "Map", "Object", "Optional"):
            assert t in _BUILTIN_TYPES

    def test_primitives_are_builtin(self):
        for t in ("int", "boolean", "double", "void"):
            assert t in _BUILTIN_TYPES
