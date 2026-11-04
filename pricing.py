"""Fare calculation strategies.

The service depends only on PricingStrategy. Surge pricing is a new class
that wraps another PricingStrategy, and new rate tables are new constructor
arguments to TieredPricingStrategy; neither requires editing this file.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Sequence

from models import CarType, Ride


@dataclass(frozen=True)
class Tier:
    up_to_km: float
    rate_per_km: float


DEFAULT_TIERS: Sequence[Tier] = (
    Tier(up_to_km=2, rate_per_km=10.0),
    Tier(up_to_km=5, rate_per_km=8.0),
    Tier(up_to_km=math.inf, rate_per_km=5.0),
)

DEFAULT_CAR_TYPE_MULTIPLIERS: Mapping[CarType, float] = {
    CarType.SEDAN: 1.0,
    CarType.HATCHBACK: 0.8,
}


class PricingStrategy(ABC):
    @abstractmethod
    def calculate_fare(self, ride: Ride) -> float:
        """Return the fare before coupons."""


class TieredPricingStrategy(PricingStrategy):
    """Charges each distance slab at its own rate, applies the multiplier for
    the *requested* car type, then enforces the minimum fare.

    Using the requested type is what charges an upgraded hatchback booking
    the hatchback price.
    """

    def __init__(
        self,
        tiers: Sequence[Tier] = DEFAULT_TIERS,
        minimum_fare: float = 50.0,
        car_type_multipliers: Mapping[CarType, float] = DEFAULT_CAR_TYPE_MULTIPLIERS,
    ) -> None:
        bounds = [tier.up_to_km for tier in tiers]
        if not bounds or bounds != sorted(bounds) or bounds[-1] != math.inf:
            raise ValueError("tiers must be ascending and end with math.inf")
        missing = set(CarType) - set(car_type_multipliers)
        if missing:
            raise ValueError(f"no multiplier for: {', '.join(sorted(c.value for c in missing))}")
        self._tiers = tuple(tiers)
        self._minimum_fare = minimum_fare
        self._multipliers = dict(car_type_multipliers)

    def calculate_fare(self, ride: Ride) -> float:
        fare = self._distance_cost(ride.distance) * self._multipliers[ride.requested_car_type]
        return round(max(fare, self._minimum_fare), 2)

    def _distance_cost(self, distance: float) -> float:
        cost = 0.0
        lower = 0.0
        for tier in self._tiers:
            if distance <= lower:
                break
            cost += (min(distance, tier.up_to_km) - lower) * tier.rate_per_km
            lower = tier.up_to_km
        return cost
