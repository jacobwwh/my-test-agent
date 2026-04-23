"""Build tool detection, test file injection, and command execution.

Responsibilities:
- Detect Maven vs Gradle from project layout
- Write the generated test file into the project's test source tree,
  prepending a "大模型生成" banner comment
- Construct and execute the build command (mvn / gradle)
- Return raw stdout+stderr and the return code for downstream parsing
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from testagent.analyzer.java.java_parser import (
    extract_imports as parse_imports,
    extract_package as parse_package,
    parse_source,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Build tool detection
# ---------------------------------------------------------------------------

_MAVEN_MARKERS = ("pom.xml",)
_GRADLE_MARKERS = ("build.gradle", "build.gradle.kts")


def detect_build_tool(project_path: Path) -> str:
    """检测项目使用的构建工具。

    功能简介：
        根据项目根目录下的标志文件判断当前 Java 项目使用的是
        Maven 还是 Gradle。

    输入参数：
        project_path:
            被测 Java 项目的根目录。

    返回值：
        str:
            返回 `maven` 或 `gradle`。

    使用示例：
        >>> detect_build_tool(Path("/repo/demo"))
        'maven'

    异常：
        FileNotFoundError:
            当项目中既没有 `pom.xml` 也没有 `build.gradle(.kts)` 时抛出。
    """
    for marker in _MAVEN_MARKERS:
        if (project_path / marker).is_file():
            return "maven"
    for marker in _GRADLE_MARKERS:
        if (project_path / marker).is_file():
            return "gradle"
    raise FileNotFoundError(
        f"Neither pom.xml nor build.gradle found in {project_path}. "
        "Cannot detect build tool."
    )


# ---------------------------------------------------------------------------
# Test source directory
# ---------------------------------------------------------------------------

_TEST_SRC_CANDIDATES = (
    "src/test/java",
    "src/test",
)


def expected_test_file_path(project_path: Path, class_name: str) -> Path:
    """返回目标 Java 测试文件在项目中的约定路径。"""
    parts = class_name.split(".")
    simple_name = parts[-1]
    package_parts = parts[:-1]
    dest_dir = project_path / "src" / "test" / "java"
    if package_parts:
        dest_dir = dest_dir / Path(*package_parts)
    return dest_dir / f"{simple_name}Test.java"


def find_test_source_dir(project_path: Path) -> Path:
    """定位测试源码根目录。

    功能简介：
        优先查找项目中已存在的测试源码目录；若不存在，则返回默认的
        Maven 约定目录 `src/test/java`，但不主动创建。

    输入参数：
        project_path:
            被测 Java 项目的根目录。

    返回值：
        Path:
            测试源码根目录路径。

    使用示例：
        >>> find_test_source_dir(Path("/repo/demo"))
        Path('/repo/demo/src/test/java')
    """
    for candidate in _TEST_SRC_CANDIDATES:
        d = project_path / candidate
        if d.is_dir():
            return d
    # Default: Maven convention
    return project_path / "src" / "test" / "java"


# ---------------------------------------------------------------------------
# Package / class name extraction from generated test code
# ---------------------------------------------------------------------------

def extract_package_from_code(test_code: str) -> str:
    """从测试代码中提取 package 名称。

    功能简介：
        读取测试代码顶部的 `package` 声明，用于推导最终测试文件的目录结构。

    输入参数：
        test_code:
            测试代码文本。

    返回值：
        str:
            package 名称；若未声明 package，则返回空字符串。

    使用示例：
        >>> extract_package_from_code("package com.example;\\nclass A {}")
        'com.example'
    """
    source_bytes = _strip_leading_banner(test_code).encode("utf-8")
    return parse_package(parse_source(source_bytes))


def extract_class_name_from_code(test_code: str) -> str:
    """从测试代码中提取顶层类名。

    功能简介：
        使用正则匹配测试代码中的第一个顶层类声明，供构造文件名和执行参数使用。

    输入参数：
        test_code:
            测试代码文本。

    返回值：
        str:
            提取出的类名。

    使用示例：
        >>> extract_class_name_from_code("public class CalculatorTest {}")
        'CalculatorTest'

    异常：
        ValueError:
            当代码中不存在可识别的类声明时抛出。
    """
    source_bytes = _strip_leading_banner(test_code).encode("utf-8")
    root = parse_source(source_bytes)
    for child in root.children:
        if child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8")
    raise ValueError("Cannot find class declaration in generated test code.")


def _target_package_and_simple_name(class_name: str) -> tuple[str, str]:
    parts = class_name.split(".")
    if len(parts) == 1:
        return "", parts[0]
    return ".".join(parts[:-1]), parts[-1]


def _header_import_lines(source: str) -> list[str]:
    root = parse_source(_strip_leading_banner(source).encode("utf-8"))
    return parse_imports(root)


def _find_first_class_node(source_bytes: bytes):
    root = parse_source(source_bytes)
    for child in root.children:
        if child.type == "class_declaration":
            return root, child
    raise ValueError("Cannot find class declaration in generated test code.")


def _class_body_bytes(source_bytes: bytes, class_node) -> bytes:
    body = class_node.child_by_field_name("body")
    if body is None:
        return b""
    return source_bytes[body.start_byte + 1 : body.end_byte - 1]


def _class_member_nodes(class_node) -> list:
    body = class_node.child_by_field_name("body")
    if body is None:
        return []
    return body.named_children


def _node_text_bytes(source_bytes: bytes, node) -> bytes:
    return source_bytes[node.start_byte:node.end_byte]


def _find_java_text_block_end(source: str, start: int) -> int:
    search_from = start
    while True:
        end = source.find('"""', search_from)
        if end == -1:
            return -1
        backslashes = 0
        cursor = end - 1
        while cursor >= 0 and source[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return end
        search_from = end + 1


def _compact_java_whitespace_outside_literals(source: str) -> str:
    compacted: list[str] = []
    i = 0
    while i < len(source):
        if source.startswith('"""', i):
            end = _find_java_text_block_end(source, i + 3)
            if end == -1:
                compacted.append(source[i:])
                break
            compacted.append(source[i : end + 3])
            i = end + 3
            continue
        char = source[i]
        if char in {'"', "'"}:
            quote = char
            start = i
            i += 1
            escaped = False
            while i < len(source):
                current = source[i]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    i += 1
                    break
                i += 1
            compacted.append(source[start:i])
            continue
        if source.startswith("//", i):
            i = source.find("\n", i)
            if i == -1:
                break
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end == -1:
                break
            i = end + 2
            continue
        if char.isspace():
            i += 1
            continue
        compacted.append(char)
        i += 1
    return "".join(compacted)


def _field_signature(source_bytes: bytes, node) -> str:
    return _compact_java_whitespace_outside_literals(_node_text_bytes(source_bytes, node).decode("utf-8"))


def _class_field_signatures(source_bytes: bytes, class_node) -> set[str]:
    signatures: set[str] = set()
    for member in _class_member_nodes(class_node):
        if member.type != "field_declaration":
            continue
        signatures.add(_field_signature(source_bytes, member))
    return signatures


def _class_field_signatures_from_body(body: str) -> set[str]:
    source_bytes = f"class TestAgentGeneratedMergeTarget {{\n{body}\n}}".encode("utf-8")
    _, class_node = _find_first_class_node(source_bytes)
    return _class_field_signatures(source_bytes, class_node)


def _expand_removal_range(source_bytes: bytes, start: int, end: int, min_start: int, max_end: int) -> tuple[int, int]:
    while start > min_start and source_bytes[start - 1] in b" \t":
        start -= 1
    while end < max_end and source_bytes[end] in b" \t":
        end += 1
    if source_bytes[end : end + 2] == b"\r\n":
        end += 2
    elif end < max_end and source_bytes[end : end + 1] in {b"\n", b"\r"}:
        end += 1
    return start, end


def _render_class_body_without_duplicate_fields(
    source_bytes: bytes,
    class_node,
    excluded_field_signatures: set[str] | None = None,
) -> str:
    excluded = excluded_field_signatures or set()
    body = class_node.child_by_field_name("body")
    if body is None:
        return ""
    body_start = body.start_byte + 1
    body_end = body.end_byte - 1
    removal_ranges: list[tuple[int, int]] = []
    for member in _class_member_nodes(class_node):
        if member.type != "field_declaration":
            continue
        if _field_signature(source_bytes, member) not in excluded:
            continue
        removal_ranges.append(
            _expand_removal_range(source_bytes, member.start_byte, member.end_byte, body_start, body_end)
        )
    if not removal_ranges:
        return source_bytes[body_start:body_end].decode("utf-8").strip("\n")

    chunks: list[bytes] = []
    cursor = body_start
    for start, end in removal_ranges:
        chunks.append(source_bytes[cursor:start])
        cursor = end
    chunks.append(source_bytes[cursor:body_end])
    return b"".join(chunks).decode("utf-8").strip("\n")


def _render_class_source(source_bytes: bytes, class_node, new_name: str, new_body: str) -> str:
    name_node = class_node.child_by_field_name("name")
    body = class_node.child_by_field_name("body")
    if name_node is None or body is None:
        raise ValueError("Cannot find class declaration in generated test code.")

    header = source_bytes[class_node.start_byte:name_node.start_byte].decode("utf-8")
    header += new_name
    header += source_bytes[name_node.end_byte:body.start_byte].decode("utf-8")
    return f"{header}{{\n{new_body.rstrip()}\n}}"


def _strip_marked_block(body: str, class_name: str, method_name: str) -> str:
    begin = re.escape(f"// BEGIN testagent generated tests for {class_name}#{method_name}")
    end = re.escape(f"// END testagent generated tests for {class_name}#{method_name}")
    pattern = re.compile(rf"(?ms)^[ \t]*{begin}[ \t]*\n.*?^[ \t]*{end}[ \t]*\n?")
    return pattern.sub("", body).rstrip()


def _has_generated_banner(source: str) -> bool:
    return bool(re.match(r"(?ms)^\s*/\*.*?大模型生成.*?\*/", source))


def _strip_leading_banner(source: str) -> str:
    return re.sub(r"(?ms)^\s*/\*.*?大模型生成.*?\*/\s*\n?", "", source, count=1)


def _render_generated_block(
    test_code: str,
    class_name: str,
    method_name: str,
    excluded_field_signatures: set[str] | None = None,
) -> str:
    source_bytes = _strip_leading_banner(test_code).encode("utf-8")
    _, generated_class_node = _find_first_class_node(source_bytes)
    generated_body = _render_class_body_without_duplicate_fields(
        source_bytes,
        generated_class_node,
        excluded_field_signatures=excluded_field_signatures,
    )
    begin = f"// BEGIN testagent generated tests for {class_name}#{method_name}"
    end = f"// END testagent generated tests for {class_name}#{method_name}"
    if generated_body:
        return f"    {begin}\n{generated_body}\n    {end}"
    return f"    {begin}\n    {end}"


# ---------------------------------------------------------------------------
# AI-generated banner comment
# ---------------------------------------------------------------------------

def _make_banner(class_name: str, method_name: str, iteration: int) -> str:
    """构造 AI 生成测试的头部注释。

    功能简介：
        生成写入测试文件顶部的 banner 注释，标记该文件为自动生成，
        并记录目标类、目标方法与迭代轮次。

    输入参数：
        class_name:
            被测类的全限定类名。
        method_name:
            被测方法名。
        iteration:
            当前测试生成/修复的迭代次数。

    返回值：
        str:
            多行块注释字符串。

    使用示例：
        >>> _make_banner("com.example.Calculator", "add", 1)
    """
    return (
        "/*\n"
        " * 大模型生成 - 由 testagent 自动生成，请勿手动修改\n"
        " * Generated by: testagent (AI-powered test generation)\n"
        f" * Target:    {class_name}#{method_name}\n"
        f" * Iteration: {iteration}\n"
        " */\n"
    )


# ---------------------------------------------------------------------------
# Write test file
# ---------------------------------------------------------------------------

def write_test_file(
    test_code: str,
    project_path: Path,
    class_name: str,
    method_name: str,
    iteration: int,
) -> Path:
    """将测试代码写入被测项目的测试目录。

    功能简介：
        根据测试代码中的 package 和类名确定目标路径，自动创建父目录，
        在文件顶部插入 AI 生成 banner 后写入磁盘。

    输入参数：
        test_code:
            待写入的测试代码。
        project_path:
            被测 Java 项目根目录。
        class_name:
            被测类的全限定类名。
        method_name:
            被测方法名。
        iteration:
            当前迭代次数。

    返回值：
        Path:
            实际写入的测试文件绝对路径。

    使用示例：
        >>> path = write_test_file(code, Path("/repo/demo"), "com.example.Calculator", "add", 1)
        >>> path.name
        'CalculatorTest.java'
    """
    target_package, target_simple_name = _target_package_and_simple_name(class_name)
    target_test_class = f"{target_simple_name}Test"
    dest_file = expected_test_file_path(project_path, class_name)
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    banner = _make_banner(class_name, method_name, iteration)
    file_previously_existed = dest_file.is_file()
    base_source = dest_file.read_text(encoding="utf-8") if file_previously_existed else test_code
    source_for_parse_bytes = _strip_leading_banner(base_source).encode("utf-8")
    root, class_node = _find_first_class_node(source_for_parse_bytes)

    generated_imports = _header_import_lines(test_code)
    base_imports = parse_imports(root)
    merged_imports = []
    seen: set[str] = set()
    for line in base_imports + generated_imports:
        if line in seen:
            continue
        seen.add(line)
        merged_imports.append(line)

    body = _class_body_bytes(source_for_parse_bytes, class_node).decode("utf-8")
    existing_field_signatures: set[str] = set()
    if file_previously_existed:
        body = _strip_marked_block(body, class_name, method_name)
        existing_field_signatures = _class_field_signatures_from_body(body)
        if body:
            body = f"{body.rstrip()}\n\n{_render_generated_block(test_code, class_name, method_name, existing_field_signatures)}"
        else:
            body = _render_generated_block(test_code, class_name, method_name, existing_field_signatures)
    else:
        body = _render_generated_block(test_code, class_name, method_name)

    class_source = _render_class_source(source_for_parse_bytes, class_node, target_test_class, body)

    parts: list[str] = []
    if _has_generated_banner(base_source) or not file_previously_existed:
        parts.append(banner.rstrip("\n"))
    if target_package:
        parts.append(f"package {target_package};")
    if merged_imports:
        parts.append("\n".join(merged_imports))
    parts.append(class_source)
    annotated = "\n\n".join(parts).rstrip() + "\n"

    dest_file.write_text(annotated, encoding="utf-8")
    logger.info("Wrote test file: %s", dest_file)
    return dest_file


# ---------------------------------------------------------------------------
# Cleanup AI-generated test files
# ---------------------------------------------------------------------------

_BANNER_MARKER = "大模型生成"


def cleanup_generated_tests(
    project_path: Path,
    clean_marker: str = _BANNER_MARKER,
) -> list[Path]:
    """清理项目中的自动生成测试文件。

    功能简介：
        遍历测试源码目录，删除带有指定标记字符串的 `.java` 文件；
        当标记为空字符串时，删除测试目录下所有 `.java` 文件。

    输入参数：
        project_path:
            被测 Java 项目根目录。
        clean_marker:
            用于识别“可删除文件”的内容标记，默认为 `大模型生成`。

    返回值：
        list[Path]:
            实际删除的文件路径列表。

    使用示例：
        >>> cleanup_generated_tests(Path("/repo/demo"))
        [Path('/repo/demo/src/test/java/com/example/CalculatorTest.java')]
    """
    test_src_root = find_test_source_dir(project_path)
    if not test_src_root.is_dir():
        logger.info("Test source dir does not exist: %s — nothing to clean.", test_src_root)
        return []

    delete_all = clean_marker == ""

    deleted: list[Path] = []
    for java_file in test_src_root.rglob("*.java"):
        if delete_all:
            java_file.unlink()
            logger.info("Deleted test file: %s", java_file)
            deleted.append(java_file)
            continue
        try:
            content = java_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", java_file, exc)
            continue
        if clean_marker in content and _has_generated_banner(content):
            java_file.unlink()
            logger.info("Deleted generated test: %s", java_file)
            deleted.append(java_file)

    # Prune empty directories left behind (bottom-up).
    for dirpath in sorted(test_src_root.rglob("*"), reverse=True):
        if dirpath.is_dir() and not any(dirpath.iterdir()):
            dirpath.rmdir()
            logger.debug("Removed empty directory: %s", dirpath)

    return deleted


# ---------------------------------------------------------------------------
# Build commands
# ---------------------------------------------------------------------------

def _resolve_mvn(project_path: Path) -> str:
    """解析 Maven 可执行命令。

    功能简介：
        优先使用项目内的 `mvnw` wrapper；若不存在，则回退到系统 `mvn`。

    输入参数：
        project_path:
            被测 Java 项目根目录。

    返回值：
        str:
            可执行的 Maven 命令或 wrapper 路径。

    使用示例：
        >>> _resolve_mvn(Path("/repo/demo"))
        'mvn'
    """
    wrapper = project_path / "mvnw"
    return str(wrapper) if wrapper.is_file() else "mvn"


def _resolve_gradle(project_path: Path) -> str:
    """解析 Gradle 可执行命令。

    功能简介：
        优先使用项目内的 `gradlew` wrapper；若不存在，则回退到系统 `gradle`。

    输入参数：
        project_path:
            被测 Java 项目根目录。

    返回值：
        str:
            可执行的 Gradle 命令或 wrapper 路径。

    使用示例：
        >>> _resolve_gradle(Path("/repo/demo"))
        'gradle'
    """
    wrapper = project_path / "gradlew"
    return str(wrapper) if wrapper.is_file() else "gradle"


def build_maven_command(
    project_path: Path,
    test_class_name: str,
    package: str,
    report_dir: Path,
) -> list[str]:
    """构造 Maven 测试执行命令。

    功能简介：
        生成执行指定测试类并输出 JaCoCo 报告所需的 Maven 命令参数列表。

    输入参数：
        project_path:
            被测 Java 项目根目录。
        test_class_name:
            测试类名。
        package:
            测试类所在包名；为空时表示默认包。
        report_dir:
            覆盖率报告输出目录。

    返回值：
        list[str]:
            可直接传给 `subprocess.run()` 的 Maven 命令列表。

    使用示例：
        >>> build_maven_command(Path("/repo/demo"), "CalculatorTest", "com.example", Path("/tmp/reports"))
    """
    mvn = _resolve_mvn(project_path)
    fully_qualified = f"{package}.{test_class_name}" if package else test_class_name
    exec_file = report_dir / "jacoco.exec"
    return [
        mvn,
        "--batch-mode",
        "test",
        "jacoco:report",
        f"-Dtest={fully_qualified}",
        f"-Djacoco.destFile={exec_file}",
        f"-Djacoco.dataFile={exec_file}",
        f"-Djacoco.outputDirectory={report_dir}",
        "-DfailIfNoTests=false",
    ]


def build_gradle_command(
    project_path: Path,
    test_class_name: str,
    package: str,
    report_dir: Path,
) -> list[str]:
    """构造 Gradle 测试执行命令。

    功能简介：
        生成执行指定测试类并输出 JaCoCo 报告所需的 Gradle 命令参数列表。

    输入参数：
        project_path:
            被测 Java 项目根目录。
        test_class_name:
            测试类名。
        package:
            测试类所在包名；为空时表示默认包。
        report_dir:
            覆盖率报告输出目录。

    返回值：
        list[str]:
            可直接传给 `subprocess.run()` 的 Gradle 命令列表。

    使用示例：
        >>> build_gradle_command(Path("/repo/demo"), "CalculatorTest", "com.example", Path("/tmp/reports"))
    """
    gradle = _resolve_gradle(project_path)
    fully_qualified = f"{package}.{test_class_name}" if package else test_class_name
    exec_file = report_dir / "jacoco.exec"
    return [
        gradle,
        "test",
        "jacocoTestReport",
        f"--tests={fully_qualified}",
        # Pass report dir and exec file as project properties;
        # the build.gradle must honour them.
        f"-PjacocoReportDir={report_dir}",
        f"-PjacocoExecFile={exec_file}",
        "--continue",
    ]


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def run_build(project_path: Path, command: list[str], timeout: int = 300) -> tuple[int, str]:
    """执行构建命令并收集输出。

    功能简介：
        在被测项目目录中运行传入的构建命令，并将标准输出与标准错误合并后返回。

    输入参数：
        project_path:
            命令执行所在的项目目录。
        command:
            待执行的命令列表。
        timeout:
            超时时间，单位为秒。

    返回值：
        tuple[int, str]:
            二元组 `(returncode, output)`，分别表示进程退出码和合并后的输出文本。

    使用示例：
        >>> code, output = run_build(Path("/repo/demo"), ["mvn", "test"])
    """
    logger.info("Running build: %s", " ".join(command))
    result = subprocess.run(
        command,
        cwd=project_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        text=True,
    )
    return result.returncode, result.stdout
