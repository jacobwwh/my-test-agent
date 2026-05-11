# -*- coding: utf-8 -*-
"""Lightweight C++ source parsing for project-local test generation context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from testagent.models import Dependency

_HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx"}
_SOURCE_SUFFIXES = {".cc", ".cpp", ".cxx"}
_SOURCE_DIRS = ("src", "source", "lib")
_INCLUDE_DIRS = ("include", "src")


@dataclass
class CppParseResult:
    """C++ 目标方法解析结果。"""

    namespace: str
    imports: list[str]
    class_source: str
    method_source: str
    file_path: Path
    header_path: Path | None


def _simple_name(class_name: str) -> str:
    """提取 C++ 类的简单名称。"""
    return class_name.rsplit("::", 1)[-1]


def _namespace_name(class_name: str) -> str:
    """提取 C++ 类的命名空间。"""
    parts = class_name.rsplit("::", 1)
    return parts[0] if len(parts) == 2 else ""


def _iter_project_files(project_path: Path, suffixes: set[str]) -> list[Path]:
    """遍历项目中指定后缀的源码文件。"""
    roots = [project_path / name for name in (*_INCLUDE_DIRS, *_SOURCE_DIRS)]
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in suffixes or not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return files


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_includes(source: str) -> list[str]:
    """提取 C++ 源码中的 include 语句。

    功能简介：
        扫描源码文本，返回所有 `#include ...` 行，保留原始文本格式。

    输入参数：
        source:
            C++ 源码文本。

    返回值：
        list[str]:
            include 语句列表。
    """
    return [
        match.group(0).strip()
        for match in re.finditer(r"(?m)^\s*#\s*include\s+[<\"][^>\"]+[>\"]", source)
    ]


def _local_include_names(source: str) -> list[str]:
    return [
        match.group(1)
        for match in re.finditer(r'(?m)^\s*#\s*include\s+"([^"]+)"', source)
    ]


def _namespace_matches(source: str, namespace: str) -> bool:
    if not namespace:
        return True
    pattern = rf"\bnamespace\s+{re.escape(namespace)}\s*(?:\{{|=)"
    return bool(re.search(pattern, source))


def _find_matching_brace(source: str, open_index: int) -> int:
    depth = 0
    i = open_index
    while i < len(source):
        char = source[i]
        if char in {'"', "'"}:
            quote = char
            i += 1
            escaped = False
            while i < len(source):
                current = source[i]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    break
                i += 1
        elif source.startswith("//", i):
            newline = source.find("\n", i)
            if newline == -1:
                return len(source) - 1
            i = newline
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end == -1:
                return len(source) - 1
            i = end + 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("Unbalanced braces in C++ source.")


def _extract_class_block(source: str, simple_name: str) -> str | None:
    match = re.search(rf"\bclass\s+{re.escape(simple_name)}\b", source)
    if match is None:
        return None
    open_index = source.find("{", match.end())
    if open_index == -1:
        return None
    close_index = _find_matching_brace(source, open_index)
    end = close_index + 1
    while end < len(source) and source[end] in " \t\r\n;":
        end += 1
    return source[match.start():end].strip()


def find_cpp_class_file(project_path: Path, class_name: str) -> Path | None:
    """按类名定位 C++ 类声明所在文件。"""
    simple = _simple_name(class_name)
    namespace = _namespace_name(class_name)
    for path in _iter_project_files(project_path, _HEADER_SUFFIXES | _SOURCE_SUFFIXES):
        source = _read(path)
        has_class = re.search(rf"\bclass\s+{re.escape(simple)}\b", source)
        if has_class and _namespace_matches(source, namespace):
            return path
    return None


def _method_pattern(class_name: str, method_name: str) -> re.Pattern[str]:
    simple = _simple_name(class_name)
    namespace = _namespace_name(class_name)
    qualifiers = [re.escape(simple)]
    if namespace:
        qualifiers.insert(0, re.escape(class_name))
    qualifier_pattern = "|".join(qualifiers)
    return re.compile(
        rf"(?P<start>(?:^|[\n\r])[\w:<>,~*&\s]+\b(?:{qualifier_pattern})::"
        rf"{re.escape(method_name)}\s*\([^;{{}}]*\)\s*(?:const\s*)?(?:noexcept\s*)?)\{{",
        re.MULTILINE,
    )


def _extract_method_definition(
    source: str,
    class_name: str,
    method_name: str,
) -> str | None:
    pattern = _method_pattern(class_name, method_name)
    match = pattern.search(source)
    if match is None:
        return None
    open_index = source.find("{", match.end() - 1)
    close_index = _find_matching_brace(source, open_index)
    return source[match.start("start"): close_index + 1].strip()


def _find_method_definition_file(
    project_path: Path,
    class_name: str,
    method_name: str,
) -> tuple[Path, str] | None:
    for path in _iter_project_files(project_path, _SOURCE_SUFFIXES | _HEADER_SUFFIXES):
        source = _read(path)
        method_source = _extract_method_definition(source, class_name, method_name)
        if method_source is not None:
            return path, method_source
    return None


def _resolve_include(
    project_path: Path,
    including_file: Path,
    include_name: str,
) -> Path | None:
    candidates = [
        including_file.parent / include_name,
        project_path / include_name,
    ]
    candidates.extend(project_path / root / include_name for root in _INCLUDE_DIRS)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _paired_source(project_path: Path, header: Path) -> Path | None:
    stem = header.stem
    for src_dir in _SOURCE_DIRS:
        root = project_path / src_dir
        if not root.is_dir():
            continue
        for suffix in _SOURCE_SUFFIXES:
            candidate = root / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate.resolve()
    return None


def _dependency_name(path: Path, source: str) -> str:
    match = re.search(r"\bclass\s+(\w+)\b", source)
    if match is None:
        return path.stem
    namespace_match = re.search(r"\bnamespace\s+([\w:]+)\s*\{", source)
    if namespace_match:
        return f"{namespace_match.group(1)}::{match.group(1)}"
    return match.group(1)


def resolve_project_dependencies(
    project_path: Path,
    roots: list[Path],
) -> list[Dependency]:
    """解析 C++ 本地 include 依赖。

    功能简介：
        从目标头文件和实现文件出发，递归解析双引号 include，并补充头文件
        对应的同名 `.cpp` 实现文件。系统头文件不会进入依赖列表。

    输入参数：
        project_path:
            C++ 项目根目录。
        roots:
            解析起点文件列表。

    返回值：
        list[Dependency]:
            项目内依赖源码列表。
    """
    root_paths = {path.resolve() for path in roots if path is not None}
    queue = list(root_paths)
    seen = set(root_paths)
    dependencies: list[Dependency] = []

    while queue:
        current = queue.pop(0)
        source = _read(current)
        for include_name in _local_include_names(source):
            resolved = _resolve_include(project_path, current, include_name)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            dep_source = _read(resolved)
            dependencies.append(
                Dependency(
                    kind="header" if resolved.suffix in _HEADER_SUFFIXES else "source",
                    qualified_name=_dependency_name(resolved, dep_source),
                    source=dep_source,
                    file_path=resolved,
                )
            )
            queue.append(resolved)
            if resolved.suffix in _HEADER_SUFFIXES:
                paired = _paired_source(project_path, resolved)
                if paired is not None and paired not in seen:
                    seen.add(paired)
                    paired_source = _read(paired)
                    dependencies.append(
                        Dependency(
                            kind="source",
                            qualified_name=_dependency_name(paired, paired_source),
                            source=paired_source,
                            file_path=paired,
                        )
                    )
                    queue.append(paired)

    return dependencies


def parse_target(project_path: Path, class_name: str, method_name: str) -> CppParseResult:
    """解析 C++ 目标类方法。

    功能简介：
        定位目标类声明文件与方法实现文件，提取类声明、目标方法源码、
        include 列表和命名空间，作为生成 C++ 测试的上下文。

    输入参数：
        project_path:
            C++ 项目根目录。
        class_name:
            目标类名，可包含命名空间，例如 `shop::PricingService`。
        method_name:
            目标方法名。

    返回值：
        CppParseResult:
            结构化解析结果。

    异常：
        FileNotFoundError:
            找不到目标类声明文件。
        ValueError:
            找不到目标类声明块或目标方法定义。
    """
    header_path = find_cpp_class_file(project_path, class_name)
    if header_path is None:
        raise FileNotFoundError(f"Cannot find C++ class declaration for {class_name!r}.")

    header_source = _read(header_path)
    class_source = _extract_class_block(header_source, _simple_name(class_name))
    if class_source is None:
        raise ValueError(f"Class {class_name!r} not found in {header_path}.")

    method = _find_method_definition_file(project_path, class_name, method_name)
    if method is None:
        available = [
            method
            for cls, method in list_testable_methods(project_path)
            if cls == class_name
        ]
        raise ValueError(
            f"Method {method_name!r} not found for C++ class {class_name!r}. "
            f"Available methods: {available}"
        )
    method_path, method_source = method

    imports: list[str] = []
    seen: set[str] = set()
    for line in extract_includes(header_source) + extract_includes(_read(method_path)):
        if line not in seen:
            seen.add(line)
            imports.append(line)

    return CppParseResult(
        namespace=_namespace_name(class_name),
        imports=imports,
        class_source=class_source,
        method_source=method_source,
        file_path=method_path,
        header_path=header_path,
    )


def _class_public_block(source: str, simple_name: str) -> str:
    class_block = _extract_class_block(source, simple_name)
    if class_block is None:
        return ""
    body_start = class_block.find("{")
    body = class_block[body_start + 1:]
    public_match = re.search(r"(?m)^\s*public\s*:\s*$", body)
    if public_match is None:
        return ""
    start = public_match.end()
    next_section = re.search(r"(?m)^\s*(private|protected)\s*:\s*$", body[start:])
    end = start + next_section.start() if next_section else len(body)
    return body[start:end]


def _public_method_names(source: str, simple_name: str) -> list[str]:
    block = _class_public_block(source, simple_name)
    names: list[str] = []
    method_pattern = (
        r"(?m)^\s*(?!using\b)(?!typedef\b)"
        r"(?:[\w:<>,~*&]+\s+)+(\w+)\s*\([^;{}]*\)\s*"
        r"(?:const\s*)?(?:noexcept\s*)?;"
    )
    for match in re.finditer(
        method_pattern,
        block,
    ):
        name = match.group(1)
        if name == simple_name or name.startswith("operator"):
            continue
        names.append(name)
    return names


def _namespace_for_file(source: str) -> str:
    match = re.search(r"\bnamespace\s+([\w:]+)\s*\{", source)
    return match.group(1) if match else ""


def list_testable_methods(project_path: Path) -> list[tuple[str, str]]:
    """列出 C++ 头文件中的 public 方法目标。"""
    targets: list[tuple[str, str]] = []
    for path in _iter_project_files(project_path, _HEADER_SUFFIXES):
        source = _read(path)
        namespace = _namespace_for_file(source)
        for class_match in re.finditer(r"\bclass\s+(\w+)\b", source):
            simple = class_match.group(1)
            qualified = f"{namespace}::{simple}" if namespace else simple
            for method in _public_method_names(source, simple):
                targets.append((qualified, method))
    return targets
