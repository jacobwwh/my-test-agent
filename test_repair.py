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
    """Extract (class_name, method_name, iteration) from the banner comment.

    Returns None if the banner is absent or incomplete.
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
    """Build the output file path for a repaired test, mirroring test_generator.py."""
    simple_class = class_name.rsplit(".", 1)[-1]
    filename = f"{simple_class}_{method_name}_Test.java"
    return OUTPUT_ROOT / project_name / filename


def _save_repaired_test(path: Path, test_code: str) -> None:
    """Write the repaired test code to the output directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(test_code, encoding="utf-8")
    print(f"  Saved to: {path}")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "=", width: int = 64) -> str:
    return char * width


def _short(class_name: str) -> str:
    return class_name.rsplit(".", 1)[-1]


def _print_initial_test(test: GeneratedTest, source_file: Path) -> None:
    lines = test.test_code.splitlines()
    print(f"\n  Source file:  {source_file.name}")
    print(f"  Code lines:   {len(lines)}")
    print(f"  Start iteration: {test.iteration}")


def _print_test_result(result: TestResult, iteration: int) -> None:
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
    lines = code.splitlines()
    shown = lines[:max_lines]
    print(f"\n  --- Refined test ({len(lines)} lines total) ---")
    for line in shown:
        print(f"  | {line}")
    if len(lines) > max_lines:
        print(f"  | ... ({len(lines) - max_lines} more lines)")


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
) -> bool:
    """Repair a single failing test file.

    Reads the file, resolves the analysis context from the banner metadata,
    then runs execute → refine until passing or exhausted.
    On success, saves the final test code to ``generated_tests/<project_name>/``.

    Returns True if all tests pass at the end.
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

        if result.passed:
            print(f"\n  [SUCCESS] Tests passed on iteration {iteration}.")
            out_path = _output_path(project_name, class_name, method_name)
            _save_repaired_test(out_path, test.test_code)
            break

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
            print(f"\n  [GIVE UP] Reached max iterations ({max_iterations}) without passing.")
            break

    return result is not None and result.passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _discover_test_files(directory: Path) -> list[Path]:
    """Return all .java files under *directory*, sorted by name."""
    return sorted(directory.glob("*.java"))


def parse_args() -> argparse.Namespace:
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
        default=SAMPLE_PROJECT,
        help=f"Java project path (default: {SAMPLE_PROJECT})",
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
    return p.parse_args()


def main() -> None:
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
        "max_iterations": args.max_iterations,
        "keep_test": args.keep_test,
    }.items() if v is not None}
    config = load_config(**overrides)

    if not config.api_key:
        print("Error: No API key configured.")
        print("  Set YUNWU_API_KEY environment variable, or set llm.api_key in configs/default.yaml")
        sys.exit(1)

    project_name = args.project.name

    print(_sep())
    print("  Pipeline: (existing test) → Executor → Refine → Executor → ...")
    print(_sep())
    print(f"  Failed test dir: {failed_dir}")
    print(f"  Project:         {args.project}")
    print(f"  Output dir:      {OUTPUT_ROOT / project_name}")
    print(f"  API:             {config.api_base_url}")
    print(f"  Model:           {config.model}")
    print(f"  Max iter:        {config.max_iterations}")
    print(f"  Keep test:       {config.keep_test}")
    print(f"  Reports dir:     {args.reports_dir}")
    print(f"  Files:           {len(files)}")

    # --- Build modules ---
    analyzer = JavaAnalyzer(args.project)
    generator = TestGenerator(
        api_base_url=config.api_base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
    )
    executor = TestExecutor(
        project_path=args.project,
        reports_dir=args.reports_dir,
        keep_test=config.keep_test,
    )

    # --- Run ---
    results: list[tuple[str, bool]] = []
    for f in files:
        ok = repair_one(f, project_name, analyzer, generator, executor, max_iterations=config.max_iterations)
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
