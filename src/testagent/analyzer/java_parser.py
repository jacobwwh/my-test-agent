"""Java source parsing using tree-sitter.

Responsibilities:
- Find .java files by fully-qualified class name within a project source tree
- Parse Java files into ASTs
- Locate a target method within a class
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
    return ts.Parser(JAVA_LANGUAGE)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_java_file(project_path: Path, class_name: str) -> Path | None:
    """Locate the .java file for a fully-qualified class name.

    Searches standard Maven/Gradle source directories inside *project_path*.
    Returns the first match or ``None``.
    """
    relative = class_name.replace(".", "/") + ".java"
    for src_dir in _SOURCE_DIRS:
        candidate = project_path / src_dir / relative
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def parse_source(source: bytes) -> ts.Node:
    """Parse Java source bytes and return the root AST node."""
    parser = _make_parser()
    tree = parser.parse(source)
    return tree.root_node


def _node_text(node: ts.Node) -> str:
    """Decode the source text of an AST node."""
    return node.text.decode("utf-8") if node.text else ""


def _find_children(node: ts.Node, type_name: str) -> list[ts.Node]:
    """Return all direct children of *node* with the given type."""
    return [c for c in node.children if c.type == type_name]


# ---------------------------------------------------------------------------
# Top-level extraction from a compilation unit
# ---------------------------------------------------------------------------

def extract_package(root: ts.Node) -> str:
    """Return the package declaration string (e.g. ``"com.example"``)."""
    for child in root.children:
        if child.type == "package_declaration":
            # The scoped_identifier / identifier child holds the name.
            for c in child.children:
                if c.type in ("scoped_identifier", "identifier"):
                    return _node_text(c)
    return ""


def extract_imports(root: ts.Node) -> list[str]:
    """Return all import statements as strings."""
    imports: list[str] = []
    for child in root.children:
        if child.type == "import_declaration":
            imports.append(_node_text(child))
    return imports


# ---------------------------------------------------------------------------
# Class / method location
# ---------------------------------------------------------------------------

def _find_class_node(root: ts.Node, simple_name: str) -> ts.Node | None:
    """Find the class_declaration node matching *simple_name*."""
    for child in root.children:
        if child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            if name_node and _node_text(name_node) == simple_name:
                return child
    return None


def find_method_node(class_node: ts.Node, method_name: str) -> ts.Node | None:
    """Find a method_declaration inside *class_node* by name."""
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
    """Return names of all methods declared in *class_node*."""
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
    """Recursively collect all ``type_identifier`` texts under *node*."""
    results: list[str] = []
    if node.type == "type_identifier":
        results.append(_node_text(node))
    for child in node.children:
        results.extend(_collect_type_identifiers(child))
    return results


def extract_type_refs(class_node: ts.Node, method_node: ts.Node | None) -> TypeRefs:
    """Extract type references from a class declaration and optionally a method."""
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
    """Return the deduplicated set of all type names in *refs*."""
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
    """Parse a Java file and extract information about a target method.

    Parameters
    ----------
    project_path:
        Root of the Java project.
    class_name:
        Fully-qualified class name, e.g. ``"com.example.MyService"``.
    method_name:
        Name of the method to analyse.

    Raises
    ------
    FileNotFoundError
        If the .java file for *class_name* cannot be found.
    ValueError
        If the class or method cannot be located inside the file.
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
