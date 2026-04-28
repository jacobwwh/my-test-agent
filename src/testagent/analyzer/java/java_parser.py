# -*- coding: utf-8 -*-
"""Java source parsing using tree-sitter.

Responsibilities:
- Find .java files by fully-qualified class name within a project source tree
- Parse Java files into ASTs
- Locate a target method within a class
- Discover testable methods within project source files
- Extract method source, class source, imports, package
- Extract referenced type names (fields, params, return type, body types,
  superclass, interfaces)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter as ts
import tree_sitter_java as tsjava

JAVA_LANGUAGE = ts.Language(tsjava.language())

# Common source directories in Java projects.
_SOURCE_DIRS = ("src/main/java", "src/java", "src")


def _make_parser() -> ts.Parser:
    """创建 Java 语法解析器。

    功能简介：
        基于预先初始化好的 `JAVA_LANGUAGE` 构造一个 tree-sitter 解析器，
        供后续 Java 源码 AST 解析使用。

    输入参数：
        无。

    返回值：
        ts.Parser:
            可用于解析 Java 源码的解析器实例。

    使用示例：
        >>> parser = _make_parser()
        >>> isinstance(parser, ts.Parser)
        True
    """
    return ts.Parser(JAVA_LANGUAGE)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_java_file(project_path: Path, class_name: str) -> Path | None:
    """按全限定类名定位 Java 源文件。

    功能简介：
        在常见的 Maven / Gradle 源码目录中查找目标类对应的 `.java` 文件，
        找到后返回第一个匹配路径；如果不存在则返回 `None`。

    输入参数：
        project_path:
            Java 项目根目录。
        class_name:
            目标类的全限定类名，例如 `com.example.service.OrderService`。

    返回值：
        Path | None:
            命中的 Java 源文件路径；如果未找到则返回 `None`。

    使用示例：
        >>> find_java_file(Path("/repo/demo"), "com.example.Calculator")
        Path("/repo/demo/src/main/java/com/example/Calculator.java")
    """
    relative = class_name.replace(".", "/") + ".java"
    for src_dir in _SOURCE_DIRS:
        candidate = project_path / src_dir / relative
        if candidate.is_file():
            return candidate
    return None


def _is_test_source_path(project_path: Path, file_path: Path) -> bool:
    try:
        parts = file_path.relative_to(project_path).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[0] == "src" and parts[1] == "test"


def _iter_java_source_files(project_path: Path) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for src_dir in _SOURCE_DIRS:
        source_root = project_path / src_dir
        if not source_root.is_dir():
            continue
        for java_file in sorted(source_root.rglob("*.java")):
            resolved = java_file.resolve()
            if resolved in seen or _is_test_source_path(project_path, java_file):
                continue
            seen.add(resolved)
            files.append(java_file)
    return files


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def parse_source(source: bytes) -> ts.Node:
    """将 Java 源码字节串解析为 AST 根节点。

    功能简介：
        使用 tree-sitter Java 语法对输入源码进行解析，并返回语法树根节点，
        供后续提取 package、imports、类声明和方法声明等结构化信息。

    输入参数：
        source:
            Java 源码的字节内容，通常来自 `Path.read_bytes()`。

    返回值：
        ts.Node:
            语法树的根节点。

    使用示例：
        >>> root = parse_source(b"package com.example; class A {}")
        >>> root.type
        'program'
    """
    parser = _make_parser()
    tree = parser.parse(source)
    return tree.root_node


def _node_text(node: ts.Node) -> str:
    """读取 AST 节点对应的源码文本。

    功能简介：
        将 tree-sitter 节点持有的原始字节内容解码为 UTF-8 字符串；
        当节点没有文本内容时返回空字符串。

    输入参数：
        node:
            需要读取源码片段的 AST 节点。

    返回值：
        str:
            节点对应的源码文本。

    使用示例：
        >>> root = parse_source(b"class A {}")
        >>> _node_text(root)
        'class A {}'
    """
    return node.text.decode("utf-8") if node.text else ""


def _find_children(node: ts.Node, type_name: str) -> list[ts.Node]:
    """筛选指定类型的直接子节点。

    功能简介：
        遍历一个 AST 节点的直接子节点，返回所有 `type` 等于目标类型的节点，
        不做递归搜索。

    输入参数：
        node:
            待搜索的父节点。
        type_name:
            目标节点类型名，例如 `import_declaration`。

    返回值：
        list[ts.Node]:
            所有匹配的直接子节点列表；若没有匹配则返回空列表。

    使用示例：
        >>> root = parse_source(b"import a.B; import c.D; class A {}")
        >>> len(_find_children(root, "import_declaration"))
        2
    """
    return [c for c in node.children if c.type == type_name]


# ---------------------------------------------------------------------------
# Top-level extraction from a compilation unit
# ---------------------------------------------------------------------------

def extract_package(root: ts.Node) -> str:
    """提取 Java 文件中的 package 名称。

    功能简介：
        从编译单元根节点中查找 `package_declaration`，提取包名文本；
        如果源码未声明 package，则返回空字符串。

    输入参数：
        root:
            Java 编译单元的 AST 根节点。

    返回值：
        str:
            包名，例如 `com.example.service`；若不存在则为空字符串。

    使用示例：
        >>> root = parse_source(b"package com.example; class A {}")
        >>> extract_package(root)
        'com.example'
    """
    for child in root.children:
        if child.type == "package_declaration":
            # The scoped_identifier / identifier child holds the name.
            for c in child.children:
                if c.type in ("scoped_identifier", "identifier"):
                    return _node_text(c)
    return ""


def extract_imports(root: ts.Node) -> list[str]:
    """提取 Java 文件中的 import 语句。

    功能简介：
        收集编译单元根节点下的所有 `import_declaration`，
        按源码原样返回 import 语句列表。

    输入参数：
        root:
            Java 编译单元的 AST 根节点。

    返回值：
        list[str]:
            import 语句列表，例如 `["import java.util.List;"]`。

    使用示例：
        >>> root = parse_source(b"import java.util.List; class A {}")
        >>> extract_imports(root)
        ['import java.util.List;']
    """
    imports: list[str] = []
    for child in root.children:
        if child.type == "import_declaration":
            imports.append(_node_text(child))
    return imports


# ---------------------------------------------------------------------------
# Class / method location
# ---------------------------------------------------------------------------

def _find_class_node(root: ts.Node, simple_name: str) -> ts.Node | None:
    """按简单类名查找类声明节点。

    功能简介：
        在编译单元根节点的直接子节点中查找 `class_declaration`，
        返回类名等于指定简单类名的那个节点。

    输入参数：
        root:
            Java 编译单元的 AST 根节点。
        simple_name:
            类的简单名称，例如 `OrderService`。

    返回值：
        ts.Node | None:
            匹配的类声明节点；未找到时返回 `None`。

    使用示例：
        >>> root = parse_source(b"class A {} class B {}")
        >>> _find_class_node(root, "B").type
        'class_declaration'
    """
    for child in root.children:
        if child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            if name_node and _node_text(name_node) == simple_name:
                return child
    return None


def _top_level_class_nodes(root: ts.Node) -> list[ts.Node]:
    return [child for child in root.children if child.type == "class_declaration"]


def _has_modifier(node: ts.Node, modifier_name: str) -> bool:
    for child in node.children:
        if child.type != "modifiers":
            continue
        for modifier in child.children:
            if _node_text(modifier) == modifier_name:
                return True
    return False


def _is_testable_method_node(method_node: ts.Node) -> bool:
    if method_node.child_by_field_name("body") is None:
        return False
    return not any(
        _has_modifier(method_node, modifier)
        for modifier in ("private", "abstract", "native")
    )


def list_testable_methods(project_path: Path) -> list[tuple[str, str]]:
    """列出项目源码中可作为测试目标的 Java 方法。

    功能简介：
        扫描项目源码目录中的 `.java` 文件，跳过 `src/test` 下的测试源码，
        只收集顶层 class 中带方法体且非 `private`、非 `abstract`、非 `native`
        的方法。构造器、接口方法和无方法体声明不会被返回。

    输入参数：
        project_path:
            Java 项目根目录。

    返回值：
        list[tuple[str, str]]:
            按源码相对路径和文件内声明顺序排列的 `(class_name, method_name)` 列表。

    使用示例：
        >>> list_testable_methods(Path("/repo/demo"))
        [('com.example.Calculator', 'add')]
    """
    targets: list[tuple[str, str]] = []
    for java_file in _iter_java_source_files(project_path):
        source_bytes = java_file.read_bytes()
        root = parse_source(source_bytes)
        package = extract_package(root)
        for class_node in _top_level_class_nodes(root):
            name_node = class_node.child_by_field_name("name")
            if name_node is None:
                continue
            simple_name = _node_text(name_node)
            class_name = f"{package}.{simple_name}" if package else simple_name
            body = class_node.child_by_field_name("body")
            if body is None:
                continue
            for member in body.children:
                if member.type != "method_declaration" or not _is_testable_method_node(member):
                    continue
                method_name_node = member.child_by_field_name("name")
                if method_name_node is None:
                    continue
                targets.append((class_name, _node_text(method_name_node)))
    return targets


def find_method_node(class_node: ts.Node, method_name: str) -> ts.Node | None:
    """在类声明中按名称查找方法节点。

    功能简介：
        遍历类体中的成员节点，返回方法名等于目标名称的
        `method_declaration` 节点。

    输入参数：
        class_node:
            类声明 AST 节点。
        method_name:
            目标方法名，例如 `process`。

    返回值：
        ts.Node | None:
            匹配的方法声明节点；若不存在则返回 `None`。

    使用示例：
        >>> root = parse_source(b"class A { void run() {} }")
        >>> cls = _find_class_node(root, "A")
        >>> find_method_node(cls, "run").type
        'method_declaration'
    """
    body = class_node.child_by_field_name("body")
    if body is None:
        return None
    for member in body.children:
        if member.type == "method_declaration":
            name_node = member.child_by_field_name("name")
            if name_node and _node_text(name_node) == method_name:
                return member
    return None


def list_method_names(class_node: ts.Node) -> list[str]:
    """列出类中声明的所有方法名。

    功能简介：
        读取类体中的全部 `method_declaration` 成员，
        并按出现顺序返回方法名称列表。

    输入参数：
        class_node:
            类声明 AST 节点。

    返回值：
        list[str]:
            方法名列表；若类体为空则返回空列表。

    使用示例：
        >>> root = parse_source(b"class A { void a() {} int b() { return 1; } }")
        >>> cls = _find_class_node(root, "A")
        >>> list_method_names(cls)
        ['a', 'b']
    """
    body = class_node.child_by_field_name("body")
    if body is None:
        return []
    names: list[str] = []
    for member in body.children:
        if member.type == "method_declaration":
            name_node = member.child_by_field_name("name")
            if name_node:
                names.append(_node_text(name_node))
    return names


# ---------------------------------------------------------------------------
# Type-reference extraction
# ---------------------------------------------------------------------------

@dataclass
class TypeRefs:
    """Collected type names referenced by a class/method."""

    field_types: list[str] = field(default_factory=list)
    param_types: list[str] = field(default_factory=list)
    return_type: str | None = None
    body_types: list[str] = field(default_factory=list)
    superclass: str | None = None
    interfaces: list[str] = field(default_factory=list)


def _collect_type_identifiers(node: ts.Node) -> list[str]:
    """递归收集节点下出现的类型标识符。

    功能简介：
        深度遍历输入节点及其后代节点，提取所有 `type_identifier`
        对应的源码文本，用于后续依赖解析。

    输入参数：
        node:
            起始 AST 节点。

    返回值：
        list[str]:
            按遍历顺序收集到的类型名列表。

    使用示例：
        >>> root = parse_source(b"class A { List<String> names; }")
        >>> cls = _find_class_node(root, "A")
        >>> _collect_type_identifiers(cls)
        ['List', 'String']
    """
    results: list[str] = []
    if node.type == "type_identifier":
        results.append(_node_text(node))
    for child in node.children:
        results.extend(_collect_type_identifiers(child))
    return results


def extract_type_refs(class_node: ts.Node, method_node: ts.Node | None) -> TypeRefs:
    """提取类和方法中引用到的类型信息。

    功能简介：
        从类声明中提取父类、接口、字段类型，并在提供方法节点时继续提取
        返回类型、参数类型以及方法体中引用的类型，最终汇总为 `TypeRefs`。

    输入参数：
        class_node:
            目标类的 AST 节点。
        method_node:
            目标方法的 AST 节点；若为 `None`，则只提取类级别类型引用。

    返回值：
        TypeRefs:
            分类整理后的类型引用结果。

    使用示例：
        >>> root = parse_source(b"class A extends B { List<C> run(D d) { E e = null; return null; } }")
        >>> cls = _find_class_node(root, "A")
        >>> method = find_method_node(cls, "run")
        >>> refs = extract_type_refs(cls, method)
        >>> refs.superclass
        'B'
    """
    refs = TypeRefs()

    # Superclass
    superclass_node = class_node.child_by_field_name("superclass")
    if superclass_node is None:
        # tree-sitter-java may use a child with type "superclass"
        for c in class_node.children:
            if c.type == "superclass":
                superclass_node = c
                break
    if superclass_node:
        types = _collect_type_identifiers(superclass_node)
        if types:
            refs.superclass = types[0]

    # Interfaces
    for c in class_node.children:
        if c.type == "super_interfaces":
            refs.interfaces = _collect_type_identifiers(c)

    # Fields
    body = class_node.child_by_field_name("body")
    if body:
        for member in body.children:
            if member.type == "field_declaration":
                type_node = member.child_by_field_name("type")
                if type_node:
                    refs.field_types.extend(_collect_type_identifiers(type_node))

    # Method-specific refs
    if method_node is not None:
        # Return type
        return_node = method_node.child_by_field_name("type")
        if return_node:
            return_types = _collect_type_identifiers(return_node)
            if return_types:
                refs.return_type = return_types[0]

        # Parameters
        params_node = method_node.child_by_field_name("parameters")
        if params_node:
            for param in params_node.children:
                if param.type == "formal_parameter":
                    ptype = param.child_by_field_name("type")
                    if ptype:
                        refs.param_types.extend(_collect_type_identifiers(ptype))

        # Body types (types referenced inside the method body)
        body_node = method_node.child_by_field_name("body")
        if body_node:
            refs.body_types = _collect_type_identifiers(body_node)

    return refs


def all_referenced_types(refs: TypeRefs) -> set[str]:
    """合并并去重所有类型引用名称。

    功能简介：
        将 `TypeRefs` 中各类别的类型名合并为一个去重集合，
        便于后续统一做依赖解析。

    输入参数：
        refs:
            由 `extract_type_refs()` 生成的类型引用对象。

    返回值：
        set[str]:
            去重后的类型名集合。

    使用示例：
        >>> refs = TypeRefs(field_types=["List"], param_types=["Order"], return_type="Result")
        >>> sorted(all_referenced_types(refs))
        ['List', 'Order', 'Result']
    """
    types: set[str] = set()
    types.update(refs.field_types)
    types.update(refs.param_types)
    if refs.return_type:
        types.add(refs.return_type)
    types.update(refs.body_types)
    if refs.superclass:
        types.add(refs.superclass)
    types.update(refs.interfaces)
    # Filter out JDK / primitive-wrapper names that we don't need to resolve.
    return types


# ---------------------------------------------------------------------------
# High-level parse result
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    """Everything extracted from parsing a single .java file for a target method."""

    package: str
    imports: list[str]
    class_source: str
    method_source: str
    type_refs: TypeRefs
    file_path: Path


def parse_target(project_path: Path, class_name: str, method_name: str) -> ParseResult:
    """解析目标类并提取目标方法分析结果。

    功能简介：
        根据项目根目录、全限定类名和方法名定位 Java 文件，解析 AST，
        并提取包名、导入语句、类源码、方法源码以及类型引用等信息，
        作为分析阶段的统一输出。

    输入参数：
        project_path:
            Java 项目根目录。
        class_name:
            目标类的全限定类名，例如 `com.example.MyService`。
        method_name:
            目标方法名称，例如 `processOrder`。

    返回值：
        ParseResult:
            包含 package、imports、类源码、方法源码、类型引用和文件路径的结果对象。

    使用示例：
        >>> result = parse_target(Path("/repo/demo"), "com.example.Calculator", "add")
        >>> result.package
        'com.example'

    异常：
        FileNotFoundError:
            当目标类对应的 `.java` 文件不存在时抛出。
        ValueError:
            当类或方法在源码中不存在时抛出。
    """
    file_path = find_java_file(project_path, class_name)
    if file_path is None:
        raise FileNotFoundError(
            f"Cannot find .java file for class '{class_name}' in {project_path}"
        )

    source_bytes = file_path.read_bytes()
    source_text = source_bytes.decode("utf-8")
    root = parse_source(source_bytes)

    package = extract_package(root)
    imports = extract_imports(root)

    simple_name = class_name.rsplit(".", 1)[-1]
    class_node = _find_class_node(root, simple_name)
    if class_node is None:
        raise ValueError(
            f"Class '{simple_name}' not found in {file_path}"
        )

    method_node = find_method_node(class_node, method_name)
    if method_node is None:
        available = list_method_names(class_node)
        raise ValueError(
            f"Method '{method_name}' not found in class '{simple_name}'. "
            f"Available methods: {available}"
        )

    type_refs = extract_type_refs(class_node, method_node)

    return ParseResult(
        package=package,
        imports=imports,
        class_source=_node_text(class_node),
        method_source=_node_text(method_node),
        type_refs=type_refs,
        file_path=file_path,
    )
