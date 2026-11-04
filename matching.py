"""Driver matching strategies.

RideService does the filtering every strategy shares (available, within the
search radius, acceptable car type) and hands the survivors to a
MatchingStrategy, which only decides *which* of them to pick. Highest-rated
or least-busy matching is a new subclass injected into the service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from models import Driver, Location


class MatchingStrategy(ABC):
    @abstractmethod
    def select_driver(self, candidates: Sequence[Driver], pickup: Location) -> Optional[Driver]:
        """Pick one driver from eligible candidates, or None if there are none."""


class NearestDriverStrategy(MatchingStrategy):
    def select_driver(self, candidates: Sequence[Driver], pickup: Location) -> Optional[Driver]:
        return min(candidates, key=lambda driver: driver.location.distance_to(pickup), default=None)
