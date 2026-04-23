"""Summaries for existing Java test files."""

from __future__ import annotations

import re
from pathlib import Path

from testagent.analyzer.java.java_parser import (
    _find_class_node,
    _node_text,
    extract_imports,
    parse_source,
)
from testagent.models import TestFileSummary

_TEST_ANNOTATION_NAMES = {
    "Test",
    "ParameterizedTest",
    "RepeatedTest",
    "TestFactory",
    "TestTemplate",
}


def expected_test_file_path(project_path: Path, class_name: str) -> Path:
    """Return the conventional path for an existing Java test file."""

    parts = class_name.split(".")
    simple_name = parts[-1]
    package_parts = parts[:-1]
    return (
        project_path
        / "src"
        / "test"
        / "java"
        / Path(*package_parts)
        / f"{simple_name}Test.java"
    )


def _slice_before_body(node) -> str:
    body = node.child_by_field_name("body")
    if body is None:
        return _node_text(node).strip()
    return node.text[: body.start_byte - node.start_byte].decode("utf-8").rstrip()


def _annotation_name(text: str) -> str:
    match = re.search(r"@([\w.]+)", text)
    if match is None:
        return ""
    return match.group(1).split(".")[-1]


def _is_test_method(node) -> bool:
    for child in node.children:
        if child.type != "modifiers":
            continue
        for modifier in child.children:
            if not modifier.type.endswith("annotation"):
                continue
            if _annotation_name(_node_text(modifier)) in _TEST_ANNOTATION_NAMES:
                return True
    return False


def summarize_existing_test_file(project_path: Path, class_name: str) -> TestFileSummary | None:
    """Summarize an existing Java test file if it is present."""

    test_file = expected_test_file_path(project_path, class_name)
    if not test_file.is_file():
        return None

    source = test_file.read_bytes()
    root = parse_source(source)
    simple_name = class_name.split(".")[-1] + "Test"
    class_node = _find_class_node(root, simple_name)
    if class_node is None:
        return None

    body = class_node.child_by_field_name("body")
    field_declarations: list[str] = []
    helper_method_signatures: list[str] = []
    test_method_signatures: list[str] = []

    if body is not None:
        for member in body.children:
            if member.type == "field_declaration":
                field_declarations.append(_node_text(member).strip())
            elif member.type == "method_declaration":
                signature = _slice_before_body(member)
                if _is_test_method(member):
                    test_method_signatures.append(signature)
                else:
                    helper_method_signatures.append(signature)

    return TestFileSummary(
        file_path=test_file,
        imports=extract_imports(root),
        class_signature=_slice_before_body(class_node),
        field_declarations=field_declarations,
        helper_method_signatures=helper_method_signatures,
        test_method_signatures=test_method_signatures,
    )
