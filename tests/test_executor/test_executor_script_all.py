"""Tests for the root test_executor.py --all target discovery wiring."""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "test_executor_script_under_test",
        PROJECT_ROOT / "test_executor.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DummyAnalyzer:
    def list_testable_methods(self):
        return [
            ("com.example.Discovered", "run"),
            ("com.example.Discovered", "stop"),
        ]


def test_all_targets_replace_default_targets():
    script = _load_script()

    assert script._targets_for_all_flag(True, DummyAnalyzer()) == [
        ("com.example.Discovered", "run"),
        ("com.example.Discovered", "stop"),
    ]


def test_default_targets_are_used_without_all_flag():
    script = _load_script()

    assert script._targets_for_all_flag(False, DummyAnalyzer()) is script.DEFAULT_TARGETS


def test_all_targets_require_analyzer_discovery_support():
    script = _load_script()

    try:
        script._targets_for_all_flag(True, object())
    except ValueError as exc:
        assert "does not support testable method discovery" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_all_targets_fail_when_project_has_no_testable_methods():
    script = _load_script()

    class EmptyAnalyzer:
        def list_testable_methods(self):
            return []

    try:
        script._targets_for_all_flag(True, EmptyAnalyzer())
    except ValueError as exc:
        assert "No testable methods discovered" in str(exc)
    else:
        raise AssertionError("expected ValueError")
