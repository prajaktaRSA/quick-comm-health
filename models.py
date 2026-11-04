"""Domain models for the ride-hailing service.

Models hold state and guard their own invariants. Behaviour that varies
(pricing, matching) lives in strategies that read these models, so new
behaviour is added as new strategy classes rather than edits here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class CarType(Enum):
    HATCHBACK = "hatchback"
    SEDAN = "sedan"


class RideStatus(Enum):
    ONGOING = "ongoing"
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


@dataclass
class Driver:
    id: str
    name: str
    car_type: CarType
    location: Location
    rating: float
    is_available: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.rating <= 5:
            raise ValueError("rating must be between 0 and 5")


@dataclass
class Ride:
    id: str
    user_id: str
    driver_id: str
    pickup: Location
    drop: Location
    requested_car_type: CarType
    assigned_car_type: CarType
    status: RideStatus = RideStatus.ONGOING
    coupon_code: Optional[str] = None
    fare: Optional[float] = None

    @property
    def distance(self) -> float:
        return self.pickup.distance_to(self.drop)

    @property
    def is_upgraded(self) -> bool:
        return self.requested_car_type != self.assigned_car_type

    def complete(self, fare: float) -> None:
        if self.status is not RideStatus.ONGOING:
            raise ValueError(f"Ride {self.id} is already {self.status.value}")
        self.status = RideStatus.COMPLETED
        self.fare = fare


@dataclass(frozen=True)
class Coupon:
    code: str
    discount_percent: float
    expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not 0 < self.discount_percent <= 100:
            raise ValueError("discount_percent must be in (0, 100]")

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def discount_for(self, fare: float) -> float:
        return round(fare * self.discount_percent / 100, 2)
