# -*- coding: utf-8 -*-
"""Tests for TestExecutor (testagent.executor.__init__)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from testagent.executor import TestExecutor
from testagent.models import AnalysisContext, CoverageReport, GeneratedTest, TargetMethod


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SIMPLE_TEST_CODE = """\
package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class CalculatorTest {
    @Test
    void testAdd() { assertEquals(3, 1 + 2); }
}
"""

WRONG_GENERATED_TEST_CODE = """\
package com.generated.wrong;

import org.junit.jupiter.api.Test;

public class TotallyWrongName {
    @Test
    void generatedMethod() {
        assert true;
    }
}
"""

MAVEN_SUCCESS_OUTPUT = (
    "[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0\n"
    "[INFO] BUILD SUCCESS\n"
)

MAVEN_COMPILE_ERROR_OUTPUT = (
    "[ERROR] COMPILATION ERROR :\n"
    "[ERROR] /src/CalculatorTest.java:[5,1] error: ';' expected\n"
    "[INFO] BUILD FAILURE\n"
)

MAVEN_TEST_FAILURE_OUTPUT = (
    "[ERROR] testAdd(com.example.CalculatorTest)  Time elapsed: 0.01 s  <<< FAILURE!\n"
    "[INFO] Tests run: 1, Failures: 1, Errors: 0, Skipped: 0\n"
    "[INFO] BUILD FAILURE\n"
)


@pytest.fixture
def maven_project(tmp_path) -> Path:
    (tmp_path / "pom.xml").touch()
    return tmp_path


@pytest.fixture
def gradle_project(tmp_path) -> Path:
    (tmp_path / "build.gradle").touch()
    return tmp_path


def _make_context(class_name="com.example.Calculator", method_name="add") -> AnalysisContext:
    return AnalysisContext(
        target=TargetMethod(
            class_name=class_name,
            method_name=method_name,
            method_signature="public int add(int a, int b) { return a + b; }",
            file_path=Path("/dummy/Calculator.java"),
            class_source="public class Calculator {}",
        ),
        dependencies=[],
        imports=[],
        package="com.example",
    )


def _make_test(code=SIMPLE_TEST_CODE, iteration=1) -> GeneratedTest:
    return GeneratedTest(test_code=code, iteration=iteration)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestTestExecutorInit:
    def test_detects_maven(self, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "reports")
        assert executor._build_tool == "maven"

    def test_detects_gradle(self, gradle_project, tmp_path):
        executor = TestExecutor(gradle_project, reports_dir=tmp_path / "reports")
        assert executor._build_tool == "gradle"

    def test_raises_on_no_build_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            TestExecutor(tmp_path, reports_dir=tmp_path / "reports")

    def test_default_reports_dir_is_set(self, maven_project):
        executor = TestExecutor(maven_project)
        assert executor.reports_dir is not None
        assert "tmp" in str(executor.reports_dir)

    def test_keep_test_default_false(self, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path)
        assert executor.keep_test is False


# ---------------------------------------------------------------------------
# execute() — happy path (mocked build)
# ---------------------------------------------------------------------------

class TestExecuteSuccess:
    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_returns_test_result(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r")
        result = executor.execute(_make_test(), _make_context())
        assert result.compiled is True
        assert result.passed is True
        assert result.failed_tests == []

    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_build_command_uses_target_class_not_generated_class(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r")
        executor.execute(_make_test(code=WRONG_GENERATED_TEST_CODE), _make_context())
        cmd_used = mock_run.call_args[0][1]
        assert any("com.example.CalculatorTest" in arg for arg in cmd_used)
        assert not any("TotallyWrongName" in arg for arg in cmd_used)

    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_test_file_removed_after_execution(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r", keep_test=False)
        executor.execute(_make_test(), _make_context())
        # The test file should have been cleaned up.
        test_dir = maven_project / "src" / "test" / "java" / "com" / "example"
        leftover = list(test_dir.glob("*.java")) if test_dir.exists() else []
        assert leftover == []

    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_test_file_kept_when_keep_test_true(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r", keep_test=True)
        executor.execute(_make_test(), _make_context())
        test_dir = maven_project / "src" / "test" / "java" / "com" / "example"
        assert (test_dir / "CalculatorTest.java").is_file()

    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_preexisting_test_file_is_restored_when_keep_test_false(self, mock_run, maven_project, tmp_path):
        test_dir = maven_project / "src" / "test" / "java" / "com" / "example"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / "CalculatorTest.java"
        original_content = """\
package com.example;

import org.junit.jupiter.api.Test;

public class CalculatorTest {
    @Test
    void humanTest() { assertEquals(3, 1 + 2); }
}
"""
        test_file.write_text(original_content, encoding="utf-8")

        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r", keep_test=False)
        executor.execute(_make_test(code=WRONG_GENERATED_TEST_CODE), _make_context())

        assert test_file.is_file()
        assert test_file.read_text(encoding="utf-8") == original_content

    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_coverage_none_when_no_xml(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r")
        result = executor.execute(_make_test(), _make_context())
        # No jacoco.xml was created, so coverage should be None.
        assert result.coverage is None

    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_coverage_populated_when_xml_present(self, mock_run, maven_project, tmp_path):
        reports_dir = tmp_path / "reports"
        # Pre-create the jacoco.xml in the expected location.
        report_subdir = (
            reports_dir
            / "com_example_Calculator"
            / "add"
            / "iter1"
        )
        report_subdir.mkdir(parents=True)
        jacoco_xml = report_subdir / "jacoco.xml"
        jacoco_xml.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<report name="t"><package name="com/example">'
            '<class name="com/example/Calculator">'
            '<counter type="LINE" missed="0" covered="5"/>'
            '<counter type="BRANCH" missed="0" covered="2"/>'
            '</class>'
            '<sourcefile name="Calculator.java"/>'
            '</package></report>',
            encoding="utf-8",
        )
        executor = TestExecutor(maven_project, reports_dir=reports_dir)
        result = executor.execute(_make_test(), _make_context())
        assert result.coverage is not None
        assert result.coverage.line_coverage == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# execute() — failure cases
# ---------------------------------------------------------------------------

class TestExecuteFailures:
    @patch("testagent.executor.java.run_build", return_value=(1, MAVEN_COMPILE_ERROR_OUTPUT))
    def test_compile_error(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r")
        result = executor.execute(_make_test(), _make_context())
        assert result.compiled is False
        assert result.passed is False
        assert len(result.compile_errors) > 0

    @patch("testagent.executor.java.run_build", return_value=(1, MAVEN_TEST_FAILURE_OUTPUT))
    def test_test_failure(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r")
        result = executor.execute(_make_test(), _make_context())
        assert result.compiled is True
        assert result.passed is False
        assert "testAdd" in result.failed_tests

    @patch("testagent.executor.java.run_build", side_effect=Exception("timeout"))
    def test_build_process_exception(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r")
        result = executor.execute(_make_test(), _make_context())
        assert result.compiled is False
        assert "timeout" in result.compile_errors

    @patch("testagent.executor.java.run_build", side_effect=Exception("timeout"))
    def test_test_file_removed_when_build_process_exception(self, mock_run, maven_project, tmp_path):
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r", keep_test=False)
        executor.execute(_make_test(), _make_context())
        test_dir = maven_project / "src" / "test" / "java" / "com" / "example"
        leftover = list(test_dir.glob("*.java")) if test_dir.exists() else []
        assert leftover == []

    def test_invalid_test_code_returns_error(self, maven_project, tmp_path):
        """Test code without a 'public class' declaration should fail gracefully."""
        bad_test = GeneratedTest(test_code="interface NotAClass {}", iteration=1)
        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r")
        result = executor.execute(bad_test, _make_context())
        assert result.compiled is False
        assert len(result.compile_errors) > 0


# ---------------------------------------------------------------------------
# execute() — report directory structure
# ---------------------------------------------------------------------------

class TestReportDirStructure:
    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_report_dir_keyed_by_class_method_iter(self, mock_run, maven_project, tmp_path):
        reports_dir = tmp_path / "reports"
        executor = TestExecutor(maven_project, reports_dir=reports_dir)
        executor.execute(_make_test(iteration=2), _make_context())
        expected = (
            reports_dir
            / "com_example_Calculator"
            / "add"
            / "iter2"
        )
        assert expected.is_dir()

    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_different_iterations_get_separate_dirs(self, mock_run, maven_project, tmp_path):
        reports_dir = tmp_path / "reports"
        executor = TestExecutor(maven_project, reports_dir=reports_dir)
        ctx = _make_context()
        executor.execute(_make_test(iteration=1), ctx)
        executor.execute(_make_test(iteration=2), ctx)
        assert (reports_dir / "com_example_Calculator" / "add" / "iter1").is_dir()
        assert (reports_dir / "com_example_Calculator" / "add" / "iter2").is_dir()


# ---------------------------------------------------------------------------
# execute() — Gradle project
# ---------------------------------------------------------------------------

class TestExecuteGradle:
    @patch("testagent.executor.java.run_build", return_value=(0, "3 tests completed, 0 failed\nBUILD SUCCESSFUL"))
    def test_gradle_success(self, mock_run, gradle_project, tmp_path):
        executor = TestExecutor(gradle_project, reports_dir=tmp_path / "r")
        result = executor.execute(_make_test(), _make_context())
        assert result.compiled is True
        assert result.passed is True

    @patch("testagent.executor.java.run_build", return_value=(0, "3 tests completed, 0 failed\nBUILD SUCCESSFUL"))
    def test_gradle_command_passed_to_run_build(self, mock_run, gradle_project, tmp_path):
        executor = TestExecutor(gradle_project, reports_dir=tmp_path / "r")
        executor.execute(_make_test(), _make_context())
        cmd_used = mock_run.call_args[0][1]  # second positional arg is the command
        assert "test" in cmd_used
        assert "jacocoTestReport" in cmd_used
