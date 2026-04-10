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
    """解析 Maven 构建输出。

    功能简介：
        根据 Maven 控制台输出判断测试是否编译成功、是否全部通过，
        并提取编译错误信息与失败测试名称。

    输入参数：
        returncode:
            Maven 进程退出码。
        output:
            Maven 标准输出与标准错误合并后的文本。

    返回值：
        dict:
            结构化解析结果，包含 `compiled`、`compile_errors`、`passed`、
            `test_output` 和 `failed_tests` 等字段。

    使用示例：
        >>> parse_maven_result(0, "[INFO] BUILD SUCCESS")
        {'compiled': True, 'compile_errors': '', 'passed': True, 'test_output': '[INFO] BUILD SUCCESS', 'failed_tests': []}
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
    """解析 Gradle 构建输出。

    功能简介：
        根据 Gradle 控制台输出判断编译状态和测试通过情况，并抽取编译错误、
        失败测试名等信息，返回与 Maven 解析器一致的数据结构。

    输入参数：
        returncode:
            Gradle 进程退出码。
        output:
            Gradle 标准输出与标准错误合并后的文本。

    返回值：
        dict:
            与 `parse_maven_result()` 相同结构的解析结果字典。

    使用示例：
        >>> parse_gradle_result(0, "3 tests completed, 0 failed\\nBUILD SUCCESSFUL")
        {'compiled': True, 'compile_errors': '', 'passed': True, 'test_output': '3 tests completed, 0 failed\\nBUILD SUCCESSFUL', 'failed_tests': []}
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
    """按构建工具类型分发输出解析逻辑。

    功能简介：
        根据 `build_tool` 的取值调用 Maven 或 Gradle 对应的输出解析函数。

    输入参数：
        build_tool:
            构建工具类型，支持 `maven` 或 `gradle`。
        returncode:
            构建命令退出码。
        output:
            构建命令输出文本。

    返回值：
        dict:
            结构化解析结果字典。

    使用示例：
        >>> parse_build_result("maven", 0, "[INFO] BUILD SUCCESS")

    异常：
        ValueError:
            当 `build_tool` 不是已支持的构建工具时抛出。
    """
    if build_tool == "maven":
        return parse_maven_result(returncode, output)
    if build_tool == "gradle":
        return parse_gradle_result(returncode, output)
    raise ValueError(f"Unknown build tool: {build_tool!r}")
