# -*- coding: utf-8 -*-
"""End-to-end integration test: Analyzer -> Generator.

Runs the full analysis + test-generation pipeline against a Java project and
writes the generated tests to ``generated_tests/<project-name>/``. By default
it uses ``under_test/sample-java-project``, but the project root can be
overridden via config or CLI.

Usage::

    python test_generator.py                         # run all targets
    python test_generator.py --target Calculator.add  # single target
    python test_generator.py --class com.example.Calculator --method add
    python test_generator.py --list                   # list available targets
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from testagent.analyzer import create_analyzer
from testagent.cli_utils import resolve_project_path, resolve_targets
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

PRESET_TARGETS = DEFAULT_TARGETS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_name(class_name: str) -> str:
    """提取类的简单名称。

    功能简介：
        将全限定类名转换为不带包路径的简单类名，便于展示与拼接文件名。

    输入参数：
        class_name:
            全限定类名，例如 `com.example.service.OrderService`。

    返回值：
        str:
            简单类名，例如 `OrderService`。

    使用示例：
        >>> _short_name("com.example.service.OrderService")
        'OrderService'
    """
    return class_name.rsplit(".", 1)[-1]


def _output_path(project_name: str, class_name: str, method_name: str) -> Path:
    """构造生成测试的输出路径。

    功能简介：
        根据项目名、被测类名和方法名生成测试代码保存路径，
        输出位置位于 `generated_tests/<project-name>/` 下。

    输入参数：
        project_name:
            被测项目目录名。
        class_name:
            被测类的全限定类名。
        method_name:
            被测方法名。

    返回值：
        Path:
            生成测试文件的目标路径。

    使用示例：
        >>> _output_path("sample-java-project", "com.example.Calculator", "add")
        Path('generated_tests/sample-java-project/Calculator_add_Test.java')
    """
    simple_class = _short_name(class_name)
    filename = f"{simple_class}_{method_name}_Test.java"
    return OUTPUT_ROOT / project_name / filename


def _print_context_summary(ctx) -> None:
    """打印分析上下文摘要。

    功能简介：
        将目标类、方法、文件路径、包名和依赖数量等关键信息输出到终端，
        便于用户快速确认分析结果。

    输入参数：
        ctx:
            `AnalysisContext` 分析上下文对象。

    返回值：
        None:
            该函数只负责终端输出，不返回数据。

    使用示例：
        >>> _print_context_summary(ctx)
    """
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
    """保存生成的测试代码到文件。

    功能简介：
        创建输出文件所需的父目录，并将生成的测试代码写入目标路径。

    输入参数：
        path:
            输出文件路径。
        test_code:
            待写入的测试代码文本。

    返回值：
        None:
            该函数执行文件写入和终端提示，不返回业务结果。

    使用示例：
        >>> _save_test(Path("generated_tests/demo/FooTest.java"), "public class FooTest {}")
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(test_code, encoding="utf-8")
    print(f"  Saved to: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_one(
    analyzer,
    generator: TestGenerator,
    project_name: str,
    class_name: str,
    method_name: str,
) -> bool:
    """对单个目标执行分析与测试生成。

    功能简介：
        先调用分析器解析目标方法，再调用生成器请求 LLM 产出测试代码，
        最后将结果保存到输出目录并打印预览。

    输入参数：
        analyzer:
            Java 源码分析器。
        generator:
            测试生成器。
        project_name:
            被测项目名称，用于构造输出目录。
        class_name:
            被测类的全限定类名。
        method_name:
            被测方法名。

    返回值：
        bool:
            成功生成并保存测试时返回 `True`，否则返回 `False`。

    使用示例：
        >>> ok = run_one(analyzer, generator, "sample-java-project", "com.example.Calculator", "add")
    """
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
    """解析命令行参数。

    功能简介：
        定义并解析 `test_generator.py` 支持的 CLI 参数，
        包括目标方法、项目路径和模型覆盖项等。

    输入参数：
        无。

    返回值：
        argparse.Namespace:
            已解析的命令行参数对象。

    使用示例：
        >>> args = parse_args()
        >>> args.target
    """
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
        default=None,
        help="Path to the Java project under test (overrides config/default)",
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
    p.add_argument("--model", help="Override LLM model name")
    p.add_argument(
        "--language",
        default=None,
        help="Target language (default: java)",
    )
    return p.parse_args()


def main() -> None:
    """脚本主入口。

    功能简介：
        负责读取参数和配置、解析待处理目标、初始化分析器与生成器，
        并按顺序执行整个 Analyzer -> Generator 流程。

    输入参数：
        无。

    返回值：
        None:
            通过终端输出执行过程；失败时可能通过 `sys.exit()` 退出。

    使用示例：
        >>> main()
    """
    args = parse_args()

    # --- List mode ---
    if args.list:
        print("Preset targets:")
        for cls, method in PRESET_TARGETS:
            print(f"  {_short_name(cls)}.{method}  ({cls})")
        print("\nFor arbitrary projects, use --class <fully.qualified.Class> --method <methodName>.")
        return

    # --- Config ---
    overrides = {k: v for k, v in {
        "model": args.model,
        "project_path": str(args.project) if args.project is not None else None,
        "language": args.language,
    }.items() if v is not None}
    config = load_config(**overrides)
    project_path = resolve_project_path(args.project, config.project_path, SAMPLE_PROJECT)
    project_name = project_path.name

    # --- Resolve targets ---
    try:
        targets = resolve_targets(
            target=args.target,
            class_name=args.class_name,
            method_name=args.method_name,
            default_targets=PRESET_TARGETS,
            short_name=_short_name,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    if not config.api_key:
        print("Error: No API key configured.")
        print("Set the YUNWU_API_KEY environment variable or configure llm.api_key in configs/default.yaml")
        sys.exit(1)

    print(f"Project:   {project_path}")
    print(f"Language:  {config.language}")
    print(f"API:       {config.api_base_url}")
    print(f"Model:     {config.model}")
    print(f"Output:    {OUTPUT_ROOT / project_name}")

    # --- Run ---
    analyzer = create_analyzer(config.language, project_path)
    generator = TestGenerator(
        api_base_url=config.api_base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
        language=config.language,
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
