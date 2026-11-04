from datetime import datetime, timedelta

import pytest

from models import CarType, Coupon, Driver, Location, Ride, RideStatus

NOW = datetime(2026, 11, 4, 12, 0)


class TestCoupon:
    @pytest.mark.parametrize("percent, fare, expected", [(10, 69.0, 6.9), (20, 55.2, 11.04), (100, 50.0, 50.0)])
    def test_discount_is_percentage_of_fare(self, percent: float, fare: float, expected: float) -> None:
        assert Coupon("SAVE", percent).discount_for(fare) == pytest.approx(expected)

    def test_not_expired_before_expiry(self) -> None:
        assert not Coupon("SAVE", 10, expires_at=NOW + timedelta(seconds=1)).is_expired(NOW)

    def test_expired_at_and_after_expiry(self) -> None:
        coupon = Coupon("SAVE", 10, expires_at=NOW)
        assert coupon.is_expired(NOW)
        assert coupon.is_expired(NOW + timedelta(days=1))

    def test_coupon_without_expiry_never_expires(self) -> None:
        assert not Coupon("SAVE", 10).is_expired(NOW + timedelta(days=3650))

    @pytest.mark.parametrize("percent", [0, -5, 100.01])
    def test_rejects_invalid_percent(self, percent: float) -> None:
        with pytest.raises(ValueError, match="discount_percent"):
            Coupon("BAD", percent)


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
        ride.complete(50.0)
        assert ride.status is RideStatus.COMPLETED
        assert ride.fare == 50.0

    def test_cannot_complete_twice(self) -> None:
        ride = self.make_ride()
        ride.complete(50.0)
        with pytest.raises(ValueError, match="already completed"):
            ride.complete(60.0)

    def test_cancel_sets_status_and_fee(self) -> None:
        ride = self.make_ride()
        ride.cancel(20.0)
        assert ride.status is RideStatus.CANCELLED
        assert ride.fare == 20.0

    def test_cannot_complete_cancelled_ride(self) -> None:
        ride = self.make_ride()
        ride.cancel(20.0)
        with pytest.raises(ValueError, match="already cancelled"):
            ride.complete(50.0)

    def test_cannot_cancel_completed_ride(self) -> None:
        ride = self.make_ride()
        ride.complete(50.0)
        with pytest.raises(ValueError, match="already completed"):
            ride.cancel(20.0)


class TestDriver:
    @pytest.mark.parametrize("rating", [-0.1, 5.1])
    def test_rejects_rating_outside_zero_to_five(self, rating: float) -> None:
        with pytest.raises(ValueError, match="rating"):
            Driver("D1", "Ravi", CarType.SEDAN, Location(0, 0), rating=rating)
