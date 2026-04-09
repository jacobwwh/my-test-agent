"""End-to-end integration test: Analyzer -> Generator.

Runs the full analysis + test-generation pipeline against the sample Java
project under ``under_test/sample-java-project`` and writes the generated
tests to ``generated_tests/<project-name>/``.

Usage::

    python test_generator.py                         # run all targets
    python test_generator.py --target Calculator.add  # single target
    python test_generator.py --list                   # list available targets
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from testagent.analyzer import JavaAnalyzer
from testagent.config import load_config
from testagent.generator.test_generator import TestGenerator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
SAMPLE_PROJECT = PROJECT_ROOT / "under_test" / "sample-java-project"
OUTPUT_ROOT = PROJECT_ROOT / "generated_tests"

# Method targets to test: (class_name, method_name)
DEFAULT_TARGETS = [
    ("com.example.Calculator", "add"),
    ("com.example.Calculator", "divide"),
    ("com.example.service.OrderService", "process"),
    ("com.example.service.OrderService", "findOrder"),
    ("com.example.service.OrderService", "calculateTotal"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_name(class_name: str) -> str:
    """'com.example.service.OrderService' -> 'OrderService'."""
    return class_name.rsplit(".", 1)[-1]


def _output_path(project_name: str, class_name: str, method_name: str) -> Path:
    """Build the output file path for a generated test."""
    simple_class = _short_name(class_name)
    filename = f"{simple_class}_{method_name}_Test.java"
    return OUTPUT_ROOT / project_name / filename


def _print_context_summary(ctx) -> None:
    """Print a brief summary of the analysis context."""
    t = ctx.target
    print(f"  Class:        {t.class_name}")
    print(f"  Method:       {t.method_name}")
    print(f"  File:         {t.file_path}")
    print(f"  Package:      {ctx.package}")
    print(f"  Imports:      {len(ctx.imports)}")
    print(f"  Dependencies: {len(ctx.dependencies)}")
    for dep in ctx.dependencies:
        print(f"    - [{dep.kind}] {dep.qualified_name}  ({dep.file_path.name})")


def _save_test(path: Path, test_code: str) -> None:
    """Write generated test code to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(test_code, encoding="utf-8")
    print(f"  Saved to: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_one(
    analyzer: JavaAnalyzer,
    generator: TestGenerator,
    project_name: str,
    class_name: str,
    method_name: str,
) -> bool:
    """Analyze + generate for a single target.  Returns True on success."""
    label = f"{_short_name(class_name)}.{method_name}"
    print(f"\n{'='*60}")
    print(f"Target: {label}")
    print(f"{'='*60}")

    # --- Step 1: Analyze ---
    print("\n[1/2] Analyzing...")
    try:
        ctx = analyzer.analyze(class_name, method_name)
    except (FileNotFoundError, ValueError) as exc:
        print(f"  Analysis FAILED: {exc}")
        return False

    _print_context_summary(ctx)

    # --- Step 2: Generate ---
    print("\n[2/2] Generating test via LLM...")
    t0 = time.time()
    try:
        result = generator.generate(ctx)
    except Exception as exc:
        print(f"  Generation FAILED: {exc}")
        return False
    elapsed = time.time() - t0

    print(f"  LLM responded in {elapsed:.1f}s")
    print(f"  Generated code length: {len(result.test_code)} chars")

    # --- Save ---
    out_path = _output_path(project_name, class_name, method_name)
    _save_test(out_path, result.test_code)

    # --- Preview ---
    preview_lines = result.test_code.splitlines()[:20]
    print(f"\n  --- Preview (first 20 lines) ---")
    for line in preview_lines:
        print(f"  | {line}")
    if len(result.test_code.splitlines()) > 20:
        print(f"  | ... ({len(result.test_code.splitlines()) - 20} more lines)")

    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyzer + Generator integration test")
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
        help="Path to the Java project under test",
    )
    p.add_argument("--model", help="Override LLM model name")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    project_path: Path = args.project
    project_name = project_path.name

    # --- List mode ---
    if args.list:
        print("Available targets:")
        for cls, method in DEFAULT_TARGETS:
            print(f"  {_short_name(cls)}.{method}  ({cls})")
        return

    # --- Resolve targets ---
    if args.target:
        # Match "Calculator.add" or "OrderService.process"
        simple_cls, _, method = args.target.partition(".")
        if not method:
            print(f"Error: target must be 'ClassName.methodName', got '{args.target}'")
            sys.exit(1)
        matched = [
            (c, m)
            for c, m in DEFAULT_TARGETS
            if _short_name(c) == simple_cls and m == method
        ]
        if not matched:
            print(f"Error: target '{args.target}' not found. Use --list to see options.")
            sys.exit(1)
        targets = matched
    else:
        targets = DEFAULT_TARGETS

    # --- Config ---
    overrides = {}
    if args.model:
        overrides["model"] = args.model
    config = load_config(**overrides)

    if not config.api_key:
        print("Error: No API key configured.")
        print("Set the YUNWU_API_KEY environment variable or configure llm.api_key in configs/default.yaml")
        sys.exit(1)

    print(f"Project:   {project_path}")
    print(f"API:       {config.api_base_url}")
    print(f"Model:     {config.model}")
    print(f"Output:    {OUTPUT_ROOT / project_name}")

    # --- Run ---
    analyzer = JavaAnalyzer(project_path)
    generator = TestGenerator(
        api_base_url=config.api_base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
    )

    results: list[tuple[str, bool]] = []
    for class_name, method_name in targets:
        label = f"{_short_name(class_name)}.{method_name}"
        ok = run_one(analyzer, generator, project_name, class_name, method_name)
        results.append((label, ok))

    # --- Summary ---
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    for label, ok in results:
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {label}")
    print(f"\n  {passed} succeeded, {failed} failed out of {len(results)} targets")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
