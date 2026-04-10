"""Shared helpers for script-level CLI resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Callable


def resolve_project_path(
    cli_project: Path | None,
    config_project_path: str | None,
    default_project: Path,
) -> Path:
    """Resolve the Java project path with CLI > config > default precedence."""
    if cli_project is not None:
        return cli_project

    if config_project_path:
        project_value = config_project_path.strip()
        if project_value:
            return Path(project_value).expanduser()

    return default_project


def resolve_targets(
    *,
    target: str | None,
    class_name: str | None,
    method_name: str | None,
    default_targets: list[tuple[str, str]],
    short_name: Callable[[str], str],
) -> list[tuple[str, str]]:
    """Resolve target methods from preset names or explicit class/method input."""
    if class_name or method_name:
        if target:
            raise ValueError("Use either --target or --class/--method, not both.")
        if not class_name or not method_name:
            raise ValueError("Both --class and --method are required together.")
        return [(class_name, method_name)]

    if target:
        simple_cls, _, method = target.partition(".")
        if not method:
            raise ValueError(f"Target must be 'ClassName.methodName', got '{target}'")

        matched = [
            (candidate_class, candidate_method)
            for candidate_class, candidate_method in default_targets
            if short_name(candidate_class) == simple_cls and candidate_method == method
        ]
        if not matched:
            raise ValueError(
                f"Preset target '{target}' not found. "
                "Use --list to see presets, or use --class/--method for arbitrary project targets."
            )
        return matched

    return default_targets
