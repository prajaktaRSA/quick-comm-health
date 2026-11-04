"""RideService: the application layer over in-memory storage.

Storage is plain dicts keyed by id. Records are never deleted, so ids are
the next number in each dict with a prefix (U1, D1, R1), which keeps them
short for the CLI and leaves no gaps when a registration fails validation.

Pricing and matching strategies are injected, and the car-type upgrade rule
is data (car_type_fallbacks), so surge pricing, new matching rules or new
upgrade paths need no edits here. The clock is injected so coupon expiry
can be tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from matching import MatchingStrategy
from models import CarType, Coupon, Driver, Location, Ride, RideStatus, User
from pricing import PricingStrategy

DEFAULT_CAR_TYPE_FALLBACKS: Mapping[CarType, Sequence[CarType]] = {
    CarType.HATCHBACK: (CarType.HATCHBACK, CarType.SEDAN),
    CarType.SEDAN: (CarType.SEDAN,),
}


class RideServiceError(Exception):
    """Base class for errors the CLI reports to the user without crashing."""


class NotFoundError(RideServiceError):
    pass


class NoDriverAvailableError(RideServiceError):
    pass


class InvalidOperationError(RideServiceError):
    pass


class InvalidCouponError(RideServiceError):
    pass


@dataclass(frozen=True)
class FareBreakdown:
    base_fare: float
    discount: float
    total: float


class RideService:
    def __init__(
        self,
        pricing: PricingStrategy,
        matching: MatchingStrategy,
        search_radius: float = 5.0,
        car_type_fallbacks: Mapping[CarType, Sequence[CarType]] = DEFAULT_CAR_TYPE_FALLBACKS,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        if search_radius <= 0:
            raise ValueError("search_radius must be positive")
        self._pricing = pricing
        self._matching = matching
        self._search_radius = search_radius
        self._car_type_fallbacks = dict(car_type_fallbacks)
        self._clock = clock
        self._users: Dict[str, User] = {}
        self._drivers: Dict[str, Driver] = {}
        self._rides: Dict[str, Ride] = {}
        self._coupons: Dict[str, Coupon] = {}

    # Users and drivers

    def register_user(self, name: str) -> User:
        user = User(id=f"U{len(self._users) + 1}", name=name)
        self._users[user.id] = user
        return user

    def register_driver(self, name: str, car_type: CarType, location: Location, rating: float) -> Driver:
        driver = Driver(
            id=f"D{len(self._drivers) + 1}",
            name=name,
            car_type=car_type,
            location=location,
            rating=rating,
        )
        self._drivers[driver.id] = driver
        return driver

    def update_driver_location(self, driver_id: str, location: Location) -> Driver:
        driver = self._get_driver(driver_id)
        driver.location = location
        return driver

    # Rides

    def book_ride(self, user_id: str, pickup: Location, drop: Location, car_type: CarType) -> Ride:
        self._get_user(user_id)
        if any(r.user_id == user_id and r.status is RideStatus.ONGOING for r in self._rides.values()):
            raise InvalidOperationError(f"User {user_id} already has an ongoing ride")

        driver = self._find_driver(pickup, car_type)
        if driver is None:
            raise NoDriverAvailableError(f"No driver for {car_type.value} within {self._search_radius:g} km")

        driver.is_available = False
        ride = Ride(
            id=f"R{len(self._rides) + 1}",
            user_id=user_id,
            driver_id=driver.id,
            pickup=pickup,
            drop=drop,
            requested_car_type=car_type,
            assigned_car_type=driver.car_type,
        )
        self._rides[ride.id] = ride
        return ride

    def end_ride(self, ride_id: str) -> FareBreakdown:
        """Complete the ride and charge it. A coupon that was deleted or expired
        after being applied is dropped rather than blocking the ride from ending."""
        ride = self._get_ongoing_ride(ride_id)
        base_fare = self._pricing.calculate_fare(ride)

        coupon = self._valid_coupon(ride.coupon_code) if ride.coupon_code else None
        if coupon is None:
            ride.coupon_code = None
        discount = coupon.discount_for(base_fare) if coupon else 0.0
        fare = FareBreakdown(base_fare=base_fare, discount=discount, total=round(base_fare - discount, 2))

        ride.complete(fare.total)
        driver = self._get_driver(ride.driver_id)
        driver.location = ride.drop
        driver.is_available = True
        return fare

    # History (oldest booking first; status=None returns every ride)

    def user_history(self, user_id: str, status: Optional[RideStatus] = None) -> List[Ride]:
        self._get_user(user_id)
        return self._rides_where(lambda ride: ride.user_id == user_id, status)

    def driver_history(self, driver_id: str, status: Optional[RideStatus] = None) -> List[Ride]:
        self._get_driver(driver_id)
        return self._rides_where(lambda ride: ride.driver_id == driver_id, status)

    # Coupons

    def add_coupon(self, coupon: Coupon) -> None:
        if coupon.code in self._coupons:
            raise InvalidOperationError(f"Coupon {coupon.code} already exists")
        self._coupons[coupon.code] = coupon

    def delete_coupon(self, code: str) -> None:
        if self._coupons.pop(code, None) is None:
            raise NotFoundError(f"Coupon {code} not found")

    def apply_coupon(self, ride_id: str, code: str) -> Ride:
        ride = self._get_ongoing_ride(ride_id)
        if code not in self._coupons:
            raise InvalidCouponError(f"Coupon {code} does not exist")
        if self._valid_coupon(code) is None:
            raise InvalidCouponError(f"Coupon {code} has expired")
        ride.coupon_code = code
        return ride

    # Helpers

    def _find_driver(self, pickup: Location, car_type: CarType) -> Optional[Driver]:
        """Try each acceptable car type in order; the first type with a match wins."""
        for acceptable_type in self._car_type_fallbacks.get(car_type, (car_type,)):
            candidates = [
                d
                for d in self._drivers.values()
                if d.is_available
                and d.car_type is acceptable_type
                and d.location.distance_to(pickup) <= self._search_radius
            ]
            driver = self._matching.select_driver(candidates, pickup)
            if driver is not None:
                return driver
        return None

    def _rides_where(self, belongs: Callable[[Ride], bool], status: Optional[RideStatus]) -> List[Ride]:
        return [r for r in self._rides.values() if belongs(r) and (status is None or r.status is status)]

    def _valid_coupon(self, code: str) -> Optional[Coupon]:
        coupon = self._coupons.get(code)
        if coupon is None or coupon.is_expired(self._clock()):
            return None
        return coupon

    def _get_user(self, user_id: str) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    def _get_driver(self, driver_id: str) -> Driver:
        driver = self._drivers.get(driver_id)
        if driver is None:
            raise NotFoundError(f"Driver {driver_id} not found")
        return driver

    def _get_ongoing_ride(self, ride_id: str) -> Ride:
        ride = self._rides.get(ride_id)
        if ride is None:
            raise NotFoundError(f"Ride {ride_id} not found")
        if ride.status is not RideStatus.ONGOING:
            raise InvalidOperationError(f"Ride {ride_id} is already {ride.status.value}")
        return ride
