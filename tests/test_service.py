from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Sequence

import pytest

from cancellation import CancellationFeePolicy
from matching import HighestRatedDriverStrategy, NearestDriverStrategy
from models import CarType, Coupon, Location, Ride, RideStatus
from pricing import PricingStrategy, TieredPricingStrategy
from service import (
    InvalidCouponError,
    InvalidOperationError,
    NoDriverAvailableError,
    NotFoundError,
    RideService,
)

ORIGIN = Location(0, 0)
DROP = Location(10, 0)  # 10 km: sedan Rs 69.00, hatchback Rs 55.20
NOW = datetime(2026, 11, 4, 12, 0)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def service(clock: FakeClock) -> RideService:
    return RideService(
        pricing=TieredPricingStrategy(),
        matching=NearestDriverStrategy(),
        search_radius=5.0,
        clock=clock,
    )


@pytest.fixture
def ride(service: RideService) -> Ride:
    """An ongoing 10 km sedan ride by U1 with driver D1."""
    user = service.register_user("Asha")
    service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=4.5)
    return service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)


class TestRegistration:
    def test_users_get_sequential_ids(self, service: RideService) -> None:
        assert [service.register_user(name).id for name in ("Asha", "Rohan")] == ["U1", "U2"]

    def test_driver_is_registered_available_with_given_details(self, service: RideService) -> None:
        driver = service.register_driver("Ravi", CarType.SEDAN, Location(1, 2), rating=4.8)
        assert driver.id == "D1"
        assert driver.car_type is CarType.SEDAN
        assert driver.location == Location(1, 2)
        assert driver.rating == 4.8
        assert driver.is_available

    def test_user_and_driver_ids_are_independent(self, service: RideService) -> None:
        service.register_user("Asha")
        assert service.register_driver("Ravi", CarType.SEDAN, ORIGIN, rating=5).id == "D1"

    def test_invalid_rating_is_rejected_without_using_an_id(self, service: RideService) -> None:
        with pytest.raises(ValueError, match="rating"):
            service.register_driver("Bad", CarType.SEDAN, ORIGIN, rating=7)
        assert service.register_driver("Good", CarType.SEDAN, ORIGIN, rating=4).id == "D1"

    def test_search_radius_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="search_radius"):
            RideService(pricing=TieredPricingStrategy(), matching=NearestDriverStrategy(), search_radius=0)


class TestDriverLocation:
    def test_update_moves_registered_driver(self, service: RideService) -> None:
        driver = service.register_driver("Ravi", CarType.HATCHBACK, ORIGIN, rating=4.5)
        updated = service.update_driver_location(driver.id, Location(3, 4))
        assert updated is driver
        assert driver.location == Location(3, 4)

    def test_unknown_driver_raises_not_found(self, service: RideService) -> None:
        with pytest.raises(NotFoundError, match="D99"):
            service.update_driver_location("D99", ORIGIN)


class TestBooking:
    def test_books_nearest_driver_of_requested_type(self, service: RideService) -> None:
        user = service.register_user("Asha")
        service.register_driver("Far", CarType.SEDAN, Location(4, 0), rating=5)
        near = service.register_driver("Near", CarType.SEDAN, Location(1, 0), rating=4)

        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)

        assert ride.id == "R1"
        assert ride.driver_id == near.id
        assert ride.status is RideStatus.ONGOING
        assert not ride.is_upgraded
        assert not near.is_available

    def test_hatchback_preferred_over_nearer_sedan(self, service: RideService) -> None:
        user = service.register_user("Asha")
        service.register_driver("Sedan", CarType.SEDAN, Location(1, 0), rating=5)
        hatchback = service.register_driver("Hatch", CarType.HATCHBACK, Location(4, 0), rating=4)

        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.HATCHBACK)

        assert ride.driver_id == hatchback.id
        assert not ride.is_upgraded

    def test_hatchback_unavailable_upgrades_to_sedan(self, service: RideService) -> None:
        user = service.register_user("Asha")
        service.register_driver("Hatch far away", CarType.HATCHBACK, Location(50, 0), rating=5)
        sedan = service.register_driver("Sedan", CarType.SEDAN, Location(2, 0), rating=4)

        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.HATCHBACK)

        assert ride.driver_id == sedan.id
        assert ride.requested_car_type is CarType.HATCHBACK
        assert ride.assigned_car_type is CarType.SEDAN
        assert ride.is_upgraded

    def test_sedan_request_never_downgrades_to_hatchback(self, service: RideService) -> None:
        user = service.register_user("Asha")
        service.register_driver("Hatch", CarType.HATCHBACK, Location(1, 0), rating=5)
        with pytest.raises(NoDriverAvailableError, match="sedan"):
            service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)

    def test_driver_exactly_on_radius_is_eligible(self, service: RideService) -> None:
        user = service.register_user("Asha")
        driver = service.register_driver("Edge", CarType.SEDAN, Location(3, 4), rating=4)  # 5 km away
        assert service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN).driver_id == driver.id

    def test_driver_outside_radius_is_ignored(self, service: RideService) -> None:
        user = service.register_user("Asha")
        service.register_driver("Far", CarType.SEDAN, Location(5.01, 0), rating=5)
        with pytest.raises(NoDriverAvailableError):
            service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)

    def test_booked_driver_is_not_matched_again(self, service: RideService) -> None:
        asha, rohan = service.register_user("Asha"), service.register_user("Rohan")
        service.register_driver("Only", CarType.SEDAN, Location(1, 0), rating=5)
        service.book_ride(asha.id, ORIGIN, DROP, CarType.SEDAN)
        with pytest.raises(NoDriverAvailableError):
            service.book_ride(rohan.id, ORIGIN, DROP, CarType.SEDAN)

    def test_user_cannot_have_two_ongoing_rides(self, service: RideService) -> None:
        user = service.register_user("Asha")
        service.register_driver("A", CarType.SEDAN, Location(1, 0), rating=5)
        service.register_driver("B", CarType.SEDAN, Location(2, 0), rating=5)
        service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)
        with pytest.raises(InvalidOperationError, match="ongoing"):
            service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)

    def test_unknown_user_raises_not_found(self, service: RideService) -> None:
        service.register_driver("A", CarType.SEDAN, Location(1, 0), rating=5)
        with pytest.raises(NotFoundError, match="U99"):
            service.book_ride("U99", ORIGIN, DROP, CarType.SEDAN)

class TestNoDriverMessage:
    def test_names_every_car_type_tried(self, service: RideService) -> None:
        user = service.register_user("Asha")
        with pytest.raises(NoDriverAvailableError, match=r"^No hatchback or sedan available within 5 km$"):
            service.book_ride(user.id, ORIGIN, DROP, CarType.HATCHBACK)
        with pytest.raises(NoDriverAvailableError, match=r"^No sedan available within 5 km$"):
            service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)

    def test_counts_one_busy_driver_in_range(self, service: RideService) -> None:
        asha, rohan = service.register_user("Asha"), service.register_user("Rohan")
        service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=4.5)
        service.book_ride(asha.id, ORIGIN, DROP, CarType.SEDAN)
        with pytest.raises(NoDriverAvailableError, match=r"^No sedan available within 5 km \(1 nearby driver is on a ride\)$"):
            service.book_ride(rohan.id, ORIGIN, DROP, CarType.SEDAN)

    def test_counts_busy_drivers_of_upgrade_type(self, service: RideService) -> None:
        users = [service.register_user(name) for name in ("Asha", "Rohan", "Meera")]
        service.register_driver("Hatch", CarType.HATCHBACK, Location(1, 0), rating=4.5)
        service.register_driver("Sedan", CarType.SEDAN, Location(2, 0), rating=4.5)
        service.book_ride(users[0].id, ORIGIN, DROP, CarType.HATCHBACK)
        service.book_ride(users[1].id, ORIGIN, DROP, CarType.HATCHBACK)  # upgraded to the sedan
        with pytest.raises(NoDriverAvailableError, match=r"\(2 nearby drivers are on rides\)$"):
            service.book_ride(users[2].id, ORIGIN, DROP, CarType.HATCHBACK)

    def test_ignores_busy_drivers_out_of_range_or_of_other_types(self, service: RideService) -> None:
        asha, rohan, meera = (service.register_user(n) for n in ("Asha", "Rohan", "Meera"))
        service.register_driver("Hatch", CarType.HATCHBACK, Location(1, 0), rating=4.5)
        service.register_driver("Far sedan", CarType.SEDAN, Location(20, 0), rating=4.5)
        service.book_ride(asha.id, ORIGIN, DROP, CarType.HATCHBACK)  # busy hatchback nearby
        service.book_ride(rohan.id, Location(20, 0), DROP, CarType.SEDAN)  # busy sedan far away
        with pytest.raises(NoDriverAvailableError, match=r"^No sedan available within 5 km$"):
            service.book_ride(meera.id, ORIGIN, DROP, CarType.SEDAN)


class TestBookingConfiguration:
    def test_uses_injected_matching_strategy(self) -> None:
        service = RideService(pricing=TieredPricingStrategy(), matching=HighestRatedDriverStrategy())
        user = service.register_user("Asha")
        service.register_driver("Near", CarType.SEDAN, Location(1, 0), rating=3.9)
        best = service.register_driver("Far", CarType.SEDAN, Location(4, 0), rating=4.9)

        assert service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN).driver_id == best.id


class TestEndRide:
    def test_charges_tiered_fare_and_completes_ride(self, service: RideService, ride: Ride) -> None:
        fare = service.end_ride(ride.id)
        assert (fare.base_fare, fare.discount, fare.total) == (Decimal("69.00"), Decimal("0.00"), Decimal("69.00"))
        assert ride.status is RideStatus.COMPLETED
        assert ride.fare == Decimal("69.00")

    def test_driver_is_freed_at_drop_location(self, service: RideService) -> None:
        user = service.register_user("Asha")
        driver = service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=4.5)
        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)
        service.end_ride(ride.id)
        assert driver.location == DROP
        assert driver.is_available

    def test_upgraded_ride_is_charged_hatchback_price(self, service: RideService) -> None:
        user = service.register_user("Asha")
        service.register_driver("Sedan", CarType.SEDAN, Location(1, 0), rating=4.5)
        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.HATCHBACK)
        assert ride.is_upgraded
        assert service.end_ride(ride.id).total == Decimal("55.20")

    def test_user_can_book_again_after_ride_ends(self, service: RideService, ride: Ride) -> None:
        service.end_ride(ride.id)
        assert service.book_ride(ride.user_id, DROP, ORIGIN, CarType.SEDAN).id == "R2"

    def test_cannot_end_ride_twice(self, service: RideService, ride: Ride) -> None:
        service.end_ride(ride.id)
        with pytest.raises(InvalidOperationError, match="already completed"):
            service.end_ride(ride.id)

    def test_unknown_ride_raises_not_found(self, service: RideService) -> None:
        with pytest.raises(NotFoundError, match="R99"):
            service.end_ride("R99")

    def test_uses_injected_pricing_strategy(self) -> None:
        class FlatPricing(PricingStrategy):
            def calculate_fare(self, ride: Ride) -> Decimal:
                return Decimal("100.00")

        service = RideService(pricing=FlatPricing(), matching=NearestDriverStrategy())
        user = service.register_user("Asha")
        service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=4.5)
        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)
        assert service.end_ride(ride.id).total == Decimal("100.00")


class TestCoupons:
    @staticmethod
    def book(service: RideService, code: str, drop: Location = DROP, car_type: CarType = CarType.SEDAN) -> Ride:
        """Book a ride for a new user with a sedan driver 1 km away, using a coupon."""
        user = service.register_user("Asha")
        service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=4.5)
        return service.book_ride(user.id, ORIGIN, drop, car_type, coupon_code=code)

    def test_coupon_given_at_booking_discounts_fare(self, service: RideService) -> None:
        service.add_coupon(Coupon("SAVE10", Decimal("10")))
        ride = self.book(service, "SAVE10")
        assert ride.coupon_code == "SAVE10"
        fare = service.end_ride(ride.id)
        assert (fare.base_fare, fare.discount, fare.total) == (Decimal("69.00"), Decimal("6.90"), Decimal("62.10"))
        assert ride.fare == Decimal("62.10")

    def test_coupon_works_with_free_upgrade(self, service: RideService) -> None:
        service.add_coupon(Coupon("SAVE10", Decimal("10")))
        ride = self.book(service, "SAVE10", car_type=CarType.HATCHBACK)
        assert ride.is_upgraded
        assert service.end_ride(ride.id).total == Decimal("49.68")  # 55.20 hatchback price - 10% (5.52)

    def test_coupon_applies_after_minimum_fare(self, service: RideService) -> None:
        service.add_coupon(Coupon("SAVE20", Decimal("20")))
        ride = self.book(service, "SAVE20", drop=Location(2, 0))  # minimum fare 50
        assert service.end_ride(ride.id).total == Decimal("40.00")

    def test_half_paisa_discount_rounds_up(self, service: RideService) -> None:
        # 12.5% of Rs 69.00 is exactly Rs 8.625; with float and round() this was 8.62
        service.add_coupon(Coupon("EIGHTH", Decimal("12.5")))
        ride = self.book(service, "EIGHTH")
        fare = service.end_ride(ride.id)
        assert (fare.base_fare, fare.discount, fare.total) == (Decimal("69.00"), Decimal("8.63"), Decimal("60.37"))

    @pytest.mark.parametrize(
        "code, message",
        [("NOPE", "Coupon NOPE does not exist"), ("OLD", "Coupon OLD has expired"), ("GONE", "Coupon GONE does not exist")],
        ids=["unknown", "expired", "deleted"],
    )
    def test_invalid_coupon_books_nothing(self, service: RideService, code: str, message: str) -> None:
        service.add_coupon(Coupon("OLD", Decimal("10"), expires_at=NOW - timedelta(days=1)))
        service.add_coupon(Coupon("GONE", Decimal("10")))
        service.delete_coupon("GONE")

        with pytest.raises(InvalidCouponError, match=message):
            self.book(service, code)

        assert service.user_history("U1") == []
        assert service.book_ride("U1", ORIGIN, DROP, CarType.SEDAN).id == "R1"  # driver still free, no id used

    def test_coupon_expiring_before_ride_ends_is_dropped(self, service: RideService, clock: FakeClock) -> None:
        service.add_coupon(Coupon("SOON", Decimal("10"), expires_at=NOW + timedelta(minutes=30)))
        ride = self.book(service, "SOON")
        clock.now = NOW + timedelta(hours=1)
        fare = service.end_ride(ride.id)
        assert (fare.discount, fare.total) == (Decimal("0.00"), Decimal("69.00"))
        assert ride.coupon_code is None

    def test_coupon_deleted_before_ride_ends_is_dropped(self, service: RideService) -> None:
        service.add_coupon(Coupon("SAVE10", Decimal("10")))
        ride = self.book(service, "SAVE10")
        service.delete_coupon("SAVE10")
        assert service.end_ride(ride.id).total == Decimal("69.00")
        assert ride.coupon_code is None

    def test_duplicate_coupon_is_rejected(self, service: RideService) -> None:
        service.add_coupon(Coupon("SAVE10", Decimal("10")))
        with pytest.raises(InvalidOperationError, match="already exists"):
            service.add_coupon(Coupon("SAVE10", Decimal("20")))

    def test_deleting_unknown_coupon_raises_not_found(self, service: RideService) -> None:
        with pytest.raises(NotFoundError, match="NOPE"):
            service.delete_coupon("NOPE")


class TestCancellation:
    def test_cancel_charges_flat_fee(self, service: RideService, ride: Ride) -> None:
        assert service.cancel_ride(ride.id) == Decimal("20.00")
        assert ride.status is RideStatus.CANCELLED
        assert ride.fare == Decimal("20.00")

    def test_driver_is_freed_where_they_are(self, service: RideService) -> None:
        user = service.register_user("Asha")
        driver = service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=4.5)
        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.SEDAN)
        service.cancel_ride(ride.id)
        assert driver.is_available
        assert driver.location == Location(1, 0)

    def test_user_can_book_again_after_cancelling(self, service: RideService, ride: Ride) -> None:
        service.cancel_ride(ride.id)
        assert service.book_ride(ride.user_id, ORIGIN, DROP, CarType.SEDAN).id == "R2"

    def test_coupon_is_not_applied_to_fee(self, service: RideService) -> None:
        service.add_coupon(Coupon("SAVE50", Decimal("50")))
        ride = TestCoupons.book(service, "SAVE50")
        assert service.cancel_ride(ride.id) == Decimal("20.00")
        assert ride.coupon_code is None

    def test_cannot_cancel_completed_ride(self, service: RideService, ride: Ride) -> None:
        service.end_ride(ride.id)
        with pytest.raises(InvalidOperationError, match="already completed"):
            service.cancel_ride(ride.id)

    def test_cannot_end_or_recancel_cancelled_ride(self, service: RideService, ride: Ride) -> None:
        service.cancel_ride(ride.id)
        with pytest.raises(InvalidOperationError, match="already cancelled"):
            service.end_ride(ride.id)
        with pytest.raises(InvalidOperationError, match="already cancelled"):
            service.cancel_ride(ride.id)

    def test_unknown_ride_raises_not_found(self, service: RideService) -> None:
        with pytest.raises(NotFoundError, match="R99"):
            service.cancel_ride("R99")

    def test_uses_injected_cancellation_policy(self) -> None:
        class FreeForUpgrades(CancellationFeePolicy):
            def fee_for(self, ride: Ride) -> Decimal:
                return Decimal("0.00") if ride.is_upgraded else Decimal("20.00")

        service = RideService(
            pricing=TieredPricingStrategy(), matching=NearestDriverStrategy(), cancellation_policy=FreeForUpgrades()
        )
        user = service.register_user("Asha")
        service.register_driver("Sedan", CarType.SEDAN, Location(1, 0), rating=4.5)
        ride = service.book_ride(user.id, ORIGIN, DROP, CarType.HATCHBACK)
        assert service.cancel_ride(ride.id) == Decimal("0.00")

    def test_cancelled_rides_appear_in_history_filter(self, service: RideService, ride: Ride) -> None:
        service.cancel_ride(ride.id)
        assert service.user_history(ride.user_id, RideStatus.CANCELLED) == [ride]
        assert service.user_history(ride.user_id, RideStatus.ONGOING) == []
        assert service.driver_history(ride.driver_id, RideStatus.CANCELLED) == [ride]


class TestHistory:
    @pytest.fixture
    def history_service(self, service: RideService) -> RideService:
        """U1: R1 completed, R3 ongoing. U2: R2 ongoing. D1: R1, R2. D2: R3."""
        asha, rohan = service.register_user("Asha"), service.register_user("Rohan")
        service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=4.5)
        service.register_driver("Sunil", CarType.SEDAN, Location(2, 0), rating=4.5)
        short_drop = Location(1, 0)
        service.end_ride(service.book_ride(asha.id, ORIGIN, short_drop, CarType.SEDAN).id)  # R1 by D1
        service.book_ride(rohan.id, ORIGIN, short_drop, CarType.SEDAN)  # R2 by D1
        service.book_ride(asha.id, ORIGIN, short_drop, CarType.SEDAN)  # R3 by D2 (D1 busy)
        return service

    @staticmethod
    def ids(rides: Sequence[Ride]) -> list:
        return [r.id for r in rides]

    @pytest.mark.parametrize(
        "status, expected",
        [(None, ["R1", "R3"]), (RideStatus.ONGOING, ["R3"]), (RideStatus.COMPLETED, ["R1"])],
    )
    def test_user_history_by_status(
        self, history_service: RideService, status: Optional[RideStatus], expected: list
    ) -> None:
        assert self.ids(history_service.user_history("U1", status)) == expected

    @pytest.mark.parametrize(
        "status, expected",
        [(None, ["R1", "R2"]), (RideStatus.ONGOING, ["R2"]), (RideStatus.COMPLETED, ["R1"])],
    )
    def test_driver_history_by_status(
        self, history_service: RideService, status: Optional[RideStatus], expected: list
    ) -> None:
        assert self.ids(history_service.driver_history("D1", status)) == expected

    def test_history_excludes_other_users_and_drivers(self, history_service: RideService) -> None:
        assert self.ids(history_service.user_history("U2")) == ["R2"]
        assert self.ids(history_service.driver_history("D2")) == ["R3"]

    def test_completed_ride_in_history_carries_fare(self, history_service: RideService) -> None:
        (completed,) = history_service.user_history("U1", RideStatus.COMPLETED)
        assert completed.fare == Decimal("50.00")  # 1 km sedan, minimum fare

    def test_new_user_and_driver_have_empty_history(self, service: RideService) -> None:
        user = service.register_user("New")
        driver = service.register_driver("New", CarType.SEDAN, ORIGIN, rating=4)
        assert service.user_history(user.id) == []
        assert service.driver_history(driver.id) == []

    def test_unknown_user_or_driver_raises_not_found(self, service: RideService) -> None:
        with pytest.raises(NotFoundError, match="U99"):
            service.user_history("U99")
        with pytest.raises(NotFoundError, match="D99"):
            service.driver_history("D99")
