# -*- coding: utf-8 -*-
"""Tests for testagent.cli_utils."""

from pathlib import Path

import pytest

from testagent.cli_utils import resolve_project_path, resolve_targets


def _short(class_name: str) -> str:
    return class_name.rsplit(".", 1)[-1]


DEFAULT_TARGETS = [
    ("com.example.Calculator", "add"),
    ("com.example.service.OrderService", "process"),
]


class TestResolveProjectPath:
    def test_prefers_cli_project(self, tmp_path):
        cli_project = tmp_path / "cli-project"
        resolved = resolve_project_path(
            cli_project=cli_project,
            config_project_path="/configured/project",
            default_project=Path("/default/project"),
        )
        assert resolved == cli_project

    def test_uses_config_project_when_cli_missing(self):
        resolved = resolve_project_path(
            cli_project=None,
            config_project_path="/configured/project",
            default_project=Path("/default/project"),
        )
        assert resolved == Path("/configured/project")

    def test_falls_back_to_default_when_cli_and_config_missing(self):
        default_project = Path("/default/project")
        resolved = resolve_project_path(
            cli_project=None,
            config_project_path=None,
            default_project=default_project,
        )
        assert resolved == default_project


class TestResolveTargets:
    def test_supports_explicit_class_and_method(self):
        targets = resolve_targets(
            target=None,
            class_name="com.acme.OrderService",
            method_name="submit",
            default_targets=DEFAULT_TARGETS,
            short_name=_short,
        )
        assert targets == [("com.acme.OrderService", "submit")]

    def test_requires_class_and_method_together(self):
        with pytest.raises(ValueError, match="Both --class and --method"):
            resolve_targets(
                target=None,
                class_name="com.acme.OrderService",
                method_name=None,
                default_targets=DEFAULT_TARGETS,
                short_name=_short,
            )

    def test_rejects_target_and_class_method_together(self):
        with pytest.raises(ValueError, match="either --target or --class/--method"):
            resolve_targets(
                target="Calculator.add",
                class_name="com.example.Calculator",
                method_name="add",
                default_targets=DEFAULT_TARGETS,
                short_name=_short,
            )

    def test_resolves_preset_target(self):
        targets = resolve_targets(
            target="Calculator.add",
            class_name=None,
            method_name=None,
            default_targets=DEFAULT_TARGETS,
            short_name=_short,
        )
        assert targets == [("com.example.Calculator", "add")]

    def test_reports_unknown_preset_target(self):
        with pytest.raises(ValueError, match="Preset target 'Missing.run' not found"):
            resolve_targets(
                target="Missing.run",
                class_name=None,
                method_name=None,
                default_targets=DEFAULT_TARGETS,
                short_name=_short,
            )
