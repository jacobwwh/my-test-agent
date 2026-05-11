# -*- coding: utf-8 -*-
"""Tests for C++ analyzer support."""

from __future__ import annotations

from pathlib import Path

import pytest

from testagent.analyzer import create_analyzer
from testagent.models import AnalysisContext


def create_sample_cpp_project(root: Path) -> Path:
    project = root / "sample-cpp-project"
    (project / "include" / "shop").mkdir(parents=True)
    (project / "src").mkdir()

    (project / "include" / "shop" / "customer.h").write_text(
        """\
#pragma once

#include <string>

namespace shop {

class Customer {
public:
    Customer(std::string tier, bool loyalty_member);

    const std::string& tier() const;
    bool isLoyaltyMember() const;

private:
    std::string tier_;
    bool loyalty_member_;
};

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "src" / "customer.cpp").write_text(
        """\
#include "shop/customer.h"

namespace shop {

Customer::Customer(std::string tier, bool loyalty_member)
    : tier_(std::move(tier)), loyalty_member_(loyalty_member) {}

const std::string& Customer::tier() const {
    return tier_;
}

bool Customer::isLoyaltyMember() const {
    return loyalty_member_;
}

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "include" / "shop" / "cart.h").write_text(
        """\
#pragma once

#include "shop/customer.h"

namespace shop {

class Cart {
public:
    Cart(Customer customer, double subtotal);

    const Customer& customer() const;
    double subtotal() const;

private:
    Customer customer_;
    double subtotal_;
};

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "src" / "cart.cpp").write_text(
        """\
#include "shop/cart.h"

namespace shop {

Cart::Cart(Customer customer, double subtotal)
    : customer_(std::move(customer)), subtotal_(subtotal) {}

const Customer& Cart::customer() const {
    return customer_;
}

double Cart::subtotal() const {
    return subtotal_;
}

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "include" / "shop" / "discount_policy.h").write_text(
        """\
#pragma once

#include "shop/customer.h"

namespace shop {

class DiscountPolicy {
public:
    double discountRate(const Customer& customer) const;
};

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "src" / "discount_policy.cpp").write_text(
        """\
#include "shop/discount_policy.h"

namespace shop {

double DiscountPolicy::discountRate(const Customer& customer) const {
    if (customer.tier() == "gold") {
        return 0.20;
    }
    if (customer.isLoyaltyMember()) {
        return 0.10;
    }
    return 0.0;
}

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "include" / "shop" / "tax_calculator.h").write_text(
        """\
#pragma once

namespace shop {

class TaxCalculator {
public:
    double taxFor(double amount) const;
};

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "src" / "tax_calculator.cpp").write_text(
        """\
#include "shop/tax_calculator.h"

namespace shop {

double TaxCalculator::taxFor(double amount) const {
    return amount * 0.08;
}

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "include" / "shop" / "pricing_service.h").write_text(
        """\
#pragma once

#include "shop/cart.h"
#include "shop/discount_policy.h"
#include "shop/tax_calculator.h"

namespace shop {

class PricingService {
public:
    PricingService();

    double finalPrice(const Cart& cart) const;

private:
    DiscountPolicy discount_policy_;
    TaxCalculator tax_calculator_;
};

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "src" / "pricing_service.cpp").write_text(
        """\
#include "shop/pricing_service.h"

namespace shop {

PricingService::PricingService() = default;

double PricingService::finalPrice(const Cart& cart) const {
    if (cart.subtotal() <= 0.0) {
        return 0.0;
    }
    const double discount = cart.subtotal() * discount_policy_.discountRate(cart.customer());
    const double net = cart.subtotal() - discount;
    return net + tax_calculator_.taxFor(net);
}

}  // namespace shop
""",
        encoding="utf-8",
    )
    (project / "Makefile").write_text(
        """\
CXX ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O0 -g -Iinclude
TEST_FILE ?= tests/testagent/generated/test.cpp
TEST_BINARY ?= build/testagent/test_binary
REPORT_DIR ?= build/testagent
SOURCES := $(wildcard src/*.cpp)

.PHONY: testagent-test clean

testagent-test:
\tmkdir -p $(dir $(TEST_BINARY)) $(REPORT_DIR)
\t$(CXX) $(CXXFLAGS) $(SOURCES) $(TEST_FILE) -o $(TEST_BINARY)
\t$(TEST_BINARY)

clean:
\trm -rf build tests/testagent/generated
""",
        encoding="utf-8",
    )
    return project


@pytest.fixture
def sample_cpp_project(tmp_path: Path) -> Path:
    return create_sample_cpp_project(tmp_path)


def test_factory_creates_cpp_analyzer(sample_cpp_project: Path):
    analyzer = create_analyzer("cpp", sample_cpp_project)

    assert type(analyzer).__name__ == "CppAnalyzer"


def test_cpp_analyzer_extracts_target_and_cross_file_dependencies(sample_cpp_project: Path):
    analyzer = create_analyzer("cpp", sample_cpp_project)

    ctx = analyzer.analyze("shop::PricingService", "finalPrice")

    assert isinstance(ctx, AnalysisContext)
    assert ctx.target.class_name == "shop::PricingService"
    assert ctx.target.method_name == "finalPrice"
    assert "PricingService::finalPrice" in ctx.target.method_signature
    assert "class PricingService" in ctx.target.class_source
    assert ctx.package == "shop"
    assert '#include "shop/pricing_service.h"' in ctx.imports

    dependency_paths = {dep.file_path.relative_to(sample_cpp_project).as_posix() for dep in ctx.dependencies}
    assert "include/shop/cart.h" in dependency_paths
    assert "include/shop/customer.h" in dependency_paths
    assert "include/shop/discount_policy.h" in dependency_paths
    assert "include/shop/tax_calculator.h" in dependency_paths
    assert "src/cart.cpp" in dependency_paths
    assert "src/customer.cpp" in dependency_paths
    assert "src/discount_policy.cpp" in dependency_paths
    assert "src/tax_calculator.cpp" in dependency_paths


def test_cpp_analyzer_lists_public_header_methods(sample_cpp_project: Path):
    analyzer = create_analyzer("cpp", sample_cpp_project)

    targets = analyzer.list_testable_methods()

    assert ("shop::PricingService", "finalPrice") in targets
    assert ("shop::DiscountPolicy", "discountRate") in targets
    assert ("shop::PricingService", "PricingService") not in targets
