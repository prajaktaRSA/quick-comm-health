import pytest

from cancellation import FlatCancellationFee
from models import CarType, Location, Ride


def make_ride() -> Ride:
    return Ride("R1", "U1", "D1", Location(0, 0), Location(10, 0), CarType.SEDAN, CarType.SEDAN)


class TestFlatCancellationFee:
    def test_default_fee_is_twenty(self) -> None:
        assert FlatCancellationFee().fee_for(make_ride()) == 20.0

    def test_custom_amount(self) -> None:
        assert FlatCancellationFee(35.0).fee_for(make_ride()) == 35.0

    def test_zero_fee_allowed(self) -> None:
        assert FlatCancellationFee(0).fee_for(make_ride()) == 0

    def test_negative_fee_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            FlatCancellationFee(-1)
