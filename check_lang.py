# -*- coding: utf-8 -*-
"""Detect the primary language of a project under test."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

JAVA_BUILD_FILES = {
    "build.gradle",
    "build.gradle.kts",
    "pom.xml",
    "settings.gradle",
    "settings.gradle.kts",
}
CPP_BUILD_FILES = {
    "CMakeLists.txt",
    "compile_commands.json",
}
CPP_WEAK_BUILD_FILES = {
    "GNUmakefile",
    "Makefile",
    "makefile",
}
JAVA_SOURCE_EXTENSIONS = {".java"}
CPP_SOURCE_EXTENSIONS = {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
LANGUAGE_ALIASES = {
    "c++": "cpp",
    "cpp": "cpp",
    "java": "java",
}
SUPPORTED_LANGUAGES = {"cpp", "java"}
SKIP_DIR_NAMES = {
    ".cache",
    ".git",
    ".gradle",
    "__pycache__",
    "build",
    "generated_tests",
    "logs",
    "node_modules",
    "target",
    "tmp",
}


def normalize_language(language: str | None) -> str | None:
    """规范化语言参数。

    功能简介：
        将 CLI 或配置文件中的语言名称转换为项目内部使用的统一标识。
        目前会把 `c++` 归一化为 `cpp`。

    输入参数：
        language:
            原始语言名称；为空或空白字符串时视为未指定。

    返回值：
        str | None:
            规范化后的语言名称；未指定时返回 `None`。
    """
    if language is None:
        return None

    normalized = language.strip().lower()
    if not normalized:
        return None
    return LANGUAGE_ALIASES.get(normalized, normalized)


def _iter_project_files(project_path: Path, max_files: int) -> Iterator[Path]:
    """遍历项目文件并跳过常见产物目录。"""
    if project_path.is_file():
        yield project_path
        return

    seen = 0
    for root, dirnames, filenames in os.walk(project_path):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        for filename in filenames:
            yield Path(root) / filename
            seen += 1
            if seen >= max_files:
                return


def detect_language(project_path: str | Path, max_files: int = 5000) -> str:
    """识别被测项目的主要语言。

    功能简介：
        根据构建文件和源码扩展名对项目进行轻量级扫描，返回测试框架内部
        使用的语言标识。当前支持识别 `java` 与 `cpp`；无法判断时返回
        `other`。

    输入参数：
        project_path:
            被测项目根目录或单个源码文件路径。
        max_files:
            最多扫描的文件数量，用于避免在大型仓库中做无界遍历。

    返回值：
        str:
            `java`、`cpp` 或 `other`。
    """
    root = Path(project_path).expanduser()
    if not root.exists():
        return "other"

    java_score = 0
    cpp_score = 0

    for file_path in _iter_project_files(root, max_files):
        name = file_path.name
        suffix = file_path.suffix.lower()

        if name in JAVA_BUILD_FILES:
            java_score += 20
        elif name in CPP_BUILD_FILES:
            cpp_score += 20
        elif name in CPP_WEAK_BUILD_FILES:
            cpp_score += 4

        if suffix in JAVA_SOURCE_EXTENSIONS:
            java_score += 1
        elif suffix in CPP_SOURCE_EXTENSIONS:
            cpp_score += 1

    if java_score == 0 and cpp_score == 0:
        return "other"
    if java_score >= cpp_score:
        return "java"
    return "cpp"


def resolve_language(
    cli_language: str | None,
    config_language: str | None,
    project_path: str | Path,
    default_language: str = "java",
) -> str:
    """解析最终使用的语言。

    功能简介：
        按“CLI 显式指定 > 项目自动识别 > 配置文件 > 默认值”的顺序决定
        语言。这样在用户未手动传 `--language` 时，脚本会优先根据被测项目
        自动选择 `java` 或 `cpp`。

    输入参数：
        cli_language:
            CLI 参数中的语言值。
        config_language:
            配置文件读取到的语言值。
        project_path:
            被测项目路径。
        default_language:
            兜底语言，默认为 `java`。

    返回值：
        str:
            最终语言标识。
    """
    normalized_cli = normalize_language(cli_language)
    if normalized_cli:
        return normalized_cli

    detected = detect_language(project_path)
    if detected in SUPPORTED_LANGUAGES:
        return detected

    normalized_config = normalize_language(config_language)
    if normalized_config:
        return normalized_config

    normalized_default = normalize_language(default_language)
    return normalized_default or default_language


def main() -> None:
    """命令行入口：打印指定项目的识别结果。"""
    import argparse

    parser = argparse.ArgumentParser(description="Detect project language")
    parser.add_argument("project", nargs="?", default=".", help="Project path to inspect")
    args = parser.parse_args()
    print(detect_language(args.project))


if __name__ == "__main__":
    main()
