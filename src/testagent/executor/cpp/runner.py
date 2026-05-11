# -*- coding: utf-8 -*-
"""Parse C++ Makefile build output into structured result fields."""

from __future__ import annotations

import re

_COMPILE_ERROR_LINE = re.compile(
    r"(?im)^.*(?:\berror:|undefined reference|ld:.*symbol|collect2: error).*$"
)
_ASSERTION_FAILURE = re.compile(r"Assertion failed|assertion failed|SIGABRT|Abort trap", re.IGNORECASE)


def parse_make_result(returncode: int, output: str) -> dict:
    """解析 C++ Makefile 测试输出。

    功能简介：
        根据编译器/链接器错误特征判断是否编译成功；编译成功后以进程退出码
        判断测试是否通过，并为运行期失败提供 `main` 作为失败入口名称。

    输入参数：
        returncode:
            make 进程退出码。
        output:
            标准输出与标准错误合并文本。

    返回值：
        dict:
            与 Java runner 相同结构的解析结果。
    """
    error_lines = _COMPILE_ERROR_LINE.findall(output)
    compiled = not error_lines
    compile_errors = "\n".join(error_lines)

    passed = compiled and returncode == 0
    failed_tests: list[str] = []
    if compiled and not passed:
        failed_tests.append("main")
    elif _ASSERTION_FAILURE.search(output):
        failed_tests.append("main")

    return {
        "compiled": compiled,
        "compile_errors": compile_errors if not compiled else "",
        "passed": passed,
        "test_output": output,
        "failed_tests": failed_tests,
    }
