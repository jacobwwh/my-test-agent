"""Test execution module — compile, run, and collect coverage for generated tests."""

from __future__ import annotations

import logging
from pathlib import Path

from testagent.executor.builder import (
    build_gradle_command,
    build_maven_command,
    cleanup_generated_tests,
    detect_build_tool,
    extract_class_name_from_code,
    extract_package_from_code,
    run_build,
    write_test_file,
)
from testagent.executor.coverage import find_jacoco_xml, parse_jacoco_xml
from testagent.executor.runner import parse_build_result
from testagent.models import AnalysisContext, GeneratedTest, TestResult

logger = logging.getLogger(__name__)

# Default location for JaCoCo reports relative to the testagent project root.
# Resolved from this file: src/testagent/executor/__init__.py → 3 levels up.
_DEFAULT_REPORTS_ROOT = Path(__file__).resolve().parents[3] / "tmp" / "reports"


class TestExecutor:
    """测试执行器。

    功能简介：
        负责把生成的 JUnit 测试写入被测项目、调用构建工具执行测试、
        解析编译/运行结果，并在可用时收集 JaCoCo 覆盖率。

    使用示例：
        >>> executor = TestExecutor(Path("/repo/java-project"))
        >>> result = executor.execute(test, context)
    """

    def __init__(
        self,
        project_path: Path,
        reports_dir: Path | None = None,
        keep_test: bool = False,
        build_timeout: int = 300,
    ) -> None:
        """初始化测试执行器。

        功能简介：
            保存项目路径与执行参数，并在初始化阶段检测被测项目使用的是
            Maven 还是 Gradle。

        输入参数：
            project_path:
                被测 Java 项目的根目录。
            reports_dir:
                覆盖率报告输出目录；为 `None` 时使用默认目录。
            keep_test:
                是否在执行结束后保留写入项目中的测试文件。
            build_timeout:
                构建/测试命令的超时时间，单位为秒。

        返回值：
            None:
                构造函数仅完成初始化。

        使用示例：
            >>> executor = TestExecutor(Path("/repo/java-project"), keep_test=True)
        """
        self.project_path = project_path
        self.reports_dir = reports_dir or _DEFAULT_REPORTS_ROOT
        self.keep_test = keep_test
        self.build_timeout = build_timeout
        self._build_tool = detect_build_tool(project_path)
        logger.info(
            "TestExecutor initialised: project=%s, build_tool=%s",
            project_path, self._build_tool,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(self, test: GeneratedTest, context: AnalysisContext) -> TestResult:
        """执行生成的测试并返回结构化结果。

        功能简介：
            该方法会将测试代码写入项目测试目录，调用 Maven/Gradle 执行构建，
            解析编译与测试输出，并尝试读取 JaCoCo 覆盖率，最后按配置清理测试文件。

        输入参数：
            test:
                待执行的测试代码对象。
            context:
                分析上下文，用于提供目标类名、方法名等执行信息。

        返回值：
            TestResult:
                结构化执行结果，包含编译状态、失败信息、原始输出和覆盖率。

        使用示例：
            >>> result = executor.execute(test, context)
            >>> result.compiled
            True
        """
        class_name = context.target.class_name
        method_name = context.target.method_name

        # --- Write test file ---
        test_file: Path | None = None
        try:
            test_file = write_test_file(
                test_code=test.test_code,
                project_path=self.project_path,
                class_name=class_name,
                method_name=method_name,
                iteration=test.iteration,
            )
        except Exception as exc:
            logger.error("Failed to write test file: %s", exc)
            return TestResult(
                compiled=False,
                compile_errors=f"Failed to write test file: {exc}",
                passed=False,
                test_output="",
                coverage=None,
            )

        test_class = extract_class_name_from_code(test.test_code)
        package = extract_package_from_code(test.test_code)

        # Per-target report directory keyed by class and method.
        report_dir = (
            self.reports_dir
            / class_name.replace(".", "_")
            / method_name
            / f"iter{test.iteration}"
        )
        report_dir.mkdir(parents=True, exist_ok=True)

        # --- Build command ---
        if self._build_tool == "maven":
            command = build_maven_command(
                self.project_path, test_class, package, report_dir,
            )
        else:
            command = build_gradle_command(
                self.project_path, test_class, package, report_dir,
            )

        # --- Clean stale coverage data ---
        stale_exec = self.project_path / "target" / "jacoco.exec"
        if stale_exec.is_file():
            stale_exec.unlink()
            logger.info("Removed stale %s", stale_exec)

        try:
            # --- Run build ---
            try:
                returncode, output = run_build(
                    self.project_path, command, timeout=self.build_timeout,
                )
            except Exception as exc:
                logger.error("Build process error: %s", exc)
                return TestResult(
                    compiled=False,
                    compile_errors=f"Build process failed: {exc}",
                    passed=False,
                    test_output="",
                    coverage=None,
                )

            # --- Parse output ---
            parsed = parse_build_result(self._build_tool, returncode, output)

            # --- Coverage ---
            coverage = None
            if parsed["compiled"]:
                xml_path = find_jacoco_xml(report_dir, self.project_path)
                if xml_path:
                    coverage = parse_jacoco_xml(xml_path, class_name, method_name)
                else:
                    logger.warning(
                        "No JaCoCo XML found in %s; coverage will be unavailable.",
                        report_dir,
                    )

            return TestResult(
                compiled=parsed["compiled"],
                compile_errors=parsed["compile_errors"],
                passed=parsed["passed"],
                test_output=parsed["test_output"],
                coverage=coverage,
                failed_tests=parsed["failed_tests"],
            )
        finally:
            if not self.keep_test and test_file and test_file.is_file():
                test_file.unlink()
                logger.info("Removed test file: %s", test_file)
