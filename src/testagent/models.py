"""Data models for the test agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TargetMethod:
    """The method under test."""

    class_name: str  # e.g., "com.example.MyService"
    method_name: str  # e.g., "processOrder"
    method_signature: str  # Full method source code
    file_path: Path  # Absolute path to the .java file
    class_source: str  # Full source of the containing class


@dataclass
class Dependency:
    """A single dependency extracted by the analyzer."""

    kind: str  # "class", "interface", "enum"
    qualified_name: str  # e.g., "com.example.Order"
    source: str  # Source code of the dependency
    file_path: Path  # Where it was found


@dataclass
class AnalysisContext:
    """Output of the Analyzer module."""

    target: TargetMethod
    dependencies: list[Dependency]
    imports: list[str]  # Import statements from the target file
    package: str  # Package declaration


@dataclass
class GeneratedTest:
    """Output of the Generator module."""

    test_code: str  # Full JUnit test class source
    iteration: int  # Which iteration produced this


@dataclass
class CoverageReport:
    """Coverage data parsed from JaCoCo XML report."""

    line_coverage: float  # 0.0 - 1.0
    branch_coverage: float  # 0.0 - 1.0
    uncovered_lines: list[int] = field(default_factory=list)
    uncovered_branches: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Output of the Executor module."""

    compiled: bool
    compile_errors: str  # Empty if compiled successfully
    passed: bool  # All tests passed?
    test_output: str  # stdout/stderr from test run
    coverage: CoverageReport | None
    failed_tests: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Final output of the pipeline."""

    success: bool  # Tests compiled and passed?
    iterations: int  # How many iterations were run
    final_test: GeneratedTest  # Last generated test
    final_result: TestResult  # Last test execution result
    history: list[tuple[GeneratedTest, TestResult]] = field(default_factory=list)


@dataclass
class Config:
    """Framework configuration."""

    api_base_url: str = "https://yunwu.ai/v1"
    api_key: str = ""  # Defaults to YUNWU_API_KEY env var via config loader
    model: str = "qwen3.5-397b-a17b"
    max_iterations: int = 5
    timeout: int = 120
    keep_test: bool = False
    jacoco_enabled: bool = True
