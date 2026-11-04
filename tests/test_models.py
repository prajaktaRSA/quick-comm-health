from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from models import CarType, Coupon, Driver, Location, Ride, RideStatus

NOW = datetime(2026, 11, 4, 12, 0)


class TestCoupon:
    @pytest.mark.parametrize(
        "percent, fare, expected",
        [
            ("10", "69.00", "6.90"),
            ("20", "55.20", "11.04"),
            ("100", "50.00", "50.00"),
            ("12.5", "69.00", "8.63"),   # exactly 8.625: float round() gives 8.62
            ("10", "55.75", "5.58"),     # exactly 5.575
            ("33.3", "69.00", "22.98"),  # 22.977
        ],
    )
    def test_discount_is_percentage_rounded_half_up_to_the_paisa(self, percent: str, fare: str, expected: str) -> None:
        discount = Coupon("SAVE", Decimal(percent)).discount_for(Decimal(fare))
        assert discount == Decimal(expected)
        assert discount.as_tuple().exponent == -2

    def test_not_expired_before_expiry(self) -> None:
        assert not Coupon("SAVE", Decimal("10"), expires_at=NOW + timedelta(seconds=1)).is_expired(NOW)

    def test_expired_at_and_after_expiry(self) -> None:
        coupon = Coupon("SAVE", Decimal("10"), expires_at=NOW)
        assert coupon.is_expired(NOW)
        assert coupon.is_expired(NOW + timedelta(days=1))

    def test_coupon_without_expiry_never_expires(self) -> None:
        assert not Coupon("SAVE", Decimal("10")).is_expired(NOW + timedelta(days=3650))

    @pytest.mark.parametrize("percent", ["0", "-5", "100.01"])
    def test_rejects_invalid_percent(self, percent: str) -> None:
        with pytest.raises(ValueError, match="discount_percent"):
            Coupon("BAD", Decimal(percent))


class TestRide:
    def make_ride(self) -> Ride:
        return Ride("R1", "U1", "D1", Location(0, 0), Location(3, 4), CarType.HATCHBACK, CarType.SEDAN)

    def test_distance_and_upgrade_flag(self) -> None:
        ride = self.make_ride()
        assert ride.distance == pytest.approx(5.0)
        assert ride.is_upgraded
        assert ride.status is RideStatus.ONGOING

    def test_complete_sets_status_and_fare(self) -> None:
        ride = self.make_ride()
        ride.complete(Decimal("50.00"))
        assert ride.status is RideStatus.COMPLETED
        assert ride.fare == Decimal("50.00")

    def test_cannot_complete_twice(self) -> None:
        ride = self.make_ride()
        ride.complete(Decimal("50.00"))
        with pytest.raises(ValueError, match="already completed"):
            ride.complete(Decimal("60.00"))

    def test_cancel_sets_status_and_fee(self) -> None:
        ride = self.make_ride()
        ride.cancel(Decimal("20.00"))
        assert ride.status is RideStatus.CANCELLED
        assert ride.fare == Decimal("20.00")

    def test_cannot_complete_cancelled_ride(self) -> None:
        ride = self.make_ride()
        ride.cancel(Decimal("20.00"))
        with pytest.raises(ValueError, match="already cancelled"):
            ride.complete(Decimal("50.00"))

    def test_cannot_cancel_completed_ride(self) -> None:
        ride = self.make_ride()
        ride.complete(Decimal("50.00"))
        with pytest.raises(ValueError, match="already completed"):
            ride.cancel(Decimal("20.00"))


class TestDriver:
    @pytest.mark.parametrize("rating", [-0.1, 5.1])
    def test_rejects_rating_outside_zero_to_five(self, rating: float) -> None:
        with pytest.raises(ValueError, match="rating"):
            Driver("D1", "Ravi", CarType.SEDAN, Location(0, 0), rating=rating)
