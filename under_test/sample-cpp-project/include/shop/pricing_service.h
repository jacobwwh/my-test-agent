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
