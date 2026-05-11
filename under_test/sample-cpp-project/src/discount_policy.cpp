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
