"""RideService: the application layer over in-memory storage.

Storage is plain dicts keyed by id. Records are never deleted, so ids are
the next number in each dict with a prefix (U1, D1, R1), which keeps them
short for the CLI and leaves no gaps when a registration fails validation.

Pricing, matching and cancellation-fee strategies are injected, so new rules
need no edits here. The clock is injected so coupon expiry can be tested.

Every public method runs under one lock (@_synchronized), so the service is
safe to share between threads: two users can never book the same driver.
"""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, TypeVar

from cancellation import CancellationFeePolicy, FlatCancellationFee
from matching import MatchingStrategy
from models import CarType, Coupon, Driver, Location, Ride, RideStatus, User
from pricing import PricingStrategy

# Car types tried, in order, for each requested type: a hatchback request is
# upgraded to a sedan when no hatchback is free; a sedan is never downgraded.
CAR_TYPE_FALLBACKS: Mapping[CarType, Sequence[CarType]] = {
    CarType.HATCHBACK: (CarType.HATCHBACK, CarType.SEDAN),
    CarType.SEDAN: (CarType.SEDAN,),
}

F = TypeVar("F", bound=Callable[..., Any])


def _synchronized(method: F) -> F:
    """Run the method while holding the service's lock, so each public
    operation is atomic with respect to every other."""

    @functools.wraps(method)
    def wrapper(self: RideService, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


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
    base_fare: Decimal
    discount: Decimal
    total: Decimal


class RideService:
    def __init__(
        self,
        pricing: PricingStrategy,
        matching: MatchingStrategy,
        search_radius: float = 5.0,
        clock: Callable[[], datetime] = datetime.now,
        cancellation_policy: CancellationFeePolicy = FlatCancellationFee(),
    ) -> None:
        if search_radius <= 0:
            raise ValueError("search_radius must be positive")
        self._pricing = pricing
        self._matching = matching
        self._search_radius = search_radius
        self._clock = clock
        self._cancellation_policy = cancellation_policy
        self._lock = threading.Lock()
        self._users: Dict[str, User] = {}
        self._drivers: Dict[str, Driver] = {}
        self._rides: Dict[str, Ride] = {}
        self._coupons: Dict[str, Coupon] = {}

    # Users and drivers

    @_synchronized
    def register_user(self, name: str) -> User:
        user = User(id=f"U{len(self._users) + 1}", name=name)
        self._users[user.id] = user
        return user

    @_synchronized
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

    @_synchronized
    def update_driver_location(self, driver_id: str, location: Location) -> Driver:
        driver = self._get_driver(driver_id)
        driver.location = location
        return driver

    # Rides

    @_synchronized
    def book_ride(
        self,
        user_id: str,
        pickup: Location,
        drop: Location,
        car_type: CarType,
        coupon_code: Optional[str] = None,
    ) -> Ride:
        """Book the best available driver. An optional coupon is validated
        before any driver is assigned, so an invalid coupon books nothing; its
        discount is taken when the ride ends."""
        self._get_user(user_id)
        if any(r.user_id == user_id and r.status is RideStatus.ONGOING for r in self._rides.values()):
            raise InvalidOperationError(f"User {user_id} already has an ongoing ride")
        if coupon_code is not None:
            self._check_coupon(coupon_code)

        driver = self._find_driver(pickup, car_type)
        if driver is None:
            raise NoDriverAvailableError(self._no_driver_message(pickup, car_type))

        driver.is_available = False
        ride = Ride(
            id=f"R{len(self._rides) + 1}",
            user_id=user_id,
            driver_id=driver.id,
            pickup=pickup,
            drop=drop,
            requested_car_type=car_type,
            assigned_car_type=driver.car_type,
            coupon_code=coupon_code,
        )
        self._rides[ride.id] = ride
        return ride

    @_synchronized
    def end_ride(self, ride_id: str) -> FareBreakdown:
        """Complete the ride and charge it. A coupon that was deleted or expired
        since booking is dropped rather than blocking the ride from ending."""
        ride = self._get_ongoing_ride(ride_id)
        base_fare = self._pricing.calculate_fare(ride)

        coupon = self._valid_coupon(ride.coupon_code) if ride.coupon_code else None
        if coupon is None:
            ride.coupon_code = None
        discount = coupon.discount_for(base_fare) if coupon else Decimal("0.00")
        # Both amounts are already rounded to the paisa, so the difference is exact.
        fare = FareBreakdown(base_fare=base_fare, discount=discount, total=base_fare - discount)

        ride.complete(fare.total)
        driver = self._get_driver(ride.driver_id)
        driver.location = ride.drop
        driver.is_available = True
        return fare

    @_synchronized
    def cancel_ride(self, ride_id: str) -> Decimal:
        """Cancel an ongoing ride and return the fee charged. Coupons do not
        apply to cancellation fees. The driver is freed where they are."""
        ride = self._get_ongoing_ride(ride_id)
        fee = self._cancellation_policy.fee_for(ride)
        ride.cancel(fee)
        ride.coupon_code = None
        self._get_driver(ride.driver_id).is_available = True
        return fee

    # History (oldest booking first; status=None returns every ride)

    @_synchronized
    def user_history(self, user_id: str, status: Optional[RideStatus] = None) -> List[Ride]:
        self._get_user(user_id)
        return self._rides_where(lambda ride: ride.user_id == user_id, status)

    @_synchronized
    def driver_history(self, driver_id: str, status: Optional[RideStatus] = None) -> List[Ride]:
        self._get_driver(driver_id)
        return self._rides_where(lambda ride: ride.driver_id == driver_id, status)

    # Coupons

    @_synchronized
    def add_coupon(self, coupon: Coupon) -> None:
        if coupon.code in self._coupons:
            raise InvalidOperationError(f"Coupon {coupon.code} already exists")
        self._coupons[coupon.code] = coupon

    @_synchronized
    def delete_coupon(self, code: str) -> None:
        if self._coupons.pop(code, None) is None:
            raise NotFoundError(f"Coupon {code} not found")

    # Helpers (called with the lock already held)

    def _find_driver(self, pickup: Location, car_type: CarType) -> Optional[Driver]:
        """Try each acceptable car type in order; the first type with a match wins."""
        for acceptable_type in CAR_TYPE_FALLBACKS[car_type]:
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

    def _no_driver_message(self, pickup: Location, car_type: CarType) -> str:
        """Names every car type that was tried and how many of those drivers in
        range are busy, e.g. "No hatchback or sedan available within 5 km
        (2 nearby drivers are on rides)"."""
        acceptable_types = CAR_TYPE_FALLBACKS[car_type]
        busy = sum(
            1
            for d in self._drivers.values()
            if not d.is_available
            and d.car_type in acceptable_types
            and d.location.distance_to(pickup) <= self._search_radius
        )
        types = " or ".join(t.value for t in acceptable_types)
        message = f"No {types} available within {self._search_radius:g} km"
        if busy == 1:
            message += " (1 nearby driver is on a ride)"
        elif busy > 1:
            message += f" ({busy} nearby drivers are on rides)"
        return message

    def _rides_where(self, belongs: Callable[[Ride], bool], status: Optional[RideStatus]) -> List[Ride]:
        return [r for r in self._rides.values() if belongs(r) and (status is None or r.status is status)]

    def _check_coupon(self, code: str) -> None:
        if code not in self._coupons:
            raise InvalidCouponError(f"Coupon {code} does not exist")
        if self._valid_coupon(code) is None:
            raise InvalidCouponError(f"Coupon {code} has expired")

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
