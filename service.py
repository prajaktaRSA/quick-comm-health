"""RideService: the application layer that ties models, storage and strategies.

Pricing and matching are injected through the constructor and can be swapped
at runtime with set_pricing_strategy / set_matching_strategy. The car-type
upgrade rule is data (car_type_fallbacks), so new car types or upgrade paths
are configuration, not code changes.
"""

from __future__ import annotations

from itertools import count
from typing import Dict, Iterator, List, Mapping, Optional, Sequence

from matching import MatchingStrategy
from models import Car, CarType, Coupon, Driver, Location, Ride, RideStatus, User
from pricing import FareBreakdown, PricingStrategy
from repository import InMemoryRepository

DEFAULT_CAR_TYPE_FALLBACKS: Mapping[CarType, Sequence[CarType]] = {
    CarType.HATCHBACK: (CarType.HATCHBACK, CarType.SEDAN),
    CarType.SEDAN: (CarType.SEDAN,),
}


class RideServiceError(Exception):
    """Base class for errors the CLI shows to the user."""


class NotFoundError(RideServiceError):
    pass


class NoDriverAvailableError(RideServiceError):
    pass


class InvalidOperationError(RideServiceError):
    pass


class RideService:
    def __init__(
        self,
        pricing: PricingStrategy,
        matching: MatchingStrategy,
        search_radius: float = 5.0,
        car_type_fallbacks: Mapping[CarType, Sequence[CarType]] = DEFAULT_CAR_TYPE_FALLBACKS,
    ) -> None:
        if search_radius <= 0:
            raise ValueError("search_radius must be positive")
        self._pricing = pricing
        self._matching = matching
        self._search_radius = search_radius
        self._car_type_fallbacks = dict(car_type_fallbacks)
        self._users: InMemoryRepository[User] = InMemoryRepository()
        self._drivers: InMemoryRepository[Driver] = InMemoryRepository()
        self._rides: InMemoryRepository[Ride] = InMemoryRepository()
        self._coupons: InMemoryRepository[Coupon] = InMemoryRepository()
        self._id_counters: Dict[str, Iterator[int]] = {}

    # Strategy swapping

    def set_pricing_strategy(self, pricing: PricingStrategy) -> None:
        self._pricing = pricing

    def set_matching_strategy(self, matching: MatchingStrategy) -> None:
        self._matching = matching

    # Users and drivers

    def register_user(self, name: str) -> User:
        user = User(id=self._next_id("U"), name=name)
        self._users.add(user.id, user)
        return user

    def register_driver(self, name: str, car: Car, location: Location) -> Driver:
        driver = Driver(id=self._next_id("D"), name=name, car=car, location=location)
        self._drivers.add(driver.id, driver)
        return driver

    def update_driver_location(self, driver_id: str, location: Location) -> Driver:
        driver = self._get_driver(driver_id)
        driver.location = location
        return driver

    def list_drivers(self) -> List[Driver]:
        return self._drivers.all()

    # Rides

    def book_ride(self, user_id: str, pickup: Location, drop: Location, car_type: CarType) -> Ride:
        self._get_user(user_id)
        if any(r.user_id == user_id and r.status is RideStatus.BOOKED for r in self._rides.all()):
            raise InvalidOperationError(f"User {user_id} already has an active ride")

        driver = self._find_driver(pickup, car_type)
        if driver is None:
            raise NoDriverAvailableError(
                f"No {car_type.value} (or upgrade) available within {self._search_radius} km"
            )

        driver.is_available = False
        ride = Ride(
            id=self._next_id("R"),
            user_id=user_id,
            driver_id=driver.id,
            pickup=pickup,
            drop=drop,
            requested_car_type=car_type,
            assigned_car_type=driver.car.car_type,
        )
        self._rides.add(ride.id, ride)
        return ride

    def end_ride(self, ride_id: str) -> FareBreakdown:
        ride = self._get_active_ride(ride_id)
        base_fare = self._pricing.calculate_fare(ride)
        coupon = self._coupons.get(ride.coupon_code) if ride.coupon_code else None
        discount = round(coupon.discount_for(base_fare), 2) if coupon else 0.0
        breakdown = FareBreakdown(base_fare=base_fare, discount=discount, total=round(base_fare - discount, 2))

        ride.complete(breakdown.total)
        driver = self._get_driver(ride.driver_id)
        driver.location = ride.drop
        driver.is_available = True
        return breakdown

    def ride_history(self, user_id: str) -> List[Ride]:
        self._get_user(user_id)
        rides = [r for r in self._rides.all() if r.user_id == user_id]
        return sorted(rides, key=lambda r: r.created_at)

    # Coupons

    def add_coupon(self, coupon: Coupon) -> None:
        if coupon.code in self._coupons:
            raise InvalidOperationError(f"Coupon {coupon.code} already exists")
        self._coupons.add(coupon.code, coupon)

    def delete_coupon(self, code: str) -> None:
        if self._coupons.remove(code) is None:
            raise NotFoundError(f"Coupon {code} not found")

    def apply_coupon(self, ride_id: str, code: str) -> Ride:
        ride = self._get_active_ride(ride_id)
        if code not in self._coupons:
            raise NotFoundError(f"Coupon {code} not found")
        ride.coupon_code = code
        return ride

    # Helpers

    def _find_driver(self, pickup: Location, car_type: CarType) -> Optional[Driver]:
        for acceptable_type in self._car_type_fallbacks.get(car_type, (car_type,)):
            candidates = [
                d
                for d in self._drivers.all()
                if d.is_available
                and d.car.car_type is acceptable_type
                and d.location.distance_to(pickup) <= self._search_radius
            ]
            driver = self._matching.select_driver(candidates, pickup)
            if driver is not None:
                return driver
        return None

    def _next_id(self, prefix: str) -> str:
        counter = self._id_counters.setdefault(prefix, count(1))
        return f"{prefix}{next(counter)}"

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

    def _get_active_ride(self, ride_id: str) -> Ride:
        ride = self._rides.get(ride_id)
        if ride is None:
            raise NotFoundError(f"Ride {ride_id} not found")
        if ride.status is not RideStatus.BOOKED:
            raise InvalidOperationError(f"Ride {ride_id} is already {ride.status.value}")
        return ride
