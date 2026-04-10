"""Test generation orchestration using LLM."""

from __future__ import annotations

import logging
import re

from testagent.generator.llm_client import LLMClient
from testagent.generator.prompt import build_generate_prompt, build_refine_prompt
from testagent.models import AnalysisContext, GeneratedTest, TestResult

__all__ = [
    "TestGenerator",
    "extract_java_code",
    "normalize_test_class_name",
    "canonical_test_class_name",
]

logger = logging.getLogger(__name__)


def canonical_test_class_name(class_name: str) -> str:
    """Return the canonical test class name for a given fully-qualified class name.

    Convention: ``<SimpleClassName>Test``, e.g.
    ``"com.example.Calculator"`` → ``"CalculatorTest"``.
    """
    simple = class_name.rsplit(".", 1)[-1]
    return f"{simple}Test"


def normalize_test_class_name(test_code: str, class_name: str) -> str:
    """Rename the test class in *test_code* to match the canonical name.

    The LLM may produce any class name.  This function replaces the first
    ``class <Anything>`` declaration with the canonical name so that
    the executor can always predict the file name and the ``-Dtest=`` argument.
    """
    canonical = canonical_test_class_name(class_name)
    # Match the first top-level class declaration (public or package-private).
    new_code, count = re.subn(
        r'(?m)^(\s*(?:public\s+)?class\s+)(\w+)',
        lambda m: m.group(1) + canonical,
        test_code,
        count=1,
    )
    if count == 0:
        logger.warning(
            "Could not find class declaration to normalize; "
            "leaving test code unchanged."
        )
    return new_code


def extract_java_code(text: str) -> str:
    """Extract the first Java code block from markdown-formatted text.

    Looks for ```java ... ``` fences first.  Falls back to a generic
    ``` ... ``` fence, and finally returns the raw text stripped of
    leading/trailing whitespace if no fence is found.
    """
    # Try ```java block first
    match = re.search(r"```java\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fall back to generic code block
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # No code fence found – return raw text
    logger.warning("No code fence found in LLM response, using raw text.")
    return text.strip()


class TestGenerator:
    """Generates and refines JUnit test code via an OpenAI-compatible LLM.

    Parameters
    ----------
    api_base_url:
        Base URL for the OpenAI-compatible API.
    api_key:
        API key for authentication.
    model:
        Model identifier.
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        model: str = "qwen3.5-397b-a17b",
        timeout: int = 120,
    ) -> None:
        self._client = LLMClient(
            api_base_url=api_base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
        )

    def generate(self, context: AnalysisContext) -> GeneratedTest:
        """Generate an initial JUnit test for the target method.

        Parameters
        ----------
        context:
            Analysis context containing the target method and its dependencies.

        Returns
        -------
        GeneratedTest
            The generated test code with iteration=1.
        """
        messages = build_generate_prompt(context)
        logger.info("Generating initial test for %s.%s",
                     context.target.class_name, context.target.method_name)
        raw_response = self._client.chat(messages)
        test_code = extract_java_code(raw_response)
        test_code = normalize_test_class_name(test_code, context.target.class_name)
        return GeneratedTest(test_code=test_code, iteration=1)

    def refine(
        self,
        context: AnalysisContext,
        previous_test: GeneratedTest,
        test_result: TestResult,
    ) -> GeneratedTest:
        """Refine a previously generated test based on execution feedback.

        Parameters
        ----------
        context:
            Analysis context containing the target method and its dependencies.
        previous_test:
            The test from the previous iteration.
        test_result:
            Execution results from the previous test (errors, failures, coverage).

        Returns
        -------
        GeneratedTest
            The refined test code with an incremented iteration number.
        """
        messages = build_refine_prompt(context, previous_test, test_result)
        logger.info("Refining test for %s.%s (iteration %d -> %d)",
                     context.target.class_name, context.target.method_name,
                     previous_test.iteration, previous_test.iteration + 1)
        raw_response = self._client.chat(messages)
        test_code = extract_java_code(raw_response)
        test_code = normalize_test_class_name(test_code, context.target.class_name)
        return GeneratedTest(
            test_code=test_code,
            iteration=previous_test.iteration + 1,
        )
