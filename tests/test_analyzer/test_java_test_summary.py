# -*- coding: utf-8 -*-
import shutil

from testagent.analyzer.java import JavaAnalyzer
from testagent.analyzer.java.test_summary import (
    expected_test_file_path,
    summarize_existing_test_file,
)


def test_expected_test_file_path_matches_source_package_layout(tmp_path):
    path = expected_test_file_path(tmp_path, "com.example.service.OrderService")
    assert path == (
        tmp_path / "src" / "test" / "java" / "com" / "example" / "service" / "OrderServiceTest.java"
    )


def test_summarize_existing_test_file_returns_none_when_missing(tmp_path):
    assert summarize_existing_test_file(tmp_path, "com.example.Calculator") is None


def test_summarize_existing_test_file_extracts_imports_fields_and_test_signatures(tmp_path):
    test_file = tmp_path / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """\
package com.example;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

public class CalculatorTest {
    private Calculator calculator;

    @BeforeEach
    void setUp() {
        calculator = new Calculator();
    }

    @Test
    void testAddPositiveNumbers() {
        assertEquals(3, calculator.add(1, 2));
    }
}
""",
        encoding="utf-8",
    )

    summary = summarize_existing_test_file(tmp_path, "com.example.Calculator")

    assert summary is not None
    assert summary.file_path == test_file
    assert "import org.junit.jupiter.api.Test;" in summary.imports
    assert summary.class_signature == "public class CalculatorTest"
    assert "private Calculator calculator;" in summary.field_declarations
    assert any("void setUp()" in sig for sig in summary.helper_method_signatures)
    assert any("void testAddPositiveNumbers()" in sig for sig in summary.test_method_signatures)


def test_summarize_existing_test_file_treats_parameterized_test_as_test_method(tmp_path):
    test_file = tmp_path / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """\
package com.example;

import org.junit.jupiter.params.ParameterizedTest;

public class CalculatorTest {
    @ParameterizedTest
    void testParameterizedAdd() {
        // no-op
    }
}
""",
        encoding="utf-8",
    )

    summary = summarize_existing_test_file(tmp_path, "com.example.Calculator")

    assert summary is not None
    assert any("void testParameterizedAdd()" in sig for sig in summary.test_method_signatures)
    assert all("void testParameterizedAdd()" not in sig for sig in summary.helper_method_signatures)


def test_java_analyzer_attaches_existing_test_summary(sample_project, tmp_path):
    project_copy = tmp_path / "sample-java-project"
    shutil.copytree(sample_project, project_copy)

    test_file = project_copy / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        """\
package com.example;

import org.junit.jupiter.api.Test;

public class CalculatorTest {
    private Calculator calculator = new Calculator();

    @Test
    void testExistingAdd() {
        calculator.add(1, 2);
    }
}
""",
        encoding="utf-8",
    )

    ctx = JavaAnalyzer(project_copy).analyze("com.example.Calculator", "add")

    assert ctx.existing_test_summary is not None
    assert ctx.existing_test_summary.class_signature == "public class CalculatorTest"
    assert any("testExistingAdd" in sig for sig in ctx.existing_test_summary.test_method_signatures)
