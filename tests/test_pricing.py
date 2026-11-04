import math
from decimal import Decimal
from typing import Optional

import pytest

from models import CarType, Location, Ride
from pricing import Tier, TieredPricingStrategy

SEDAN = CarType.SEDAN
HATCHBACK = CarType.HATCHBACK


def make_ride(distance_km: float, requested: CarType, assigned: Optional[CarType] = None) -> Ride:
    return Ride(
        id="R1",
        user_id="U1",
        driver_id="D1",
        pickup=Location(0, 0),
        drop=Location(distance_km, 0),
        requested_car_type=requested,
        assigned_car_type=assigned or requested,
    )


@pytest.fixture
def pricing() -> TieredPricingStrategy:
    return TieredPricingStrategy()


class TestTiers:
    @pytest.mark.parametrize(
        "distance_km, expected",
        [
            (1, "10.00"),   # inside tier 1
            (2, "20.00"),   # tier 1 boundary
            (3, "28.00"),   # 20 + 1 * 8
            (5, "44.00"),   # tier 2 boundary: 20 + 24
            (6, "49.00"),   # 44 + 1 * 5
        ],
    )
    def test_slab_rates_without_minimum(self, distance_km: float, expected: str) -> None:
        no_minimum = TieredPricingStrategy(minimum_fare=Decimal("0"))
        assert no_minimum.calculate_fare(make_ride(distance_km, SEDAN)) == Decimal(expected)

    @pytest.mark.parametrize(
        "distance_km, expected",
        [(7, "54.00"), (7.35, "55.75"), (10, "69.00"), (12.5, "81.50"), (20, "119.00")],
    )
    def test_sedan_fares_above_minimum(self, pricing: TieredPricingStrategy, distance_km: float, expected: str) -> None:
        assert pricing.calculate_fare(make_ride(distance_km, SEDAN)) == Decimal(expected)

    def test_uses_euclidean_distance(self, pricing: TieredPricingStrategy) -> None:
        ride = Ride("R1", "U1", "D1", Location(0, 0), Location(6, 8), SEDAN, SEDAN)  # 10 km
        assert pricing.calculate_fare(ride) == Decimal("69.00")


class TestMinimumFare:
    @pytest.mark.parametrize("distance_km", [0, 2, 5, 6])
    def test_short_sedan_rides_pay_minimum(self, pricing: TieredPricingStrategy, distance_km: float) -> None:
        assert pricing.calculate_fare(make_ride(distance_km, SEDAN)) == Decimal("50.00")

    def test_hatchback_discount_never_goes_below_minimum(self, pricing: TieredPricingStrategy) -> None:
        # 8 km sedan = 59; 20% off would be 47.20
        assert pricing.calculate_fare(make_ride(8, HATCHBACK)) == Decimal("50.00")


class TestCarTypeRates:
    @pytest.mark.parametrize("distance_km, expected", [(10, "55.20"), (20, "95.20")])
    def test_hatchback_is_twenty_percent_cheaper(
        self, pricing: TieredPricingStrategy, distance_km: float, expected: str
    ) -> None:
        sedan = pricing.calculate_fare(make_ride(distance_km, SEDAN))
        hatchback = pricing.calculate_fare(make_ride(distance_km, HATCHBACK))
        assert hatchback == Decimal(expected)
        assert hatchback == sedan * Decimal("0.8")


class TestFreeUpgrade:
    def test_upgraded_ride_pays_hatchback_price(self, pricing: TieredPricingStrategy) -> None:
        upgraded = make_ride(10, requested=HATCHBACK, assigned=SEDAN)
        assert upgraded.is_upgraded
        assert pricing.calculate_fare(upgraded) == Decimal("55.20")
        assert pricing.calculate_fare(upgraded) < pricing.calculate_fare(make_ride(10, SEDAN))


class TestMoney:
    def test_fares_are_decimal_rounded_to_the_paisa(self, pricing: TieredPricingStrategy) -> None:
        fare = pricing.calculate_fare(make_ride(10, HATCHBACK))
        assert isinstance(fare, Decimal)
        assert fare.as_tuple().exponent == -2

    def test_half_paisa_rounds_up(self) -> None:
        # 1.0005 km at Rs 10/km = Rs 10.005; half-up gives 10.01 (round-half-even would give 10.00)
        no_minimum = TieredPricingStrategy(minimum_fare=Decimal("0"))
        assert no_minimum.calculate_fare(make_ride(1.0005, SEDAN)) == Decimal("10.01")


class TestConfiguration:
    def test_custom_tiers_and_rates(self) -> None:
        flat = TieredPricingStrategy(
            tiers=[Tier(math.inf, Decimal("12"))],
            minimum_fare=Decimal("0"),
            car_type_multipliers={SEDAN: Decimal("1.5"), HATCHBACK: Decimal("1")},
        )
        assert flat.calculate_fare(make_ride(10, SEDAN)) == Decimal("180.00")

    @pytest.mark.parametrize(
        "tiers",
        [
            [],
            [Tier(5, Decimal("8")), Tier(2, Decimal("10")), Tier(math.inf, Decimal("5"))],
            [Tier(2, Decimal("10")), Tier(5, Decimal("8"))],
        ],
        ids=["empty", "not-ascending", "no-open-ended-tier"],
    )
    def test_rejects_invalid_tiers(self, tiers: list) -> None:
        with pytest.raises(ValueError, match="tiers"):
            TieredPricingStrategy(tiers=tiers)

    def test_rejects_missing_car_type_multiplier(self) -> None:
        with pytest.raises(ValueError, match="hatchback"):
            TieredPricingStrategy(car_type_multipliers={SEDAN: Decimal("1")})
