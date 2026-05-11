#pragma once

#include "shop/customer.h"

namespace shop {

class DiscountPolicy {
public:
    double discountRate(const Customer& customer) const;
};

}  // namespace shop
