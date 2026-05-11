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
