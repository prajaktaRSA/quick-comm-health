"""Fare calculation strategies.

The service depends only on PricingStrategy. Surge pricing is a new class
that wraps another PricingStrategy, and new rate tables are new constructor
arguments to TieredPricingStrategy; neither requires editing this file.

Money is Decimal throughout (see money.py). The ride's distance is the only
float input; it is converted to Decimal once, before any money arithmetic.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from models import CarType, Ride
from money import to_money


@dataclass(frozen=True)
class Tier:
    up_to_km: float
    rate_per_km: Decimal


DEFAULT_TIERS: Sequence[Tier] = (
    Tier(up_to_km=2, rate_per_km=Decimal("10")),
    Tier(up_to_km=5, rate_per_km=Decimal("8")),
    Tier(up_to_km=math.inf, rate_per_km=Decimal("5")),
)

DEFAULT_CAR_TYPE_MULTIPLIERS: Mapping[CarType, Decimal] = {
    CarType.SEDAN: Decimal("1"),
    CarType.HATCHBACK: Decimal("0.8"),
}


class PricingStrategy(ABC):
    @abstractmethod
    def calculate_fare(self, ride: Ride) -> Decimal:
        """Return the fare before coupons, rounded to the paisa."""


class TieredPricingStrategy(PricingStrategy):
    """Charges each distance slab at its own rate, applies the multiplier for
    the *requested* car type, then enforces the minimum fare.

    Using the requested type is what charges an upgraded hatchback booking
    the hatchback price.
    """

    def __init__(
        self,
        tiers: Sequence[Tier] = DEFAULT_TIERS,
        minimum_fare: Decimal = Decimal("50"),
        car_type_multipliers: Mapping[CarType, Decimal] = DEFAULT_CAR_TYPE_MULTIPLIERS,
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

    def calculate_fare(self, ride: Ride) -> Decimal:
        distance = Decimal(str(ride.distance))
        fare = self._distance_cost(distance) * self._multipliers[ride.requested_car_type]
        return to_money(max(fare, self._minimum_fare))

    def _distance_cost(self, distance: Decimal) -> Decimal:
        cost = Decimal("0")
        lower = Decimal("0")
        for tier in self._tiers:
            if distance <= lower:
                break
            upper = Decimal(str(tier.up_to_km))  # math.inf becomes Decimal("Infinity")
            cost += (min(distance, upper) - lower) * tier.rate_per_km
            lower = upper
        return cost
