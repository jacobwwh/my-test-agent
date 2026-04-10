"""Dependency resolution for Java source projects.

Given a set of type names and import statements from a target file, this
module locates the corresponding .java source files in the project tree and
extracts their source code and kind (class / interface / enum).
"""

from __future__ import annotations

from pathlib import Path

from testagent.analyzer.java_parser import (
    _SOURCE_DIRS,
    _find_children,
    _node_text,
    find_java_file,
    parse_source,
)
from testagent.models import Dependency

# JDK and primitive types that should never be resolved from project sources.
_BUILTIN_TYPES: set[str] = {
    # Primitives / wrappers
    "boolean", "byte", "char", "short", "int", "long", "float", "double", "void",
    "Boolean", "Byte", "Character", "Short", "Integer", "Long", "Float", "Double",
    "Void",
    # java.lang
    "String", "Object", "Class", "System", "Math", "Throwable", "Exception",
    "RuntimeException", "Error", "Thread", "Runnable", "Comparable", "Iterable",
    "AutoCloseable", "Override", "Deprecated", "SuppressWarnings", "StringBuilder",
    "StringBuffer", "Number",
    # Common collections (from java.util) — the user won't have source for these
    "List", "Map", "Set", "Collection", "ArrayList", "HashMap", "HashSet",
    "LinkedList", "TreeMap", "TreeSet", "Optional", "Iterator", "Collections",
    "Arrays", "Queue", "Deque", "LinkedHashMap", "LinkedHashSet",
    "Stream", "Collectors",
}


def _build_import_map(imports: list[str]) -> dict[str, str]:
    """根据 import 语句建立简单类名到全限定名的映射。

    功能简介：
        解析 Java 源码中的 import 语句，将普通 import 转成
        `简单类名 -> 全限定类名` 的映射；对于通配符 import，
        记录其包前缀以供后续模糊解析使用；静态 import 会被忽略。

    输入参数：
        imports:
            import 语句列表，例如 `["import com.example.Order;"]`。

    返回值：
        dict[str, str]:
            映射结果。普通 import 的 key 为简单类名；
            通配符 import 的 key 形如 `*com.example`。

    使用示例：
        >>> _build_import_map(["import com.example.Order;", "import com.example.*;"])
        {'Order': 'com.example.Order', '*com.example': 'com.example'}
    """
    mapping: dict[str, str] = {}
    for imp in imports:
        # Normalise: strip "import", optional "static", trailing ";"
        text = imp.strip().removeprefix("import").strip().removesuffix(";").strip()
        if text.startswith("static "):
            continue  # static imports are not type imports
        if text.endswith(".*"):
            # Wildcard — store the package prefix under a special key scheme.
            # We use a key like "*com.example" so callers can iterate.
            prefix = text[:-2]
            mapping[f"*{prefix}"] = prefix
        else:
            simple = text.rsplit(".", 1)[-1]
            mapping[simple] = text
    return mapping


def _detect_kind(root_node) -> str:
    """判断源码文件声明的顶层类型种类。

    功能简介：
        检查编译单元根节点的直接子节点，识别当前文件声明的是
        `class`、`interface` 还是 `enum`；若未命中，则默认返回 `class`。

    输入参数：
        root_node:
            Java 编译单元的 AST 根节点。

    返回值：
        str:
            类型种类字符串，取值为 `class`、`interface` 或 `enum`。

    使用示例：
        >>> root = parse_source(b"interface A {}")
        >>> _detect_kind(root)
        'interface'
    """
    for child in root_node.children:
        if child.type == "class_declaration":
            return "class"
        if child.type == "interface_declaration":
            return "interface"
        if child.type == "enum_declaration":
            return "enum"
    return "class"


def resolve_dependencies(
    project_path: Path,
    type_names: set[str],
    imports: list[str],
    target_package: str,
) -> list[Dependency]:
    """解析目标方法依赖到项目内源码文件。

    功能简介：
        将一组类型名与 import / package 信息结合起来，尝试在项目源码中
        找到对应的 `.java` 文件，并提取依赖源码与类型种类，生成依赖列表。

    输入参数：
        project_path:
            Java 项目根目录。
        type_names:
            待解析的类型名集合，通常来自 `all_referenced_types()`。
        imports:
            目标类文件中的 import 语句列表。
        target_package:
            目标类所在包名，用于同包类型解析。

    返回值：
        list[Dependency]:
            已成功解析到源码文件的依赖列表；内建类型、JDK 类型和项目中不存在的类型
            不会出现在结果里。

    使用示例：
        >>> resolve_dependencies(
        ...     Path("/repo/demo"),
        ...     {"Order", "Customer"},
        ...     ["import com.example.model.Order;"],
        ...     "com.example.service",
        ... )
        [Dependency(...)]
    """
    import_map = _build_import_map(imports)
    wildcard_packages = [v for k, v in import_map.items() if k.startswith("*")]

    resolved: list[Dependency] = []
    seen_paths: set[Path] = set()

    for type_name in sorted(type_names):
        if type_name in _BUILTIN_TYPES:
            continue

        qualified = _resolve_qualified_name(
            type_name, import_map, target_package, wildcard_packages,
        )
        for qname in qualified:
            file_path = find_java_file(project_path, qname)
            if file_path and file_path not in seen_paths:
                seen_paths.add(file_path)
                source_bytes = file_path.read_bytes()
                source_text = source_bytes.decode("utf-8")
                root = parse_source(source_bytes)
                kind = _detect_kind(root)
                resolved.append(Dependency(
                    kind=kind,
                    qualified_name=qname,
                    source=source_text,
                    file_path=file_path,
                ))
                break  # resolved — move to next type

    return resolved


def _resolve_qualified_name(
    simple_name: str,
    import_map: dict[str, str],
    target_package: str,
    wildcard_packages: list[str],
) -> list[str]:
    """为简单类名生成候选全限定类名列表。

    功能简介：
        按“显式 import -> 同包 -> 通配符 import”的优先级，
        生成一个简单类名可能对应的全限定类名候选列表。

    输入参数：
        simple_name:
            简单类名，例如 `Order`。
        import_map:
            由 `_build_import_map()` 生成的 import 映射。
        target_package:
            目标类所在包名。
        wildcard_packages:
            通配符 import 对应的包前缀列表。

    返回值：
        list[str]:
            按优先级排序的候选全限定类名列表。

    使用示例：
        >>> _resolve_qualified_name(
        ...     "Order",
        ...     {"Order": "com.example.model.Order"},
        ...     "com.example.service",
        ...     ["com.example.common"],
        ... )
        ['com.example.model.Order', 'com.example.service.Order', 'com.example.common.Order']
    """
    candidates: list[str] = []

    # 1. Explicit import
    if simple_name in import_map:
        candidates.append(import_map[simple_name])

    # 2. Same package
    if target_package:
        candidates.append(f"{target_package}.{simple_name}")

    # 3. Wildcard imports
    for pkg in wildcard_packages:
        candidates.append(f"{pkg}.{simple_name}")

    return candidates
