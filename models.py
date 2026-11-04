"""Domain models for the ride-hailing service.

Models hold state and guard their own invariants. Anything that can vary
(how fares are priced, how drivers are matched) lives in strategies that
operate on these models, so new behaviour is added without editing them.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class CarType(Enum):
    HATCHBACK = "hatchback"
    SEDAN = "sedan"


class RideStatus(Enum):
    BOOKED = "booked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Location:
    x: float
    y: float

    def distance_to(self, other: Location) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class User:
    id: str
    name: str


@dataclass(frozen=True)
class Car:
    number: str
    car_type: CarType


@dataclass
class Driver:
    id: str
    name: str
    car: Car
    location: Location
    rating: float = 5.0
    is_available: bool = True


@dataclass
class Ride:
    id: str
    user_id: str
    driver_id: str
    pickup: Location
    drop: Location
    requested_car_type: CarType
    assigned_car_type: CarType
    status: RideStatus = RideStatus.BOOKED
    coupon_code: Optional[str] = None
    fare: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None

    @property
    def distance(self) -> float:
        return self.pickup.distance_to(self.drop)

    @property
    def is_upgraded(self) -> bool:
        return self.requested_car_type != self.assigned_car_type

    def complete(self, fare: float) -> None:
        self._close(RideStatus.COMPLETED, fare)

    def cancel(self, fee: float) -> None:
        self._close(RideStatus.CANCELLED, fee)

    def _close(self, status: RideStatus, amount: float) -> None:
        if self.status is not RideStatus.BOOKED:
            raise ValueError(f"Ride {self.id} is already {self.status.value}")
        self.status = status
        self.fare = amount
        self.ended_at = datetime.now()


@dataclass
class Coupon(ABC):
    code: str

    @abstractmethod
    def discount_for(self, fare: float) -> float:
        """Return the amount to subtract from the fare."""


@dataclass
class FlatCoupon(Coupon):
    amount: float

    def discount_for(self, fare: float) -> float:
        return min(self.amount, fare)


@dataclass
class PercentageCoupon(Coupon):
    percent: float
    max_discount: Optional[float] = None

    def __post_init__(self) -> None:
        if not 0 < self.percent <= 100:
            raise ValueError("percent must be in (0, 100]")

    def discount_for(self, fare: float) -> float:
        discount = fare * self.percent / 100
        if self.max_discount is not None:
            discount = min(discount, self.max_discount)
        return min(discount, fare)
