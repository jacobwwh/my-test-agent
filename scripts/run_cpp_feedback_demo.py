# -*- coding: utf-8 -*-
"""Run a deterministic C++ analyzer-generator-executor feedback demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from test_executor import run_one
from testagent.analyzer import create_analyzer
from testagent.executor import create_executor
from testagent.generator.test_generator import TestGenerator

DEFAULT_CPP_PROJECT = PROJECT_ROOT.parent / "sample-cpp-project"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "tmp" / "reports" / "cpp-feedback-demo"


class DeterministicCppChat:
    """用于本地验证修复闭环的确定性聊天响应。"""

    def __init__(self) -> None:
        """初始化反馈记录。"""
        self.calls = 0
        self.used_feedback = False

    def __call__(self, messages: list[dict[str, str]]) -> str:
        """根据 prompt 轮次返回确定性的 C++ fenced code block。"""
        self.calls += 1
        prompt = messages[0]["content"]
        if self.calls == 1:
            return """```cpp
#include "shop/pricing_service.h"

int main() {
    missing_symbol_for_feedback_loop();
    return 0;
}
```"""
        if "missing_symbol_for_feedback_loop" not in prompt:
            raise RuntimeError("Refine prompt did not contain the expected compile feedback.")
        self.used_feedback = True
        return """```cpp
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
```"""


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Run the deterministic C++ feedback-loop demo.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=DEFAULT_CPP_PROJECT,
        help=f"C++ sample project path (default: {DEFAULT_CPP_PROJECT})",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"Report directory (default: {DEFAULT_REPORTS_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    """脚本主入口。"""
    args = parse_args()
    analyzer = create_analyzer("cpp", args.project)
    generator = TestGenerator(
        api_base_url="http://testagent.invalid/v1",
        api_key="deterministic-demo",
        language="cpp",
    )
    deterministic_chat = DeterministicCppChat()
    generator._client.chat = deterministic_chat
    executor = create_executor(
        "cpp",
        args.project,
        reports_dir=args.reports_dir,
        keep_test=True,
    )

    ok = run_one(
        "shop::PricingService",
        "finalPrice",
        analyzer,
        generator,
        executor,
        max_iterations=2,
        min_branch_coverage=0.0,
    )
    if not ok or not deterministic_chat.used_feedback:
        sys.exit(1)


if __name__ == "__main__":
    main()
