"""Prompt template loading and rendering."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from testagent.models import AnalysisContext, GeneratedTest, TestResult

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _get_env(prompts_dir: Path | None = None) -> Environment:
    """Create a Jinja2 environment for the prompts directory."""
    return Environment(
        loader=FileSystemLoader(str(prompts_dir or _PROMPTS_DIR)),
        keep_trailing_newline=True,
    )


def build_generate_prompt(
    context: AnalysisContext,
    prompts_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Build the chat messages for initial test generation.

    Returns a list of message dicts suitable for the OpenAI chat API.
    """
    env = _get_env(prompts_dir)
    template = env.get_template("generate_test.txt")
    rendered = template.render(
        target=context.target,
        dependencies=context.dependencies,
        imports=context.imports,
    )
    return [{"role": "user", "content": rendered}]


def build_refine_prompt(
    context: AnalysisContext,
    previous_test: GeneratedTest,
    test_result: TestResult,
    prompts_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Build the chat messages for iterative test refinement.

    Returns a list of message dicts suitable for the OpenAI chat API.
    """
    env = _get_env(prompts_dir)
    template = env.get_template("fix_test.txt")
    rendered = template.render(
        target=context.target,
        dependencies=context.dependencies,
        previous_test=previous_test,
        test_result=test_result,
    )
    return [{"role": "user", "content": rendered}]
