# -*- coding: utf-8 -*-
"""Tests for testagent.executor.runner."""

import pytest

from testagent.executor.java.runner import (
    parse_build_result,
    parse_gradle_result,
    parse_maven_result,
)


# ---------------------------------------------------------------------------
# Realistic build output samples
# ---------------------------------------------------------------------------

MAVEN_SUCCESS = """\
[INFO] --- maven-surefire-plugin:3.2.5:test (default-test) @ sample-java-project ---
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.45 s
[INFO] BUILD SUCCESS
"""

MAVEN_COMPILE_ERROR = """\
[INFO] --- maven-compiler-plugin:3.11.0:testCompile (default-testCompile) ---
[ERROR] COMPILATION ERROR :
[ERROR] /src/test/java/com/example/CalculatorTest.java:[10,5] error: ';' expected
[ERROR] /src/test/java/com/example/CalculatorTest.java:[15,1] error: reached end of file
[INFO] BUILD FAILURE
"""

MAVEN_TEST_FAILURE = """\
[INFO] --- maven-surefire-plugin:3.2.5:test (default-test) @ sample-java-project ---
[ERROR] testDivideByZero(com.example.CalculatorTest)  Time elapsed: 0.01 s  <<< FAILURE!
[ERROR] testAdd(com.example.CalculatorTest)  Time elapsed: 0.01 s  <<< ERROR!
[INFO] Tests run: 3, Failures: 1, Errors: 1, Skipped: 0
[INFO] BUILD FAILURE
"""

MAVEN_MULTIPLE_RUNS = """\
[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0
[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0
[INFO] BUILD SUCCESS
"""

MAVEN_NO_TESTS_SUCCESS = """\
[INFO] No tests to run.
[INFO] BUILD SUCCESS
"""

MAVEN_NO_TESTS_FAILURE = """\
[INFO] No tests to run.
[INFO] BUILD FAILURE
"""

GRADLE_SUCCESS = """\
> Task :test
3 tests completed, 0 failed
BUILD SUCCESSFUL in 2s
"""

GRADLE_COMPILE_FAILED = """\
> Task :compileTestJava FAILED
error: cannot find symbol
  symbol: class Calculator
BUILD FAILED in 1s
"""

GRADLE_TEST_FAILURE_FORMAT1 = """\
> Task :test
3 tests completed, 1 failed
  FAILED com.example.CalculatorTest > testDivideByZero
BUILD FAILED in 2s
"""

GRADLE_TEST_FAILURE_FORMAT2 = """\
> Task :test
2 tests completed, 1 failed
  CalculatorTest > testBadInput FAILED
BUILD FAILED in 2s
"""

GRADLE_COMPILE_FAILED_RESOLVE = """\
> Could not resolve com.example:missing-lib:1.0
BUILD FAILED
"""


# ---------------------------------------------------------------------------
# parse_maven_result
# ---------------------------------------------------------------------------

class TestParseMavenResult:
    def test_success(self):
        r = parse_maven_result(0, MAVEN_SUCCESS)
        assert r["compiled"] is True
        assert r["passed"] is True
        assert r["compile_errors"] == ""
        assert r["failed_tests"] == []

    def test_compile_error(self):
        r = parse_maven_result(1, MAVEN_COMPILE_ERROR)
        assert r["compiled"] is False
        assert r["passed"] is False
        assert "CalculatorTest.java" in r["compile_errors"]

    def test_compile_error_compile_errors_not_empty(self):
        r = parse_maven_result(1, MAVEN_COMPILE_ERROR)
        assert len(r["compile_errors"]) > 0

    def test_test_failure(self):
        r = parse_maven_result(1, MAVEN_TEST_FAILURE)
        assert r["compiled"] is True
        assert r["passed"] is False
        assert "testDivideByZero" in r["failed_tests"]
        assert "testAdd" in r["failed_tests"]

    def test_multiple_test_runs_all_pass(self):
        r = parse_maven_result(0, MAVEN_MULTIPLE_RUNS)
        assert r["compiled"] is True
        assert r["passed"] is True

    def test_no_tests_success(self):
        r = parse_maven_result(0, MAVEN_NO_TESTS_SUCCESS)
        assert r["compiled"] is True
        assert r["passed"] is True

    def test_no_tests_failure(self):
        r = parse_maven_result(1, MAVEN_NO_TESTS_FAILURE)
        assert r["compiled"] is True
        assert r["passed"] is False

    def test_test_output_contains_raw_output(self):
        r = parse_maven_result(0, MAVEN_SUCCESS)
        assert "BUILD SUCCESS" in r["test_output"]

    def test_failed_tests_empty_on_success(self):
        r = parse_maven_result(0, MAVEN_SUCCESS)
        assert r["failed_tests"] == []


# ---------------------------------------------------------------------------
# parse_gradle_result
# ---------------------------------------------------------------------------

class TestParseGradleResult:
    def test_success(self):
        r = parse_gradle_result(0, GRADLE_SUCCESS)
        assert r["compiled"] is True
        assert r["passed"] is True
        assert r["failed_tests"] == []

    def test_compile_failed(self):
        r = parse_gradle_result(1, GRADLE_COMPILE_FAILED)
        assert r["compiled"] is False
        assert r["passed"] is False
        assert "cannot find symbol" in r["compile_errors"]

    def test_compile_failed_resolve(self):
        r = parse_gradle_result(1, GRADLE_COMPILE_FAILED_RESOLVE)
        assert r["compiled"] is False

    def test_test_failure_format1(self):
        r = parse_gradle_result(1, GRADLE_TEST_FAILURE_FORMAT1)
        assert r["compiled"] is True
        assert r["passed"] is False
        assert "testDivideByZero" in r["failed_tests"]

    def test_test_failure_format2(self):
        r = parse_gradle_result(1, GRADLE_TEST_FAILURE_FORMAT2)
        assert r["compiled"] is True
        assert r["passed"] is False
        assert "testBadInput" in r["failed_tests"]

    def test_no_duplicate_failed_tests(self):
        output = """\
2 tests completed, 1 failed
FAILED com.example.FooTest > testSomething
> testSomething FAILED
BUILD FAILED
"""
        r = parse_gradle_result(1, output)
        assert r["failed_tests"].count("testSomething") == 1

    def test_failed_tests_empty_on_success(self):
        r = parse_gradle_result(0, GRADLE_SUCCESS)
        assert r["failed_tests"] == []

    def test_test_output_contains_raw_output(self):
        r = parse_gradle_result(0, GRADLE_SUCCESS)
        assert "BUILD SUCCESSFUL" in r["test_output"]


# ---------------------------------------------------------------------------
# parse_build_result (dispatcher)
# ---------------------------------------------------------------------------

class TestParseBuildResult:
    def test_dispatches_maven(self):
        r = parse_build_result("maven", 0, MAVEN_SUCCESS)
        assert r["passed"] is True

    def test_dispatches_gradle(self):
        r = parse_build_result("gradle", 0, GRADLE_SUCCESS)
        assert r["passed"] is True

    def test_raises_on_unknown_tool(self):
        with pytest.raises(ValueError, match="Unknown build tool"):
            parse_build_result("ant", 0, "")
