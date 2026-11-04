from decimal import Decimal

import pytest

from cancellation import FlatCancellationFee
from models import CarType, Location, Ride


def make_ride() -> Ride:
    return Ride("R1", "U1", "D1", Location(0, 0), Location(10, 0), CarType.SEDAN, CarType.SEDAN)


class TestFlatCancellationFee:
    def test_default_fee_is_twenty_rupees(self) -> None:
        assert FlatCancellationFee().fee_for(make_ride()) == Decimal("20.00")

    def test_custom_amount_is_rounded_to_the_paisa(self) -> None:
        fee = FlatCancellationFee(Decimal("35.005")).fee_for(make_ride())
        assert fee == Decimal("35.01")
        assert fee.as_tuple().exponent == -2

    def test_zero_fee_allowed(self) -> None:
        assert FlatCancellationFee(Decimal("0")).fee_for(make_ride()) == Decimal("0.00")

    def test_negative_fee_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            FlatCancellationFee(Decimal("-1"))
