"""Test execution module — compile, run, and collect coverage for generated tests."""

from __future__ import annotations

import logging
from pathlib import Path

from testagent.executor.builder import (
    build_gradle_command,
    build_maven_command,
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
    """Compile and run a generated JUnit test against the target Java project.

    Parameters
    ----------
    project_path:
        Root directory of the Java project under test.
    reports_dir:
        Directory where JaCoCo XML reports are stored.  Defaults to
        ``<testagent_root>/tmp/reports``.
    keep_test:
        If ``True``, the generated test file is not deleted after execution.
    build_timeout:
        Maximum seconds to wait for the build process.
    """

    def __init__(
        self,
        project_path: Path,
        reports_dir: Path | None = None,
        keep_test: bool = False,
        build_timeout: int = 300,
    ) -> None:
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
        """Compile and run *test* against the project, then return results.

        Steps:
        1. Write the test file into the project's test source tree.
        2. Run the build tool (Maven/Gradle) to compile, execute, and report.
        3. Parse the build output.
        4. Parse the JaCoCo XML report (if present).
        5. Clean up the test file (unless ``keep_test=True``).

        Parameters
        ----------
        test:
            The generated test to execute.
        context:
            Analysis context for the target method (provides class/method names).
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
            xml_path = find_jacoco_xml(report_dir)
            if xml_path:
                coverage = parse_jacoco_xml(xml_path, class_name)
            else:
                logger.warning(
                    "No JaCoCo XML found in %s; coverage will be unavailable.",
                    report_dir,
                )

        # --- Cleanup ---
        if not self.keep_test and test_file and test_file.is_file():
            test_file.unlink()
            logger.info("Removed test file: %s", test_file)

        return TestResult(
            compiled=parsed["compiled"],
            compile_errors=parsed["compile_errors"],
            passed=parsed["passed"],
            test_output=parsed["test_output"],
            coverage=coverage,
            failed_tests=parsed["failed_tests"],
        )
