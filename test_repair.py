"""Repair pipeline: load existing failing tests → execute → iterative refinement.

Reads Java test files from ``failed_test_case/``, extracts the target class and
method from the "大模型生成" banner comment, then runs the full
execute → (refine → execute)* loop until the tests pass or max iterations are
exhausted.

Repaired (passing) tests are saved to ``generated_tests/<project-name>/``
using the same naming convention as ``test_generator.py``:
``<ClassName>_<methodName>_Test.java``.

Usage::

    python test_repair.py                                # repair all files in failed_test_case/
    python test_repair.py --file CalculatorTest_failing.java   # single file
    python test_repair.py --list                         # list repairable files
    python test_repair.py --max-iterations 5             # override iteration limit
    python test_repair.py --keep-test                    # leave test files in project
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from testagent.analyzer import JavaAnalyzer
from testagent.cli_utils import resolve_project_path
from testagent.config import load_config
from testagent.executor import TestExecutor
from testagent.generator.test_generator import TestGenerator
from testagent.models import AnalysisContext, GeneratedTest, TestResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
SAMPLE_PROJECT = PROJECT_ROOT / "under_test" / "sample-java-project"
FAILED_TEST_DIR = PROJECT_ROOT / "failed_test_case"
REPORTS_ROOT = PROJECT_ROOT / "tmp" / "reports"
OUTPUT_ROOT = PROJECT_ROOT / "generated_tests"

# Regex to extract "Target: com.example.Calculator#add" from banner comment.
_BANNER_TARGET_RE = re.compile(r"\*\s+Target:\s+([\w.]+)#(\w+)")
# Regex to extract "Iteration: N" from banner comment.
_BANNER_ITER_RE = re.compile(r"\*\s+Iteration:\s+(\d+)")


# ---------------------------------------------------------------------------
# Banner parsing
# ---------------------------------------------------------------------------

def _parse_banner(test_code: str) -> tuple[str, str, int] | None:
    """从测试文件头部注释中解析目标信息。

    功能简介：
        从自动生成测试文件的 banner 注释中提取目标类名、方法名和迭代次数，
        供修复流程恢复上下文使用。

    输入参数：
        test_code:
            测试文件完整文本。

    返回值：
        tuple[str, str, int] | None:
            成功时返回 `(class_name, method_name, iteration)`；
            若 banner 不存在或信息不完整则返回 `None`。

    使用示例：
        >>> _parse_banner("/*\\n * Target:    com.example.Calculator#add\\n * Iteration: 2\\n */")
        ('com.example.Calculator', 'add', 2)
    """
    target_match = _BANNER_TARGET_RE.search(test_code)
    iter_match = _BANNER_ITER_RE.search(test_code)
    if not target_match:
        return None
    class_name = target_match.group(1)
    method_name = target_match.group(2)
    iteration = int(iter_match.group(1)) if iter_match else 1
    return class_name, method_name, iteration


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _output_path(project_name: str, class_name: str, method_name: str) -> Path:
    """构造修复后测试代码的输出路径。

    功能简介：
        复用与 `test_generator.py` 一致的命名规则，为修复成功后的测试文件生成保存路径。

    输入参数：
        project_name:
            被测项目目录名。
        class_name:
            被测类的全限定类名。
        method_name:
            被测方法名。

    返回值：
        Path:
            修复后测试代码的目标文件路径。

    使用示例：
        >>> _output_path("sample-java-project", "com.example.Calculator", "add")
        Path('generated_tests/sample-java-project/Calculator_add_Test.java')
    """
    simple_class = class_name.rsplit(".", 1)[-1]
    filename = f"{simple_class}_{method_name}_Test.java"
    return OUTPUT_ROOT / project_name / filename


def _save_repaired_test(path: Path, test_code: str) -> None:
    """保存修复后的测试代码。

    功能简介：
        创建目标目录并将修复后的测试代码写入输出文件。

    输入参数：
        path:
            输出文件路径。
        test_code:
            修复后的测试代码文本。

    返回值：
        None:
            该函数仅执行文件写入和终端提示。

    使用示例：
        >>> _save_repaired_test(Path("generated_tests/demo/FooTest.java"), "public class FooTest {}")
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(test_code, encoding="utf-8")
    print(f"  Saved to: {path}")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "=", width: int = 64) -> str:
    """生成分隔线字符串。

    功能简介：
        按指定字符和长度构造用于 CLI 输出的分隔线。

    输入参数：
        char:
            分隔线字符，默认 `=`。
        width:
            分隔线长度，默认 `64`。

    返回值：
        str:
            构造好的分隔线字符串。

    使用示例：
        >>> _sep("-", 4)
        '----'
    """
    return char * width


def _short(class_name: str) -> str:
    """提取类的简单名称。

    功能简介：
        将全限定类名转换为简单类名，便于修复流程中的终端展示。

    输入参数：
        class_name:
            全限定类名。

    返回值：
        str:
            简单类名。

    使用示例：
        >>> _short("com.example.Calculator")
        'Calculator'
    """
    return class_name.rsplit(".", 1)[-1]


def _print_initial_test(test: GeneratedTest, source_file: Path) -> None:
    """打印待修复测试的初始摘要。

    功能简介：
        输出失败测试文件名、代码行数和起始迭代次数，帮助用户确认修复输入。

    输入参数：
        test:
            当前待修复的测试对象。
        source_file:
            原始失败测试文件路径。

    返回值：
        None:
            该函数仅负责终端输出。

    使用示例：
        >>> _print_initial_test(test, Path("failed_test_case/FooTest.java"))
    """
    lines = test.test_code.splitlines()
    print(f"\n  Source file:  {source_file.name}")
    print(f"  Code lines:   {len(lines)}")
    print(f"  Start iteration: {test.iteration}")


def _print_test_result(result: TestResult, iteration: int) -> None:
    """打印修复流程中的单轮执行结果。

    功能简介：
        将编译错误、失败测试、覆盖率和输出摘要等信息格式化展示到终端，
        用于跟踪每轮修复效果。

    输入参数：
        result:
            当前轮次的执行结果。
        iteration:
            当前轮次编号。

    返回值：
        None:
            该函数仅负责终端输出。

    使用示例：
        >>> _print_test_result(result, 2)
    """
    if not result.compiled:
        status = "COMPILE ERROR"
    elif result.passed:
        status = "PASS"
    else:
        status = "FAIL"
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
    """打印修复后测试代码预览。

    功能简介：
        将修复后的测试代码前若干行输出到终端，便于快速检查 LLM 生成结果。

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
    print(f"\n  --- Refined test ({len(lines)} lines total) ---")
    for line in shown:
        print(f"  | {line}")
    if len(lines) > max_lines:
        print(f"  | ... ({len(lines) - max_lines} more lines)")


def _coverage_met(result: TestResult, min_branch_coverage: float) -> bool:
    """判断分支覆盖率是否达标。

    功能简介：
        检查当前测试结果中的分支覆盖率是否达到目标阈值；
        若没有覆盖率数据，则默认不阻塞修复流程。

    输入参数：
        result:
            当前测试执行结果。
        min_branch_coverage:
            目标最小分支覆盖率。

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
# Core repair loop
# ---------------------------------------------------------------------------

def repair_one(
    source_file: Path,
    project_name: str,
    analyzer: JavaAnalyzer,
    generator: TestGenerator,
    executor: TestExecutor,
    max_iterations: int,
    min_branch_coverage: float,
) -> bool:
    """修复单个失败测试文件。

    功能简介：
        从失败测试文件中恢复目标上下文，执行测试并根据反馈反复调用 LLM 修复，
        直到测试通过且覆盖率达标，或达到最大迭代次数。

    输入参数：
        source_file:
            待修复的失败测试文件路径。
        project_name:
            被测项目名称，用于构造输出目录。
        analyzer:
            Java 源码分析器。
        generator:
            测试修复生成器。
        executor:
            测试执行器。
        max_iterations:
            最大修复迭代次数。
        min_branch_coverage:
            最小分支覆盖率阈值。

    返回值：
        bool:
            最终修复成功时返回 `True`，否则返回 `False`。

    使用示例：
        >>> ok = repair_one(Path("failed_test_case/FooTest.java"), "sample-java-project", analyzer, generator, executor, 5, 0.8)
    """
    test_code = source_file.read_text(encoding="utf-8")

    # --- Parse banner ---
    parsed = _parse_banner(test_code)
    if parsed is None:
        print(f"\n  [SKIP] Cannot parse target from banner in {source_file.name}")
        print("         Expected: '* Target: com.example.ClassName#methodName'")
        return False

    class_name, method_name, start_iteration = parsed
    label = f"{_short(class_name)}.{method_name}"

    print(f"\n{_sep()}")
    print(f"  Repairing: {label}  ({class_name})")
    print(f"  File:      {source_file.name}")
    print(_sep())

    # --- Analyze source to obtain AnalysisContext ---
    print("\n[1/2] Analyzing source...")
    try:
        ctx: AnalysisContext = analyzer.analyze(class_name, method_name)
    except (FileNotFoundError, ValueError) as exc:
        print(f"  Analysis FAILED: {exc}")
        return False

    print(f"  Class:        {ctx.target.class_name}")
    print(f"  Method:       {ctx.target.method_name}")
    print(f"  Dependencies: {len(ctx.dependencies)}")

    # --- Wrap existing code as the first GeneratedTest ---
    test = GeneratedTest(test_code=test_code, iteration=start_iteration)
    _print_initial_test(test, source_file)

    # --- Execute + iterative refinement ---
    print("\n[2/2] Executing and refining...")
    result: TestResult | None = None
    iteration = start_iteration

    for _ in range(max_iterations):
        print(f"\n  {'─' * 56}")
        print(f"  Executing iteration {iteration}...")
        t0 = time.time()
        result = executor.execute(test, ctx)
        print(f"  Execution finished in {time.time() - t0:.1f}s")
        _print_test_result(result, iteration)

        if result.passed and _coverage_met(result, min_branch_coverage):
            print(f"\n  [SUCCESS] Tests passed on iteration {iteration}.")
            out_path = _output_path(project_name, class_name, method_name)
            _save_repaired_test(out_path, test.test_code)
            break

        if result.passed:
            cov = result.coverage
            print(
                f"\n  Tests passed but branch coverage "
                f"{cov.branch_coverage * 100:.1f}% < "
                f"{min_branch_coverage * 100:.1f}%, refining for coverage..."
            )

        if iteration - start_iteration + 1 < max_iterations:
            print(f"\n  Refining test (iteration {iteration} → {iteration + 1})...")
            t0 = time.time()
            try:
                test = generator.refine(ctx, test, result)
            except Exception as exc:
                print(f"  Refinement FAILED: {exc}")
                break
            print(f"  LLM responded in {time.time() - t0:.1f}s")
            _print_code_preview(test.test_code)
            iteration = test.iteration
        else:
            print(f"\n  [GIVE UP] Reached max iterations ({max_iterations}).")
            if result.passed:
                out_path = _output_path(project_name, class_name, method_name)
                _save_repaired_test(out_path, test.test_code)
            break

    return result is not None and result.passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _discover_test_files(directory: Path) -> list[Path]:
    """发现失败测试目录中的 Java 文件。

    功能简介：
        枚举指定目录下所有 `.java` 文件，并按文件名排序返回。

    输入参数：
        directory:
            待扫描目录。

    返回值：
        list[Path]:
            目录下的 Java 文件路径列表。

    使用示例：
        >>> _discover_test_files(Path("failed_test_case"))
    """
    return sorted(directory.glob("*.java"))


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    功能简介：
        定义并解析 `test_repair.py` 支持的 CLI 参数，包括失败测试目录、
        目标文件、模型覆盖项和覆盖率阈值等。

    输入参数：
        无。

    返回值：
        argparse.Namespace:
            已解析的参数对象。

    使用示例：
        >>> args = parse_args()
        >>> args.file
    """
    p = argparse.ArgumentParser(
        description="Repair failing test cases via execute → refine loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--file",
        help="Single file name inside failed_test_case/ (e.g. CalculatorTest_failing.java)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List repairable files and exit",
    )
    p.add_argument(
        "--failed-dir",
        type=Path,
        default=FAILED_TEST_DIR,
        help=f"Directory containing failing test files (default: {FAILED_TEST_DIR})",
    )
    p.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Java project path (overrides config/default)",
    )
    p.add_argument(
        "--model",
        help="Override LLM model name",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Max repair iterations per file (default: from config)",
    )
    p.add_argument(
        "--keep-test",
        action="store_true",
        default=None,
        help="Keep the (repaired) test file in the project after execution",
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
    return p.parse_args()


def main() -> None:
    """脚本主入口。

    功能简介：
        负责发现失败测试文件、读取配置、初始化分析器/生成器/执行器，
        并依次执行“现有测试 -> 执行 -> 修复 -> 再执行”的修复流水线。

    输入参数：
        无。

    返回值：
        None:
            主要通过终端输出反馈结果；失败时可能调用 `sys.exit()`。

    使用示例：
        >>> main()
    """
    args = parse_args()
    failed_dir: Path = args.failed_dir

    # --- Discover files ---
    all_files = _discover_test_files(failed_dir)

    if args.list:
        if not all_files:
            print(f"No .java files found in {failed_dir}")
        else:
            print(f"Repairable files in {failed_dir}:")
            for f in all_files:
                parsed = _parse_banner(f.read_text(encoding="utf-8"))
                if parsed:
                    cls, method, iteration = parsed
                    print(f"  {f.name:<45}  → {_short(cls)}.{method}  (iter {iteration})")
                else:
                    print(f"  {f.name:<45}  → [no banner — will be skipped]")
        return

    # --- Resolve target file(s) ---
    if args.file:
        target_path = failed_dir / args.file
        if not target_path.is_file():
            print(f"Error: '{target_path}' not found.")
            sys.exit(1)
        files = [target_path]
    else:
        files = all_files
        if not files:
            print(f"No .java files found in {failed_dir}")
            sys.exit(1)

    # --- Config ---
    overrides = {k: v for k, v in {
        "model": args.model,
        "project_path": str(args.project) if args.project is not None else None,
        "max_iterations": args.max_iterations,
        "keep_test": args.keep_test,
        "min_branch_coverage": args.min_branch_coverage,
    }.items() if v is not None}
    config = load_config(**overrides)

    if not config.api_key:
        print("Error: No API key configured.")
        print("  Set YUNWU_API_KEY environment variable, or set llm.api_key in configs/default.yaml")
        sys.exit(1)

    project_path = resolve_project_path(args.project, config.project_path, SAMPLE_PROJECT)
    project_name = project_path.name

    print(_sep())
    print("  Pipeline: (existing test) → Executor → Refine → Executor → ...")
    print(_sep())
    print(f"  Failed test dir: {failed_dir}")
    print(f"  Project:         {project_path}")
    print(f"  Output dir:      {OUTPUT_ROOT / project_name}")
    print(f"  API:             {config.api_base_url}")
    print(f"  Model:           {config.model}")
    print(f"  Max iter:        {config.max_iterations}")
    print(f"  Keep test:       {config.keep_test}")
    print(f"  Min branch cov:  {config.min_branch_coverage * 100:.0f}%")
    print(f"  Reports dir:     {args.reports_dir}")
    print(f"  Files:           {len(files)}")

    # --- Build modules ---
    analyzer = JavaAnalyzer(project_path)
    generator = TestGenerator(
        api_base_url=config.api_base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
    )
    executor = TestExecutor(
        project_path=project_path,
        reports_dir=args.reports_dir,
        keep_test=config.keep_test,
    )

    # --- Run ---
    results: list[tuple[str, bool]] = []
    for f in files:
        ok = repair_one(
            f,
            project_name,
            analyzer,
            generator,
            executor,
            max_iterations=config.max_iterations,
            min_branch_coverage=config.min_branch_coverage,
        )
        results.append((f.name, ok))

    # --- Summary ---
    print(f"\n{_sep()}")
    print("  Summary")
    print(_sep())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    for name, ok in results:
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {name}")
    print(f"\n  {passed} succeeded, {failed} failed out of {len(results)} files")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
