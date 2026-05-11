# -*- coding: utf-8 -*-
"""C++ analyzer -> generator -> executor feedback-loop test."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from testagent.analyzer import create_analyzer
from testagent.executor import create_executor
from testagent.models import AnalysisContext, GeneratedTest, TestResult
from tests.test_analyzer.test_cpp_analyzer import create_sample_cpp_project

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "test_executor_script_for_cpp_feedback",
        PROJECT_ROOT / "test_executor.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeedbackGenerator:
    """Deterministic generator that repairs a compile error from executor feedback."""

    def __init__(self) -> None:
        self.refine_feedback: TestResult | None = None

    def generate(self, context: AnalysisContext) -> GeneratedTest:
        return GeneratedTest(
            test_code="""\
#include "shop/pricing_service.h"

int main() {
    missing_symbol_for_feedback_loop();
    return 0;
}
""",
            iteration=1,
        )

    def refine(
        self,
        context: AnalysisContext,
        previous_test: GeneratedTest,
        test_result: TestResult,
    ) -> GeneratedTest:
        self.refine_feedback = test_result
        assert test_result.compiled is False
        assert "missing_symbol_for_feedback_loop" in test_result.compile_errors
        return GeneratedTest(
            test_code="""\
#include "shop/cart.h"
#include "shop/customer.h"
#include "shop/pricing_service.h"

#include <cassert>
#include <cmath>

int main() {
    shop::PricingService service;
    shop::Customer customer("gold", true);
    shop::Cart cart(customer, 100.0);

    const double actual = service.finalPrice(cart);
    assert(std::fabs(actual - 86.4) < 0.0001);
    return 0;
}
""",
            iteration=previous_test.iteration + 1,
        )


def test_cpp_pipeline_repairs_generated_test_from_execution_feedback(tmp_path: Path):
    script = _load_script()
    project = create_sample_cpp_project(tmp_path)
    analyzer = create_analyzer("cpp", project)
    generator = FeedbackGenerator()
    executor = create_executor(
        "cpp",
        project,
        reports_dir=tmp_path / "reports",
        keep_test=True,
    )

    ok = script.run_one(
        "shop::PricingService",
        "finalPrice",
        analyzer,
        generator,
        executor,
        max_iterations=2,
        min_branch_coverage=0.0,
    )

    assert ok is True
    assert generator.refine_feedback is not None
    assert (project / "tests" / "testagent" / "generated" / "shop_PricingService_finalPrice_iter2.cpp").is_file()
