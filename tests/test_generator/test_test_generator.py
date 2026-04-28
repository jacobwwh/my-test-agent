# -*- coding: utf-8 -*-
"""Tests for TestGenerator (generate and refine with mocked LLM)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from testagent.models import (
    AnalysisContext,
    CoverageReport,
    Dependency,
    GeneratedTest,
    TargetMethod,
    TestResult,
)
from testagent.generator.test_generator import TestGenerator, normalize_test_class_name


@pytest.fixture
def sample_context() -> AnalysisContext:
    return AnalysisContext(
        target=TargetMethod(
            class_name="com.example.Calculator",
            method_name="add",
            method_signature="public int add(int a, int b) { return a + b; }",
            file_path=Path("/project/src/main/java/com/example/Calculator.java"),
            class_source=(
                "package com.example;\n"
                "public class Calculator {\n"
                "    public int add(int a, int b) { return a + b; }\n"
                "}"
            ),
        ),
        dependencies=[],
        imports=[],
        package="com.example",
    )


MOCK_LLM_GENERATE_RESPONSE = (
    "Here is the test:\n\n"
    "```java\n"
    "package com.example;\n"
    "\n"
    "import org.junit.jupiter.api.Test;\n"
    "import static org.junit.jupiter.api.Assertions.*;\n"
    "\n"
    "public class CalculatorTest {\n"
    "    @Test\n"
    "    void testAdd() {\n"
    "        Calculator calc = new Calculator();\n"
    "        assertEquals(3, calc.add(1, 2));\n"
    "    }\n"
    "}\n"
    "```"
)

MOCK_LLM_REFINE_RESPONSE = (
    "Fixed test:\n\n"
    "```java\n"
    "package com.example;\n"
    "\n"
    "import org.junit.jupiter.api.Test;\n"
    "import static org.junit.jupiter.api.Assertions.*;\n"
    "\n"
    "public class CalculatorTest {\n"
    "    @Test\n"
    "    void testAdd() {\n"
    "        Calculator calc = new Calculator();\n"
    "        assertEquals(3, calc.add(1, 2));\n"
    "    }\n"
    "\n"
    "    @Test\n"
    "    void testAddNegative() {\n"
    "        Calculator calc = new Calculator();\n"
    "        assertEquals(-1, calc.add(1, -2));\n"
    "    }\n"
    "}\n"
    "```"
)


class TestTestGenerator:
    @patch("testagent.generator.test_generator.LLMClient")
    def test_generate_returns_generated_test(self, mock_llm_cls, sample_context):
        mock_client = MagicMock()
        mock_client.chat.return_value = MOCK_LLM_GENERATE_RESPONSE
        mock_llm_cls.return_value = mock_client

        generator = TestGenerator(
            api_base_url="https://api.example.com/v1",
            api_key="test-key",
        )
        result = generator.generate(sample_context)

        assert isinstance(result, GeneratedTest)
        assert result.iteration == 1
        assert "CalculatorTest" in result.test_code
        assert "testAdd" in result.test_code
        assert "```" not in result.test_code

    @patch("testagent.generator.test_generator.LLMClient")
    def test_generate_calls_llm_with_messages(self, mock_llm_cls, sample_context):
        mock_client = MagicMock()
        mock_client.chat.return_value = MOCK_LLM_GENERATE_RESPONSE
        mock_llm_cls.return_value = mock_client

        generator = TestGenerator(
            api_base_url="https://api.example.com/v1",
            api_key="test-key",
        )
        generator.generate(sample_context)

        mock_client.chat.assert_called_once()
        messages = mock_client.chat.call_args[0][0]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Calculator" in messages[0]["content"]

    @patch("testagent.generator.test_generator.LLMClient")
    def test_refine_increments_iteration(self, mock_llm_cls, sample_context):
        mock_client = MagicMock()
        mock_client.chat.return_value = MOCK_LLM_REFINE_RESPONSE
        mock_llm_cls.return_value = mock_client

        generator = TestGenerator(
            api_base_url="https://api.example.com/v1",
            api_key="test-key",
        )

        previous = GeneratedTest(test_code="old test code", iteration=2)
        test_result = TestResult(
            compiled=True,
            compile_errors="",
            passed=False,
            test_output="expected: <3> but was: <5>",
            coverage=None,
            failed_tests=["testAdd"],
        )

        result = generator.refine(sample_context, previous, test_result)

        assert isinstance(result, GeneratedTest)
        assert result.iteration == 3
        assert "testAddNegative" in result.test_code

    @patch("testagent.generator.test_generator.LLMClient")
    def test_refine_passes_feedback_to_llm(self, mock_llm_cls, sample_context):
        mock_client = MagicMock()
        mock_client.chat.return_value = MOCK_LLM_REFINE_RESPONSE
        mock_llm_cls.return_value = mock_client

        generator = TestGenerator(
            api_base_url="https://api.example.com/v1",
            api_key="test-key",
        )

        previous = GeneratedTest(test_code="old test", iteration=1)
        test_result = TestResult(
            compiled=False,
            compile_errors="error: cannot find symbol",
            passed=False,
            test_output="",
            coverage=None,
        )

        generator.refine(sample_context, previous, test_result)

        messages = mock_client.chat.call_args[0][0]
        content = messages[0]["content"]
        assert "cannot find symbol" in content
        assert "old test" in content

    @patch("testagent.generator.test_generator.LLMClient")
    def test_refine_with_coverage_feedback(self, mock_llm_cls, sample_context):
        mock_client = MagicMock()
        mock_client.chat.return_value = MOCK_LLM_REFINE_RESPONSE
        mock_llm_cls.return_value = mock_client

        generator = TestGenerator(
            api_base_url="https://api.example.com/v1",
            api_key="test-key",
        )

        previous = GeneratedTest(test_code="old test", iteration=1)
        test_result = TestResult(
            compiled=True,
            compile_errors="",
            passed=True,
            test_output="OK",
            coverage=CoverageReport(
                line_coverage=0.5,
                branch_coverage=0.3,
                uncovered_lines=[10, 15],
                uncovered_branches=["line 8: else branch"],
            ),
        )

        generator.refine(sample_context, previous, test_result)

        messages = mock_client.chat.call_args[0][0]
        content = messages[0]["content"]
        assert "50.0%" in content
        assert "30.0%" in content
        assert "else branch" in content


def test_normalize_test_class_name_accepts_package_private_class():
    test_code = (
        "package com.example.service;\n\n"
        "class WrongName {\n"
        "}\n"
    )

    normalized = normalize_test_class_name(test_code, "com.example.service.OrderService")

    assert "class OrderServiceTest" in normalized
    assert "class WrongName" not in normalized
