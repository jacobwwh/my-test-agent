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
