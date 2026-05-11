#include "shop/tax_calculator.h"

namespace shop {

double TaxCalculator::taxFor(double amount) const {
    return amount * 0.08;
}

}  // namespace shop
