"""Configuration loading from YAML with CLI parameter overrides."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from testagent.models import Config

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "default.yaml"


def load_config(
    config_path: Path | None = None,
    **overrides: object,
) -> Config:
    """加载并合并项目配置。

    功能简介：
        从 YAML 配置文件读取嵌套配置，展开为 `Config` 数据对象需要的字段，
        再依次应用环境变量和 CLI 覆盖项，返回最终生效的配置。

    输入参数：
        config_path:
            配置文件路径；为 `None` 时使用项目默认的 `configs/default.yaml`。
        **overrides:
            额外覆盖项，字段名需与 `Config` 数据类字段一致；
            值为 `None` 的项会被忽略。

    返回值：
        Config:
            合并后的最终配置对象。

    使用示例：
        >>> config = load_config(model="demo-model", max_iterations=3)
        >>> config.model
        'demo-model'
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    raw: dict = {}
    if path.exists():
        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}

    # Flatten the nested YAML structure into Config field names.
    flat: dict[str, object] = {}
    llm = raw.get("llm", {})
    if "api_base_url" in llm:
        flat["api_base_url"] = llm["api_base_url"]
    if "api_key" in llm:
        flat["api_key"] = llm["api_key"]
    if "model" in llm:
        flat["model"] = llm["model"]
    if "timeout" in llm:
        flat["timeout"] = llm["timeout"]

    project = raw.get("project", {})
    if "path" in project:
        flat["project_path"] = project["path"]

    pipeline = raw.get("pipeline", {})
    if "max_iterations" in pipeline:
        flat["max_iterations"] = pipeline["max_iterations"]
    if "min_branch_coverage" in pipeline:
        flat["min_branch_coverage"] = pipeline["min_branch_coverage"]

    executor = raw.get("executor", {})
    if "keep_test" in executor:
        flat["keep_test"] = executor["keep_test"]
    if "jacoco_enabled" in executor:
        flat["jacoco_enabled"] = executor["jacoco_enabled"]

    # Environment variable for API key takes precedence over config file.
    env_key = os.environ.get("YUNWU_API_KEY")
    if env_key and not flat.get("api_key"):
        flat["api_key"] = env_key

    # CLI overrides take precedence (skip None values).
    for key, value in overrides.items():
        if value is not None:
            flat[key] = value

    return Config(**flat)
