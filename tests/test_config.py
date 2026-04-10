"""Tests for configuration loading."""

from pathlib import Path

from testagent.config import load_config


def test_load_config_reads_project_path(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "llm:",
                '  api_base_url: "https://example.test/v1"',
                '  api_key: "demo-key"',
                '  model: "demo-model"',
                "project:",
                '  path: "/workspace/java-project"',
                "pipeline:",
                "  max_iterations: 7",
                "executor:",
                "  keep_test: true",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path=config_path)

    assert config.api_base_url == "https://example.test/v1"
    assert config.project_path == "/workspace/java-project"
    assert config.max_iterations == 7
    assert config.keep_test is True


def test_cli_override_project_path_wins(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                '  path: "/workspace/from-config"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(
        config_path=config_path,
        project_path="/workspace/from-cli",
    )

    assert config.project_path == "/workspace/from-cli"
