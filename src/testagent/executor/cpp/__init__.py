# -*- coding: utf-8 -*-
"""C++-specific test executor implementation."""

from __future__ import annotations

import logging
from pathlib import Path

from testagent.executor.base import BaseExecutor
from testagent.executor.cpp.builder import (
    build_make_command,
    detect_build_tool,
    run_build,
    write_test_file,
)
from testagent.executor.cpp.runner import parse_make_result
from testagent.models import AnalysisContext, GeneratedTest, TestResult

logger = logging.getLogger(__name__)

_DEFAULT_REPORTS_ROOT = Path(__file__).resolve().parents[4] / "tmp" / "reports"


class CppTestExecutor(BaseExecutor):
    """C++ 测试执行器。

    功能简介：
        将生成的 C++ 测试源文件写入项目的 `tests/testagent/generated/`，
        调用项目 Makefile 的 `testagent-test` 目标执行编译和测试，并把结果
        转换为统一的 `TestResult`。
    """

    def __init__(
        self,
        project_path: Path,
        reports_dir: Path | None = None,
        keep_test: bool = False,
        build_timeout: int = 300,
    ) -> None:
        """初始化 C++ 测试执行器。"""
        super().__init__(
            project_path=project_path,
            reports_dir=reports_dir or _DEFAULT_REPORTS_ROOT,
            keep_test=keep_test,
            build_timeout=build_timeout,
        )
        self._build_tool = detect_build_tool(project_path)

    def execute(self, test: GeneratedTest, context: AnalysisContext) -> TestResult:
        """执行生成的 C++ 测试并返回结构化结果。"""
        test_file: Path | None = None
        try:
            test_file = write_test_file(
                test_code=test.test_code,
                project_path=self.project_path,
                class_name=context.target.class_name,
                method_name=context.target.method_name,
                iteration=test.iteration,
            )
        except Exception as exc:
            logger.error("Failed to write C++ test file: %s", exc)
            return TestResult(
                compiled=False,
                compile_errors=f"Failed to write C++ test file: {exc}",
                passed=False,
                test_output="",
                coverage=None,
            )

        report_dir = (
            self.reports_dir
            / context.target.class_name.replace("::", "_")
            / context.target.method_name
            / f"iter{test.iteration}"
        )
        report_dir.mkdir(parents=True, exist_ok=True)
        command = build_make_command(self.project_path, test_file, report_dir)

        try:
            try:
                returncode, output = run_build(
                    self.project_path,
                    command,
                    timeout=self.build_timeout,
                )
            except Exception as exc:
                logger.error("C++ build process error: %s", exc)
                return TestResult(
                    compiled=False,
                    compile_errors=f"C++ build process failed: {exc}",
                    passed=False,
                    test_output="",
                    coverage=None,
                )

            parsed = parse_make_result(returncode, output)
            return TestResult(
                compiled=parsed["compiled"],
                compile_errors=parsed["compile_errors"],
                passed=parsed["passed"],
                test_output=parsed["test_output"],
                coverage=None,
                failed_tests=parsed["failed_tests"],
            )
        finally:
            if not self.keep_test and test_file and test_file.is_file():
                test_file.unlink()
                logger.info("Removed C++ generated test file: %s", test_file)
