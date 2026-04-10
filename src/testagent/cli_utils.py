"""Shared helpers for script-level CLI resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Callable


def resolve_project_path(
    cli_project: Path | None,
    config_project_path: str | None,
    default_project: Path,
) -> Path:
    """按优先级解析被测项目路径。

    功能简介：
        根据“CLI 参数 > 配置文件 > 默认路径”的优先级决定最终使用的
        Java 项目根目录。

    输入参数：
        cli_project:
            CLI 传入的项目路径；若提供则优先使用。
        config_project_path:
            配置文件中的项目路径字符串。
        default_project:
            当前脚本内置的默认项目路径。

    返回值：
        Path:
            最终解析得到的项目根目录路径。

    使用示例：
        >>> resolve_project_path(None, "/repo/from-config", Path("/repo/default"))
        Path('/repo/from-config')
    """
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
    """解析待执行的目标方法列表。

    功能简介：
        支持两种输入方式：
        1. 使用预设目标名 `ClassName.methodName`
        2. 通过 `--class` 与 `--method` 显式指定任意目标
        若两者都未提供，则返回默认目标列表。

    输入参数：
        target:
            预设目标名，例如 `Calculator.add`。
        class_name:
            显式指定的全限定类名。
        method_name:
            显式指定的方法名。
        default_targets:
            默认目标列表，每项为 `(class_name, method_name)`。
        short_name:
            用于将全限定类名映射为简单类名的函数。

    返回值：
        list[tuple[str, str]]:
            解析后的目标列表，每项为 `(class_name, method_name)`。

    使用示例：
        >>> resolve_targets(
        ...     target="Calculator.add",
        ...     class_name=None,
        ...     method_name=None,
        ...     default_targets=[("com.example.Calculator", "add")],
        ...     short_name=lambda s: s.rsplit(".", 1)[-1],
        ... )
        [('com.example.Calculator', 'add')]

    异常：
        ValueError:
            当 `--target` 与 `--class/--method` 混用，或输入不完整/不合法时抛出。
    """
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
