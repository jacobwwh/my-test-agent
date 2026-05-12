# -*- coding: utf-8 -*-
"""Tests for root-level project language detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from check_lang import detect_language, resolve_language


def test_detects_java_project_from_build_file(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")

    assert detect_language(tmp_path) == "java"


def test_detects_cpp_project_from_source_files(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "cart.cpp").write_text("int main() { return 0; }", encoding="utf-8")
    (src_dir / "cart.h").write_text("#pragma once\n", encoding="utf-8")

    assert detect_language(tmp_path) == "cpp"


def test_returns_other_for_unknown_project(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    assert detect_language(tmp_path) == "other"


def test_resolve_language_prefers_cli_override(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")

    assert resolve_language("c++", "java", tmp_path) == "cpp"


def test_resolve_language_uses_detected_project_before_config(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8")

    assert resolve_language(None, "java", tmp_path) == "cpp"


def test_resolve_language_falls_back_to_config_when_detection_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    assert resolve_language(None, "java", tmp_path) == "java"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("cpp", "cpp"),
        ("c++", "cpp"),
        (" Java ", "java"),
    ],
)
def test_resolve_language_normalizes_supported_aliases(
    tmp_path: Path,
    raw: str,
    expected: str,
) -> None:
    assert resolve_language(raw, None, tmp_path) == expected
