"""Tests for prompt building."""

from pathlib import Path

import pytest

from testagent.models import (
    AnalysisContext,
    CoverageReport,
    Dependency,
    GeneratedTest,
    TestFileSummary,
    TargetMethod,
    TestResult,
)
from testagent.generator.prompt import build_generate_prompt, build_refine_prompt


@pytest.fixture
def sample_target() -> TargetMethod:
    return TargetMethod(
        class_name="com.example.Calculator",
        method_name="add",
        method_signature="public int add(int a, int b) { return a + b; }",
        file_path=Path("/project/src/main/java/com/example/Calculator.java"),
        class_source=(
            "package com.example;\n"
            "\n"
            "public class Calculator {\n"
            "    public int add(int a, int b) { return a + b; }\n"
            "}"
        ),
    )


@pytest.fixture
def sample_context(sample_target: TargetMethod) -> AnalysisContext:
    return AnalysisContext(
        target=sample_target,
        dependencies=[
            Dependency(
                kind="class",
                qualified_name="com.example.MathUtils",
                source="public class MathUtils { public static int abs(int x) { return x < 0 ? -x : x; } }",
                file_path=Path("/project/src/main/java/com/example/MathUtils.java"),
            ),
        ],
        imports=["import com.example.MathUtils;"],
        package="com.example",
    )


@pytest.fixture
def prompts_dir() -> Path:
    """Point to the actual Java prompts directory."""
    return Path(__file__).resolve().parent.parent.parent / "prompts" / "java"


class TestBuildGeneratePrompt:
    def test_returns_single_user_message(self, sample_context, prompts_dir):
        messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_includes_target_method(self, sample_context, prompts_dir):
        messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "Calculator" in content
        assert "add" in content
        assert "public int add(int a, int b)" in content

    def test_includes_dependencies(self, sample_context, prompts_dir):
        messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "MathUtils" in content
        assert "com.example.MathUtils" in content

    def test_includes_imports(self, sample_context, prompts_dir):
        messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "import com.example.MathUtils;" in content

    def test_includes_existing_test_summary(self, sample_context, prompts_dir):
        sample_context.existing_test_summary = TestFileSummary(
            file_path=Path("/project/src/test/java/com/example/CalculatorTest.java"),
            imports=[
                "import org.junit.jupiter.api.Test;",
                "import static org.junit.jupiter.api.Assertions.*;",
            ],
            class_signature="public class CalculatorTest",
            field_declarations=["private Calculator calculator;"],
            helper_method_signatures=["private Calculator createCalculator();"],
            test_method_signatures=[
                "void testExistingAdd();",
                "void testExistingSubtract();",
            ],
        )

        messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "## Existing Test File Summary" in content
        assert "CalculatorTest.java" in content
        assert "import org.junit.jupiter.api.Test;" in content
        assert "public class CalculatorTest" in content
        assert "private Calculator calculator;" in content
        assert "private Calculator createCalculator();" in content
        assert "void testExistingAdd();" in content
        assert "avoid duplicate imports, fields, helper methods, and test method names" in content
        assert "Reuse compatible shared objects and helpers when they already exist." in content

    def test_requires_target_method_only_tests(self, sample_context, prompts_dir):
        messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "only for the target method" in content
        assert "Do not generate tests for other methods" in content
        assert "same package as the target class" in content

    def test_no_dependencies_section_when_empty(self, sample_target, prompts_dir):
        ctx = AnalysisContext(
            target=sample_target,
            dependencies=[],
            imports=[],
            package="com.example",
        )
        messages = build_generate_prompt(ctx, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "## Dependencies" not in content


class TestBuildRefinePrompt:
    @pytest.fixture
    def previous_test(self) -> GeneratedTest:
        return GeneratedTest(
            test_code="public class CalcTest { @Test void testAdd() { assertEquals(3, 1+2); } }",
            iteration=1,
        )

    @pytest.fixture
    def compile_fail_result(self) -> TestResult:
        return TestResult(
            compiled=False,
            compile_errors="error: cannot find symbol\n  symbol: method assertEquals",
            passed=False,
            test_output="",
            coverage=None,
            failed_tests=[],
        )

    @pytest.fixture
    def test_fail_result(self) -> TestResult:
        return TestResult(
            compiled=True,
            compile_errors="",
            passed=False,
            test_output="expected: <3> but was: <5>",
            coverage=None,
            failed_tests=["testAdd"],
        )

    @pytest.fixture
    def coverage_gap_result(self) -> TestResult:
        return TestResult(
            compiled=True,
            compile_errors="",
            passed=True,
            test_output="Tests passed.",
            coverage=CoverageReport(
                line_coverage=0.6,
                branch_coverage=0.4,
                uncovered_lines=[15, 16, 20],
                uncovered_branches=["line 10: false branch not covered"],
            ),
            failed_tests=[],
        )

    def test_returns_single_user_message(self, sample_context, previous_test, compile_fail_result, prompts_dir):
        messages = build_refine_prompt(sample_context, previous_test, compile_fail_result, prompts_dir=prompts_dir)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_includes_compile_errors(self, sample_context, previous_test, compile_fail_result, prompts_dir):
        messages = build_refine_prompt(sample_context, previous_test, compile_fail_result, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "Compilation Errors" in content
        assert "cannot find symbol" in content

    def test_includes_test_failures(self, sample_context, previous_test, test_fail_result, prompts_dir):
        messages = build_refine_prompt(sample_context, previous_test, test_fail_result, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "Test Failures" in content
        assert "testAdd" in content

    def test_includes_coverage_gaps(self, sample_context, previous_test, coverage_gap_result, prompts_dir):
        messages = build_refine_prompt(sample_context, previous_test, coverage_gap_result, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "Coverage Gaps" in content
        assert "60.0%" in content
        assert "40.0%" in content
        assert "15" in content
        assert "false branch not covered" in content

    def test_includes_previous_test_code(self, sample_context, previous_test, compile_fail_result, prompts_dir):
        messages = build_refine_prompt(sample_context, previous_test, compile_fail_result, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "CalcTest" in content
        assert "Iteration 1" in content

    def test_requires_target_method_only_refinement(self, sample_context, previous_test, compile_fail_result, prompts_dir):
        messages = build_refine_prompt(sample_context, previous_test, compile_fail_result, prompts_dir=prompts_dir)
        content = messages[0]["content"]
        assert "Output the COMPLETE fixed test class" in content
        assert "same package as the target class" in content
        assert "only for the target method" in content
        assert "Do not add tests for other methods" in content
