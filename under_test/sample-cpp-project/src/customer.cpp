#include "shop/customer.h"

#include <utility>

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
