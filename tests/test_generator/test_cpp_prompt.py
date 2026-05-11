# -*- coding: utf-8 -*-
"""Tests for C++ prompt rendering and generator normalization behavior."""

from __future__ import annotations

from pathlib import Path

from testagent.generator.prompt import build_generate_prompt, build_refine_prompt
from testagent.generator.test_generator import TestGenerator
from testagent.models import AnalysisContext, Dependency, GeneratedTest, TargetMethod, TestResult


def _cpp_context() -> AnalysisContext:
    target = TargetMethod(
        class_name="shop::PricingService",
        method_name="finalPrice",
        method_signature=(
            "double PricingService::finalPrice(const Cart& cart) const {\n"
            "    return cart.subtotal();\n"
            "}"
        ),
        file_path=Path("/project/src/pricing_service.cpp"),
        class_source=(
            "namespace shop {\n"
            "class PricingService {\n"
            "public:\n"
            "    double finalPrice(const Cart& cart) const;\n"
            "};\n"
            "}"
        ),
    )
    return AnalysisContext(
        target=target,
        dependencies=[
            Dependency(
                kind="header",
                qualified_name="shop::Cart",
                source="class Cart { public: double subtotal() const; };",
                file_path=Path("/project/include/shop/cart.h"),
            ),
        ],
        imports=['#include "shop/pricing_service.h"'],
        package="shop",
    )


def test_cpp_generate_prompt_is_not_placeholder():
    messages = build_generate_prompt(_cpp_context(), language="cpp")

    content = messages[0]["content"]
    assert "C++ support is not yet implemented" not in content
    assert "shop::PricingService::finalPrice" in content
    assert '#include "shop/pricing_service.h"' in content
    assert "int main()" in content
    assert "assert" in content


def test_cpp_refine_prompt_includes_execution_feedback():
    result = TestResult(
        compiled=False,
        compile_errors="error: use of undeclared identifier 'missing_symbol'",
        passed=False,
        test_output="",
        coverage=None,
    )
    previous = GeneratedTest(
        test_code="int main() { missing_symbol; return 0; }",
        iteration=1,
    )

    messages = build_refine_prompt(_cpp_context(), previous, result, language="cpp")

    content = messages[0]["content"]
    assert "error: use of undeclared identifier" in content
    assert "int main() { missing_symbol; return 0; }" in content
    assert "Output the COMPLETE fixed C++ test file" in content


def test_cpp_generator_does_not_apply_java_class_name_normalization(monkeypatch):
    generator = TestGenerator(
        api_base_url="https://example.test/v1",
        api_key="dummy",
        language="cpp",
    )

    monkeypatch.setattr(
        generator._client,
        "chat",
        lambda messages: "```cpp\nclass LocalHelper {};\nint main() { return 0; }\n```",
    )

    generated = generator.generate(_cpp_context())

    assert "class LocalHelper" in generated.test_code
    assert "shop::PricingServiceTest" not in generated.test_code
