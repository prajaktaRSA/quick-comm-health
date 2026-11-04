"""Thread-safe RideService, added without editing RideService (Open/Closed).

RideService is not safe to share between threads: two bookings can both see
the same driver as available and both take them, two registrations can get
the same id, and reading history while a ride is booked can fail with
"dictionary changed size during iteration".

This subclass runs every public operation under one lock, so each is
atomic. It is a drop-in replacement: callers construct it with the same
arguments and use the same methods.
"""

from __future__ import annotations

import threading
from typing import Any, List, Optional

from models import CarType, Coupon, Driver, Location, Ride, RideStatus, User
from service import FareBreakdown, RideService


class ThreadSafeRideService(RideService):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()

    def register_user(self, name: str) -> User:
        with self._lock:
            return super().register_user(name)

    def register_driver(self, name: str, car_type: CarType, location: Location, rating: float) -> Driver:
        with self._lock:
            return super().register_driver(name, car_type, location, rating)

    def update_driver_location(self, driver_id: str, location: Location) -> Driver:
        with self._lock:
            return super().update_driver_location(driver_id, location)

    def book_ride(
        self,
        user_id: str,
        pickup: Location,
        drop: Location,
        car_type: CarType,
        coupon_code: Optional[str] = None,
    ) -> Ride:
        with self._lock:
            return super().book_ride(user_id, pickup, drop, car_type, coupon_code)

    def end_ride(self, ride_id: str) -> FareBreakdown:
        with self._lock:
            return super().end_ride(ride_id)

    def cancel_ride(self, ride_id: str) -> float:
        with self._lock:
            return super().cancel_ride(ride_id)

    def user_history(self, user_id: str, status: Optional[RideStatus] = None) -> List[Ride]:
        with self._lock:
            return super().user_history(user_id, status)

    def driver_history(self, driver_id: str, status: Optional[RideStatus] = None) -> List[Ride]:
        with self._lock:
            return super().driver_history(driver_id, status)

    def add_coupon(self, coupon: Coupon) -> None:
        with self._lock:
            super().add_coupon(coupon)

    def delete_coupon(self, code: str) -> None:
        with self._lock:
            super().delete_coupon(code)

    def apply_coupon(self, ride_id: str, code: str) -> Ride:
        with self._lock:
            return super().apply_coupon(ride_id, code)
