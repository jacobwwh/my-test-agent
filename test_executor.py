"""End-to-end pipeline: Analyzer → Generator → Executor (with iterative refinement).

Runs the full test-generation-and-execution loop against the sample Java project
under ``under_test/sample-java-project``.

Usage::

    python test_executor.py                           # run all default targets
    python test_executor.py --target Calculator.add   # single target
    python test_executor.py --list                    # list available targets
    python test_executor.py --max-iterations 3        # override iteration limit
    python test_executor.py --keep-test               # leave test files in project
"""

from __future__ import annotations

import argparse
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
REPORTS_ROOT = PROJECT_ROOT / "tmp" / "reports"

DEFAULT_TARGETS = [
    ("com.example.Calculator", "add"),
    ("com.example.Calculator", "divide"),
    ("com.example.service.OrderService", "process"),
    ("com.example.service.OrderService", "findOrder"),
    ("com.example.service.OrderService", "calculateTotal"),
]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "=", width: int = 64) -> str:
    return char * width


def _short(class_name: str) -> str:
    return class_name.rsplit(".", 1)[-1]


def _print_context(ctx: AnalysisContext) -> None:
    t = ctx.target
    print(f"  Class:        {t.class_name}")
    print(f"  Method:       {t.method_name}")
    print(f"  Package:      {ctx.package}")
    print(f"  Imports:      {len(ctx.imports)}")
    print(f"  Dependencies: {len(ctx.dependencies)}")
    for dep in ctx.dependencies:
        print(f"    [{dep.kind}] {dep.qualified_name}")


def _print_test_result(result: TestResult, iteration: int) -> None:
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
    lines = code.splitlines()
    shown = lines[:max_lines]
    print(f"\n  --- Generated test ({len(lines)} lines total) ---")
    for line in shown:
        print(f"  | {line}")
    if len(lines) > max_lines:
        print(f"  | ... ({len(lines) - max_lines} more lines)")


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def run_one(
    class_name: str,
    method_name: str,
    analyzer: JavaAnalyzer,
    generator: TestGenerator,
    executor: TestExecutor,
    max_iterations: int,
) -> bool:
    """Run the full generate → execute → refine loop for one target.

    Returns True if the final result compiled and all tests passed.
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

        if result.passed:
            print(f"\n  [SUCCESS] Tests passed on iteration {iteration}.")
            break

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
            print(f"\n  [GIVE UP] Reached max iterations ({max_iterations}) without passing.")

    return result is not None and result.passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
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
    return p.parse_args()


def main() -> None:
    args = parse_args()
    project_path: Path = args.project

    # ── List mode ───────────────────────────────────────────────────
    if args.list:
        print("Available targets:")
        for cls, method in DEFAULT_TARGETS:
            print(f"  {_short(cls)}.{method:<20}  ({cls})")
        return

    # ── Resolve targets ─────────────────────────────────────────────
    if args.target:
        simple_cls, _, method = args.target.partition(".")
        if not method:
            print(f"Error: target must be 'ClassName.methodName', got '{args.target}'")
            sys.exit(1)
        targets = [
            (c, m) for c, m in DEFAULT_TARGETS
            if _short(c) == simple_cls and m == method
        ]
        if not targets:
            print(f"Error: '{args.target}' not found. Use --list to see options.")
            sys.exit(1)
    else:
        targets = DEFAULT_TARGETS

    # ── Config ──────────────────────────────────────────────────────
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

    print(_sep())
    print("  Pipeline: Analyzer → Generator → Executor")
    print(_sep())
    print(f"  Project:       {project_path}")
    print(f"  API:           {config.api_base_url}")
    print(f"  Model:         {config.model}")
    print(f"  Max iter:      {config.max_iterations}")
    print(f"  Keep test:     {config.keep_test}")
    print(f"  Reports dir:   {args.reports_dir}")
    print(f"  Targets:       {len(targets)}")

    # ── Build modules ───────────────────────────────────────────────
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

    # ── Run ─────────────────────────────────────────────────────────
    results: list[tuple[str, bool]] = []
    for class_name, method_name in targets:
        label = f"{_short(class_name)}.{method_name}"
        ok = run_one(
            class_name, method_name,
            analyzer, generator, executor,
            max_iterations=config.max_iterations,
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
