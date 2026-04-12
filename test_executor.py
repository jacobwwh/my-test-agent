"""End-to-end pipeline: Analyzer → Generator → Executor (with iterative refinement).

Runs the full test-generation-and-execution loop against a Java project.
By default it targets ``under_test/sample-java-project``, but the project root
can be overridden via config or CLI.

Usage::

    python test_executor.py                           # run all default targets
    python test_executor.py --target Calculator.add   # single target
    python test_executor.py --class com.example.Calculator --method add
    python test_executor.py --list                    # list available targets
    python test_executor.py --max-iterations 3        # override iteration limit
    python test_executor.py --keep-test               # leave test files in project
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from testagent.analyzer import create_analyzer
from testagent.cli_utils import resolve_project_path, resolve_targets
from testagent.config import load_config
from testagent.executor import create_executor
from testagent.generator.test_generator import TestGenerator
from testagent.models import AnalysisContext, GeneratedTest, TestResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
SAMPLE_PROJECT = PROJECT_ROOT / "under_test" / "sample-java-project"
REPORTS_ROOT = PROJECT_ROOT / "tmp" / "reports"

DEFAULT_TARGETS = [
    ("com.example.Calculator", "add"),
    ("com.example.Calculator", "divide"),
    ("com.example.service.OrderService", "process"),
    ("com.example.service.OrderService", "findOrder"),  #line coverage 100%, branch coverage 0%?
    ("com.example.service.OrderService", "calculateTotal"),
]

PRESET_TARGETS = DEFAULT_TARGETS


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "=", width: int = 64) -> str:
    """生成分隔线字符串。

    功能简介：
        按指定字符和宽度构造一条终端输出分隔线，用于增强 CLI 展示可读性。

    输入参数：
        char:
            构成分隔线的字符，默认为 `=`。
        width:
            分隔线长度，默认为 `64`。

    返回值：
        str:
            生成好的分隔线字符串。

    使用示例：
        >>> _sep("-", 5)
        '-----'
    """
    return char * width


def _short(class_name: str) -> str:
    """提取类的简单名称。

    功能简介：
        将全限定类名转换为简单类名，便于终端输出和标签展示。

    输入参数：
        class_name:
            全限定类名，例如 `com.example.Calculator`。

    返回值：
        str:
            简单类名，例如 `Calculator`。

    使用示例：
        >>> _short("com.example.Calculator")
        'Calculator'
    """
    return class_name.rsplit(".", 1)[-1]


def _print_context(ctx: AnalysisContext) -> None:
    """打印分析上下文信息。

    功能简介：
        将分析器返回的目标类、方法、包名和依赖信息输出到终端，
        便于用户核对当前执行目标。

    输入参数：
        ctx:
            分析上下文对象。

    返回值：
        None:
            该函数仅负责终端输出。

    使用示例：
        >>> _print_context(ctx)
    """
    t = ctx.target
    print(f"  Class:        {t.class_name}")
    print(f"  Method:       {t.method_name}")
    print(f"  Package:      {ctx.package}")
    print(f"  Imports:      {len(ctx.imports)}")
    print(f"  Dependencies: {len(ctx.dependencies)}")
    for dep in ctx.dependencies:
        print(f"    [{dep.kind}] {dep.qualified_name}")


def _print_test_result(result: TestResult, iteration: int) -> None:
    """打印单轮测试执行结果。

    功能简介：
        将编译状态、失败测试、覆盖率和错误摘要等关键信息格式化输出到终端。

    输入参数：
        result:
            当前轮次的测试执行结果。
        iteration:
            当前执行轮次编号。

    返回值：
        None:
            该函数仅负责终端输出。

    使用示例：
        >>> _print_test_result(result, 1)
    """
    status = "PASS" if result.passed else ("COMPILE ERROR" if not result.compiled else "FAIL")
    print(f"\n  Iteration {iteration} result: [{status}]")

    if not result.compiled:
        lines = result.compile_errors.strip().splitlines()
        print(f"  Compile errors ({len(lines)} lines):")
        for line in lines[:8]:
            print(f"    {line}")
        if len(lines) > 8:
            print(f"    ... ({len(lines) - 8} more lines)")
    elif not result.passed:
        print(f"  Failed tests: {result.failed_tests}")
        output_lines = result.test_output.strip().splitlines()
        # Show the last 15 lines of test output (most informative part)
        tail = output_lines[-15:] if len(output_lines) > 15 else output_lines
        print(f"  Build output (last {len(tail)} lines):")
        for line in tail:
            print(f"    {line}")
    else:
        print("  All tests passed.")

    if result.coverage:
        cov = result.coverage
        print(
            f"  Coverage: line={cov.line_coverage * 100:.1f}%  "
            f"branch={cov.branch_coverage * 100:.1f}%"
        )
        if cov.uncovered_lines:
            print(f"  Uncovered lines: {cov.uncovered_lines}")
        if cov.uncovered_branches:
            for b in cov.uncovered_branches[:3]:
                print(f"  Uncovered branch: {b}")
            if len(cov.uncovered_branches) > 3:
                print(f"  ... ({len(cov.uncovered_branches) - 3} more)")
    else:
        print("  Coverage: not available")


def _print_code_preview(code: str, max_lines: int = 20) -> None:
    """打印测试代码预览。

    功能简介：
        将测试代码的前若干行输出到终端，帮助用户快速查看 LLM 当前生成结果。

    输入参数：
        code:
            测试代码文本。
        max_lines:
            最多展示的行数，默认 `20`。

    返回值：
        None:
            该函数仅负责终端输出。

    使用示例：
        >>> _print_code_preview("line1\\nline2", max_lines=1)
    """
    lines = code.splitlines()
    shown = lines[:max_lines]
    print(f"\n  --- Generated test ({len(lines)} lines total) ---")
    for line in shown:
        print(f"  | {line}")
    if len(lines) > max_lines:
        print(f"  | ... ({len(lines) - max_lines} more lines)")


# ---------------------------------------------------------------------------
# Coverage threshold
# ---------------------------------------------------------------------------

def _coverage_met(result: TestResult, min_branch_coverage: float) -> bool:
    """判断分支覆盖率是否达标。

    功能简介：
        检查测试结果中的分支覆盖率是否达到目标阈值；
        若没有覆盖率数据，则默认视为不阻塞后续流程。

    输入参数：
        result:
            测试执行结果对象。
        min_branch_coverage:
            目标最小分支覆盖率，范围通常在 `0.0` 到 `1.0` 之间。

    返回值：
        bool:
            达标时返回 `True`，否则返回 `False`；无覆盖率数据时返回 `True`。

    使用示例：
        >>> _coverage_met(result, 0.8)
        True
    """
    if result.coverage is None:
        return True
    return result.coverage.branch_coverage >= min_branch_coverage


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def run_one(
    class_name: str,
    method_name: str,
    analyzer,
    generator: TestGenerator,
    executor,
    max_iterations: int,
    min_branch_coverage: float,
) -> bool:
    """对单个目标执行完整流水线。

    功能简介：
        针对一个类方法依次执行分析、测试生成、测试执行和迭代优化，
        直到测试通过且覆盖率达标，或达到最大迭代次数。

    输入参数：
        class_name:
            被测类的全限定类名。
        method_name:
            被测方法名。
        analyzer:
            Java 源码分析器。
        generator:
            测试生成与修复器。
        executor:
            测试执行器。
        max_iterations:
            最大迭代次数。
        min_branch_coverage:
            最小分支覆盖率阈值。

    返回值：
        bool:
            最终测试通过时返回 `True`，否则返回 `False`。

    使用示例：
        >>> ok = run_one("com.example.Calculator", "add", analyzer, generator, executor, 3, 0.8)
    """
    label = f"{_short(class_name)}.{method_name}"
    print(f"\n{_sep()}")
    print(f"  Target: {label}  ({class_name})")
    print(_sep())

    # ── Step 1: Analyze ──────────────────────────────────────────────
    print("\n[1/3] Analyzing source...")
    try:
        ctx = analyzer.analyze(class_name, method_name)
    except (FileNotFoundError, ValueError) as exc:
        print(f"  Analysis FAILED: {exc}")
        return False
    _print_context(ctx)

    # ── Step 2: Generate initial test ────────────────────────────────
    print("\n[2/3] Generating initial test via LLM...")
    t0 = time.time()
    try:
        test = generator.generate(ctx)
    except Exception as exc:
        print(f"  Generation FAILED: {exc}")
        return False
    print(f"  LLM responded in {time.time() - t0:.1f}s")
    _print_code_preview(test.test_code)

    # ── Step 3: Execute + iterative refinement ───────────────────────
    print("\n[3/3] Executing and refining...")
    result: TestResult | None = None

    for iteration in range(1, max_iterations + 1):
        print(f"\n  {'─' * 56}")
        print(f"  Executing iteration {iteration}/{max_iterations}...")
        t0 = time.time()
        result = executor.execute(test, ctx)
        print(f"  Execution finished in {time.time() - t0:.1f}s")
        _print_test_result(result, iteration)

        if result.passed and _coverage_met(result, min_branch_coverage):
            print(f"\n  [SUCCESS] Tests passed on iteration {iteration}.")
            break

        if result.passed:
            cov = result.coverage
            print(
                f"\n  Tests passed but branch coverage "
                f"{cov.branch_coverage * 100:.1f}% < "
                f"{min_branch_coverage * 100:.1f}%, refining for coverage..."
            )

        if iteration < max_iterations:
            print(f"\n  Refining test (iteration {iteration} → {iteration + 1})...")
            t0 = time.time()
            try:
                test = generator.refine(ctx, test, result)
            except Exception as exc:
                print(f"  Refinement FAILED: {exc}")
                break
            print(f"  LLM responded in {time.time() - t0:.1f}s")
            _print_code_preview(test.test_code)
        else:
            print(f"\n  [GIVE UP] Reached max iterations ({max_iterations}).")

    return result is not None and result.passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    功能简介：
        定义并解析完整流水线脚本支持的 CLI 参数，包括目标方法、项目路径、
        最大迭代次数和覆盖率阈值等。

    输入参数：
        无。

    返回值：
        argparse.Namespace:
            已解析的参数对象。

    使用示例：
        >>> args = parse_args()
        >>> args.max_iterations
    """
    p = argparse.ArgumentParser(
        description="Full generate → execute → refine pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--target",
        help="Single target as 'ClassName.methodName' (e.g. Calculator.add)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List available targets and exit",
    )
    p.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Java project path (overrides config/default)",
    )
    p.add_argument(
        "--class",
        dest="class_name",
        help="Fully-qualified class name for an arbitrary target (e.g. com.example.Calculator)",
    )
    p.add_argument(
        "--method",
        dest="method_name",
        help="Method name to analyze together with --class",
    )
    p.add_argument(
        "--model",
        help="Override LLM model name",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Max refinement iterations (default: from config)",
    )
    p.add_argument(
        "--keep-test",
        action="store_true",
        default=None,
        help="Keep the generated test file in the project after execution",
    )
    p.add_argument(
        "--reports-dir",
        type=Path,
        default=REPORTS_ROOT,
        help=f"Directory for JaCoCo reports (default: {REPORTS_ROOT})",
    )
    p.add_argument(
        "--min-branch-coverage",
        type=float,
        default=None,
        help="Minimum branch coverage (0.0–1.0) to stop iterating (default: from config)",
    )
    p.add_argument(
        "--language",
        default=None,
        help="Target language (default: java)",
    )
    return p.parse_args()


def main() -> None:
    """脚本主入口。

    功能简介：
        负责读取配置、解析目标、初始化分析器/生成器/执行器，
        并逐个执行 Analyzer -> Generator -> Executor 的完整流程。

    输入参数：
        无。

    返回值：
        None:
            主要通过终端输出反馈执行状态；失败时可能调用 `sys.exit()`。

    使用示例：
        >>> main()
    """
    args = parse_args()

    # ── List mode ───────────────────────────────────────────────────
    if args.list:
        print("Preset targets:")
        for cls, method in PRESET_TARGETS:
            print(f"  {_short(cls)}.{method:<20}  ({cls})")
        print("\nFor arbitrary projects, use --class <fully.qualified.Class> --method <methodName>.")
        return

    # ── Config ──────────────────────────────────────────────────────
    overrides = {k: v for k, v in {
        "model": args.model,
        "project_path": str(args.project) if args.project is not None else None,
        "max_iterations": args.max_iterations,
        "keep_test": args.keep_test,
        "min_branch_coverage": args.min_branch_coverage,
        "language": args.language,
    }.items() if v is not None}
    config = load_config(**overrides)
    project_path = resolve_project_path(args.project, config.project_path, SAMPLE_PROJECT)

    # ── Resolve targets ─────────────────────────────────────────────
    try:
        targets = resolve_targets(
            target=args.target,
            class_name=args.class_name,
            method_name=args.method_name,
            default_targets=PRESET_TARGETS,
            short_name=_short,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    if not config.api_key:
        print("Error: No API key configured.")
        print("  Set YUNWU_API_KEY environment variable, or set llm.api_key in configs/default.yaml")
        sys.exit(1)

    print(_sep())
    print("  Pipeline: Analyzer → Generator → Executor")
    print(_sep())
    print(f"  Project:       {project_path}")
    print(f"  Language:      {config.language}")
    print(f"  API:           {config.api_base_url}")
    print(f"  Model:         {config.model}")
    print(f"  Max iter:      {config.max_iterations}")
    print(f"  Keep test:     {config.keep_test}")
    print(f"  Min branch cov: {config.min_branch_coverage * 100:.0f}%")
    print(f"  Reports dir:   {args.reports_dir}")
    print(f"  Targets:       {len(targets)}")

    # ── Build modules ───────────────────────────────────────────────
    analyzer = create_analyzer(config.language, project_path)
    generator = TestGenerator(
        api_base_url=config.api_base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
        language=config.language,
    )
    executor = create_executor(
        config.language,
        project_path,
        reports_dir=args.reports_dir,
        keep_test=config.keep_test,
    )

    # ── Run ─────────────────────────────────────────────────────────
    results: list[tuple[str, bool]] = []
    for class_name, method_name in targets:
        label = f"{_short(class_name)}.{method_name}"
        ok = run_one(
            class_name, method_name,
            analyzer, generator, executor,
            max_iterations=config.max_iterations,
            min_branch_coverage=config.min_branch_coverage,
        )
        results.append((label, ok))

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{_sep()}")
    print("  Summary")
    print(_sep())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    for label, ok in results:
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {label}")
    print(f"\n  {passed} succeeded, {failed} failed out of {len(results)} targets")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
