# -*- coding: utf-8 -*-
"""Convenience script to run analyzer tests from the project root.

Usage:
    python test_analyzer.py                # list all tests and prompt for selection
    python test_analyzer.py -a             # run all tests directly
    python test_analyzer.py <extra args>   # pass extra args to pytest (e.g. -k "parse")
"""

import subprocess
import sys


TEST_DIR = "tests/test_analyzer/"


def _collect_tests() -> list[str]:
    """收集 analyzer 测试用例列表。

    功能简介：
        调用 `pytest --collect-only` 枚举 `tests/test_analyzer/` 下的所有测试节点，
        并提取可用于后续交互式选择的测试 ID 列表。

    输入参数：
        无。

    返回值：
        list[str]:
            收集到的 pytest 测试节点 ID 列表。

    使用示例：
        >>> tests = _collect_tests()
        >>> isinstance(tests, list)
        True
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_DIR, "--collect-only", "-q"],
        capture_output=True, text=True,
    )
    tests = [
        line for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    ]
    return tests


def _interactive_select(tests: list[str]) -> list[str]:
    """交互式选择要执行的测试。

    功能简介：
        在终端中打印编号菜单，允许用户通过序号、区间、`a` 或 `q`
        选择要运行的 analyzer 测试用例。

    输入参数：
        tests:
            可供选择的测试节点 ID 列表。

    返回值：
        list[str]:
            用户选择后的测试节点 ID 列表；若用户退出或未选中则可能为空列表。

    使用示例：
        >>> _interactive_select(["tests/test_analyzer/test_demo.py::test_x"])
    """
    print(f"\nFound {len(tests)} test(s):\n")
    for i, t in enumerate(tests, 1):
        print(f"  [{i:>2}] {t}")

    print(
        "\nEnter test numbers to run (comma-separated), "
        "a range (e.g. 1-5), 'a' for all, or 'q' to quit:"
    )
    choice = input("> ").strip()

    if choice.lower() == "q":
        return []
    if choice.lower() == "a":
        return tests

    selected: list[str] = []
    for part in choice.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            for idx in range(int(lo), int(hi) + 1):
                if 1 <= idx <= len(tests):
                    selected.append(tests[idx - 1])
        elif part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(tests):
                selected.append(tests[idx - 1])
    return selected


def main() -> int:
    """脚本主入口。

    功能简介：
        负责解析脚本参数，并在“直接转发给 pytest”与“交互式选择测试后执行”
        两种模式之间切换，最终返回 pytest 的退出码。

    输入参数：
        无。

    返回值：
        int:
            命令退出码；通常与底层 pytest 执行结果一致。

    使用示例：
        >>> exit_code = main()
    """
    args = sys.argv[1:]

    # If any args given, delegate directly to pytest.
    if args:
        if args == ["-a"]:
            args = []
        return subprocess.call(
            [sys.executable, "-m", "pytest", TEST_DIR, "-v", *args],
        )

    # Interactive mode: collect, select, run.
    tests = _collect_tests()
    if not tests:
        print("No tests found.")
        return 1

    selected = _interactive_select(tests)
    if not selected:
        print("No tests selected.")
        return 0

    print(f"\nRunning {len(selected)} test(s)...\n")
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-v", *selected],
    )


if __name__ == "__main__":
    sys.exit(main())
