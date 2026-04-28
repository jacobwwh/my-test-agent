# -*- coding: utf-8 -*-
"""Tests for testagent.analyzer.java_parser."""

from pathlib import Path

import pytest

from testagent.analyzer.java.java_parser import (
    all_referenced_types,
    extract_imports,
    extract_package,
    extract_type_refs,
    find_java_file,
    find_method_node,
    list_method_names,
    parse_source,
    parse_target,
    _find_class_node,
)


# ---------------------------------------------------------------------------
# find_java_file
# ---------------------------------------------------------------------------

class TestFindJavaFile:
    def test_finds_file_in_src_main_java(self, sample_project):
        result = find_java_file(sample_project, "com.example.Calculator")
        assert result is not None
        assert result.name == "Calculator.java"
        assert result.is_file()

    def test_finds_nested_package(self, sample_project):
        result = find_java_file(sample_project, "com.example.model.Order")
        assert result is not None
        assert result.name == "Order.java"

    def test_returns_none_for_missing_class(self, sample_project):
        result = find_java_file(sample_project, "com.example.DoesNotExist")
        assert result is None


# ---------------------------------------------------------------------------
# parse_source / extract_package / extract_imports
# ---------------------------------------------------------------------------

class TestParseBasics:
    SAMPLE_SOURCE = b"""\
package com.example.service;

import java.util.List;
import com.example.model.Order;

public class Foo {
    public void bar() {}
}
"""

    def test_extract_package(self):
        root = parse_source(self.SAMPLE_SOURCE)
        assert extract_package(root) == "com.example.service"

    def test_extract_imports(self):
        root = parse_source(self.SAMPLE_SOURCE)
        imports = extract_imports(root)
        assert len(imports) == 2
        assert any("java.util.List" in i for i in imports)
        assert any("com.example.model.Order" in i for i in imports)

    def test_extract_package_empty(self):
        root = parse_source(b"public class Foo {}")
        assert extract_package(root) == ""


# ---------------------------------------------------------------------------
# Class / method location
# ---------------------------------------------------------------------------

class TestClassAndMethodLocation:
    SOURCE = b"""\
package com.example;

public class Calculator {
    public int add(int a, int b) { return a + b; }
    public int subtract(int a, int b) { return a - b; }
}
"""

    def test_find_class_node(self):
        root = parse_source(self.SOURCE)
        node = _find_class_node(root, "Calculator")
        assert node is not None
        assert node.type == "class_declaration"

    def test_find_class_node_missing(self):
        root = parse_source(self.SOURCE)
        assert _find_class_node(root, "Missing") is None

    def test_find_method_node(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "Calculator")
        method = find_method_node(cls, "add")
        assert method is not None
        assert method.type == "method_declaration"

    def test_find_method_node_missing(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "Calculator")
        assert find_method_node(cls, "multiply") is None

    def test_list_method_names(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "Calculator")
        names = list_method_names(cls)
        assert names == ["add", "subtract"]


# ---------------------------------------------------------------------------
# Type reference extraction
# ---------------------------------------------------------------------------

class TestTypeRefs:
    SOURCE = b"""\
package com.example.service;

import com.example.model.Order;
import com.example.dao.OrderDao;

public class OrderService extends BaseService implements Processable {
    private OrderDao orderDao;

    public Order process(Order order) {
        IllegalArgumentException ex = new IllegalArgumentException("bad");
        return orderDao.save(order);
    }
}
"""

    def test_extract_superclass(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "OrderService")
        method = find_method_node(cls, "process")
        refs = extract_type_refs(cls, method)
        assert refs.superclass == "BaseService"

    def test_extract_interfaces(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "OrderService")
        refs = extract_type_refs(cls, None)
        assert "Processable" in refs.interfaces

    def test_extract_field_types(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "OrderService")
        refs = extract_type_refs(cls, None)
        assert "OrderDao" in refs.field_types

    def test_extract_return_type(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "OrderService")
        method = find_method_node(cls, "process")
        refs = extract_type_refs(cls, method)
        assert refs.return_type == "Order"

    def test_extract_param_types(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "OrderService")
        method = find_method_node(cls, "process")
        refs = extract_type_refs(cls, method)
        assert "Order" in refs.param_types

    def test_extract_body_types(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "OrderService")
        method = find_method_node(cls, "process")
        refs = extract_type_refs(cls, method)
        assert "IllegalArgumentException" in refs.body_types

    def test_all_referenced_types(self):
        root = parse_source(self.SOURCE)
        cls = _find_class_node(root, "OrderService")
        method = find_method_node(cls, "process")
        refs = extract_type_refs(cls, method)
        all_types = all_referenced_types(refs)
        assert "Order" in all_types
        assert "OrderDao" in all_types
        assert "BaseService" in all_types
        assert "Processable" in all_types


# ---------------------------------------------------------------------------
# parse_target (high-level)
# ---------------------------------------------------------------------------

class TestParseTarget:
    def test_parse_calculator_add(self, sample_project):
        result = parse_target(sample_project, "com.example.Calculator", "add")
        assert result.package == "com.example"
        assert "add" in result.method_source
        assert "return a + b" in result.method_source
        assert "Calculator" in result.class_source
        assert result.file_path.name == "Calculator.java"

    def test_parse_order_service_process(self, sample_project):
        result = parse_target(
            sample_project, "com.example.service.OrderService", "process",
        )
        assert result.package == "com.example.service"
        assert "process" in result.method_source
        assert result.type_refs.superclass == "BaseService"
        assert "Processable" in result.type_refs.interfaces
        assert len(result.imports) >= 2

    def test_file_not_found(self, sample_project):
        with pytest.raises(FileNotFoundError, match="Cannot find .java file"):
            parse_target(sample_project, "com.example.Missing", "foo")

    def test_method_not_found(self, sample_project):
        with pytest.raises(ValueError, match="Method 'nonexistent' not found"):
            parse_target(sample_project, "com.example.Calculator", "nonexistent")

    def test_method_not_found_lists_available(self, sample_project):
        with pytest.raises(ValueError, match="add"):
            parse_target(sample_project, "com.example.Calculator", "nonexistent")
