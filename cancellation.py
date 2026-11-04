"""Cancellation fee policies.

RideService depends only on CancellationFeePolicy. Free cancellation within
a grace period, or a fee based on how far the driver has travelled, are new
policy classes injected into the service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from models import Ride
from money import to_money


class CancellationFeePolicy(ABC):
    @abstractmethod
    def fee_for(self, ride: Ride) -> Decimal:
        """Return the fee charged for cancelling this ongoing ride."""


class FlatCancellationFee(CancellationFeePolicy):
    def __init__(self, amount: Decimal = Decimal("20")) -> None:
        if amount < 0:
            raise ValueError("cancellation fee must be non-negative")
        self._amount = to_money(amount)

    def fee_for(self, ride: Ride) -> Decimal:
        return self._amount
