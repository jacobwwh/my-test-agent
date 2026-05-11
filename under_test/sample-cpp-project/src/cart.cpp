#include "shop/cart.h"

#include <utility>

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
