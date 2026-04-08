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
    """Map simple class names to fully-qualified names based on import statements.

    For example, ``import com.example.Order;`` → ``{"Order": "com.example.Order"}``.
    Wildcard imports (``import com.example.*;``) are stored under the key ``"*"``
    with the package prefix so that callers can attempt package-based lookup.
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
    """Detect whether the compilation unit declares a class, interface, or enum."""
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
    """Resolve type names to project-local .java source files.

    Resolution strategy (tried in order for each type name):
    1. Skip if the type is a known built-in / JDK type.
    2. Look up the type in the explicit import map.
    3. Assume the type lives in the same package as the target class.
    4. Try wildcard import packages.

    Only types whose .java files exist in the project are returned.
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
    """Return candidate fully-qualified names for *simple_name*, best-first."""
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
