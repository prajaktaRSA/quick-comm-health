"""Money rounding.

Every amount (fares, discounts, fees) is a Decimal in rupees, never a float,
and is rounded to the paisa with ROUND_HALF_UP, the usual commercial rule.
Floats cannot represent most decimal fractions exactly, and Python's round()
rounds halves to even, so with floats 12.5% of Rs 69.00 comes out as 8.62
instead of 8.63.
"""

from decimal import ROUND_HALF_UP, Decimal

PAISA = Decimal("0.01")


def to_money(amount: Decimal) -> Decimal:
    return amount.quantize(PAISA, rounding=ROUND_HALF_UP)
