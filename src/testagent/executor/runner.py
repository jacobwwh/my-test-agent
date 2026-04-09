"""Parse Maven / Gradle build output into structured result fields.

Functions here are pure: they receive the raw build output string and return
structured data. No I/O is performed.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Maven output parsing
# ---------------------------------------------------------------------------

# Maven prints this when compilation of tests fails:
#   [ERROR] COMPILATION ERROR :
#   [ERROR] /path/to/Foo.java:[10,5] error: ...
_MAVEN_COMPILE_ERROR_HEADER = re.compile(
    r"\[ERROR\]\s+COMPILATION ERROR", re.IGNORECASE
)

# Maven BUILD FAILURE / BUILD SUCCESS line
_MAVEN_BUILD_RESULT = re.compile(r"\[INFO\]\s+BUILD\s+(SUCCESS|FAILURE)", re.IGNORECASE)

# Maven test failure summary: "Tests run: X, Failures: Y, Errors: Z"
_MAVEN_TESTS_RUN = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)"
)

# Surefire failure method name:  "<<< FAILURE!" preceded by the test name
# e.g.  "testAdd(com.example.CalculatorTest)  Time elapsed: 0.01 s  <<< FAILURE!"
_MAVEN_FAILED_TEST = re.compile(
    r"(\w+)\([\w.]+\)\s+Time elapsed:.*?<<<\s+(?:FAILURE|ERROR)"
)

# Plain Maven [ERROR] lines that contain compile errors
_MAVEN_COMPILE_LINE = re.compile(r"^\[ERROR\]\s+.+\.java:\[\d+", re.MULTILINE)


def parse_maven_result(returncode: int, output: str) -> dict:
    """Parse Maven build output.

    Returns a dict with keys:
    - ``compiled`` (bool)
    - ``compile_errors`` (str)
    - ``passed`` (bool)
    - ``test_output`` (str)
    - ``failed_tests`` (list[str])
    """
    has_compile_error = bool(_MAVEN_COMPILE_ERROR_HEADER.search(output))
    compiled = not has_compile_error

    compile_errors = ""
    if not compiled:
        # Collect all [ERROR] lines from the compile section.
        error_lines = _MAVEN_COMPILE_LINE.findall(output)
        compile_errors = "\n".join(error_lines) if error_lines else output

    # Determine pass/fail from test results or build outcome.
    passed = False
    failed_tests: list[str] = []

    if compiled:
        test_matches = _MAVEN_TESTS_RUN.findall(output)
        if test_matches:
            total_failures = sum(int(f) + int(e) for _, f, e in test_matches)
            passed = total_failures == 0 and returncode == 0
        else:
            # No test summary found — treat non-zero returncode as failure.
            passed = returncode == 0

        if not passed:
            failed_tests = _MAVEN_FAILED_TEST.findall(output)

    return {
        "compiled": compiled,
        "compile_errors": compile_errors,
        "passed": passed,
        "test_output": output,
        "failed_tests": failed_tests,
    }


# ---------------------------------------------------------------------------
# Gradle output parsing
# ---------------------------------------------------------------------------

# Gradle test failure: "> X tests completed, Y failed"
_GRADLE_TEST_SUMMARY = re.compile(r"(\d+) tests completed,\s*(\d+) failed")

# Gradle BUILD SUCCESSFUL / BUILD FAILED
_GRADLE_BUILD_RESULT = re.compile(r"BUILD\s+(SUCCESSFUL|FAILED)", re.IGNORECASE)

# Gradle compilation error: "error: " lines
_GRADLE_COMPILE_ERROR = re.compile(r"error:\s+.+", re.IGNORECASE)

# Gradle compilation failure marker
_GRADLE_COMPILE_FAILED = re.compile(
    r"Compilation failed|compileTestJava FAILED|> Could not resolve", re.IGNORECASE
)

# Gradle failed test method:
# "  CalculatorTest > testDivideByZero FAILED"
# "  FAILED com.example.CalculatorTest > testDivideByZero"
_GRADLE_FAILED_TEST = re.compile(
    r"FAILED\s+[\w.]+\s*>\s*(\w+)|>\s*(\w+)\s+FAILED", re.MULTILINE
)


def parse_gradle_result(returncode: int, output: str) -> dict:
    """Parse Gradle build output.

    Returns the same dict shape as :func:`parse_maven_result`.
    """
    has_compile_failure = bool(_GRADLE_COMPILE_FAILED.search(output))
    compiled = not has_compile_failure

    compile_errors = ""
    if not compiled:
        error_lines = _GRADLE_COMPILE_ERROR.findall(output)
        compile_errors = "\n".join(error_lines) if error_lines else output

    passed = False
    failed_tests: list[str] = []

    if compiled:
        summary_match = _GRADLE_TEST_SUMMARY.search(output)
        if summary_match:
            n_failed = int(summary_match.group(2))
            passed = n_failed == 0 and returncode == 0
        else:
            passed = returncode == 0

        if not passed:
            matches = _GRADLE_FAILED_TEST.findall(output)
            # Each match is a tuple (group1, group2); take whichever is non-empty.
            for g1, g2 in matches:
                name = g1 or g2
                if name:
                    failed_tests.append(name)

    return {
        "compiled": compiled,
        "compile_errors": compile_errors,
        "passed": passed,
        "test_output": output,
        "failed_tests": list(dict.fromkeys(failed_tests)),  # deduplicate, preserve order
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def parse_build_result(build_tool: str, returncode: int, output: str) -> dict:
    """Dispatch to the appropriate parser based on *build_tool*."""
    if build_tool == "maven":
        return parse_maven_result(returncode, output)
    if build_tool == "gradle":
        return parse_gradle_result(returncode, output)
    raise ValueError(f"Unknown build tool: {build_tool!r}")
