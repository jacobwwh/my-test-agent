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
