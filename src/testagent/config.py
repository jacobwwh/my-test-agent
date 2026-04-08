"""Configuration loading from YAML with CLI parameter overrides."""

from __future__ import annotations

from pathlib import Path

import yaml

from testagent.models import Config

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "default.yaml"


def load_config(
    config_path: Path | None = None,
    **overrides: object,
) -> Config:
    """Load configuration from a YAML file and apply CLI overrides.

    Parameters
    ----------
    config_path:
        Path to a YAML config file.  Falls back to ``configs/default.yaml``
        shipped with the project when *None*.
    **overrides:
        Keyword arguments whose names match :class:`Config` fields.  Only
        non-``None`` values are applied, so callers can forward raw Click
        parameters without filtering.
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    raw: dict = {}
    if path.exists():
        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}

    # Flatten the nested YAML structure into Config field names.
    flat: dict[str, object] = {}
    ollama = raw.get("ollama", {})
    if "url" in ollama:
        flat["ollama_url"] = ollama["url"]
    if "model" in ollama:
        flat["model"] = ollama["model"]
    if "timeout" in ollama:
        flat["timeout"] = ollama["timeout"]

    pipeline = raw.get("pipeline", {})
    if "max_iterations" in pipeline:
        flat["max_iterations"] = pipeline["max_iterations"]

    executor = raw.get("executor", {})
    if "keep_test" in executor:
        flat["keep_test"] = executor["keep_test"]
    if "jacoco_enabled" in executor:
        flat["jacoco_enabled"] = executor["jacoco_enabled"]

    # CLI overrides take precedence (skip None values).
    for key, value in overrides.items():
        if value is not None:
            flat[key] = value

    return Config(**flat)
