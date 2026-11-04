import math
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
            (1, 10.0),   # inside tier 1
            (2, 20.0),   # tier 1 boundary
            (3, 28.0),   # 20 + 1 * 8
            (5, 44.0),   # tier 2 boundary: 20 + 24
            (6, 49.0),   # 44 + 1 * 5
        ],
    )
    def test_slab_rates_without_minimum(self, distance_km: float, expected: float) -> None:
        no_minimum = TieredPricingStrategy(minimum_fare=0)
        assert no_minimum.calculate_fare(make_ride(distance_km, SEDAN)) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "distance_km, expected",
        [(7, 54.0), (10, 69.0), (12.5, 81.5), (20, 119.0)],
    )
    def test_sedan_fares_above_minimum(self, pricing: TieredPricingStrategy, distance_km: float, expected: float) -> None:
        assert pricing.calculate_fare(make_ride(distance_km, SEDAN)) == pytest.approx(expected)

    def test_uses_euclidean_distance(self, pricing: TieredPricingStrategy) -> None:
        ride = Ride("R1", "U1", "D1", Location(0, 0), Location(6, 8), SEDAN, SEDAN)  # 10 km
        assert pricing.calculate_fare(ride) == pytest.approx(69.0)


class TestMinimumFare:
    @pytest.mark.parametrize("distance_km", [0, 2, 5, 6])
    def test_short_sedan_rides_pay_minimum(self, pricing: TieredPricingStrategy, distance_km: float) -> None:
        assert pricing.calculate_fare(make_ride(distance_km, SEDAN)) == pytest.approx(50.0)

    def test_hatchback_discount_never_goes_below_minimum(self, pricing: TieredPricingStrategy) -> None:
        # 8 km sedan = 59; 20% off would be 47.2
        assert pricing.calculate_fare(make_ride(8, HATCHBACK)) == pytest.approx(50.0)


class TestCarTypeRates:
    @pytest.mark.parametrize("distance_km, expected", [(10, 55.2), (20, 95.2)])
    def test_hatchback_is_twenty_percent_cheaper(self, pricing: TieredPricingStrategy, distance_km: float, expected: float) -> None:
        sedan = pricing.calculate_fare(make_ride(distance_km, SEDAN))
        hatchback = pricing.calculate_fare(make_ride(distance_km, HATCHBACK))
        assert hatchback == pytest.approx(expected)
        assert hatchback == pytest.approx(sedan * 0.8)


class TestFreeUpgrade:
    def test_upgraded_ride_pays_hatchback_price(self, pricing: TieredPricingStrategy) -> None:
        upgraded = make_ride(10, requested=HATCHBACK, assigned=SEDAN)
        assert upgraded.is_upgraded
        assert pricing.calculate_fare(upgraded) == pytest.approx(55.2)
        assert pricing.calculate_fare(upgraded) < pricing.calculate_fare(make_ride(10, SEDAN))


class TestConfiguration:
    def test_custom_tiers_and_rates(self) -> None:
        flat = TieredPricingStrategy(
            tiers=[Tier(math.inf, 12.0)],
            minimum_fare=0,
            car_type_multipliers={SEDAN: 1.5, HATCHBACK: 1.0},
        )
        assert flat.calculate_fare(make_ride(10, SEDAN)) == pytest.approx(180.0)

    @pytest.mark.parametrize(
        "tiers",
        [[], [Tier(5, 8.0), Tier(2, 10.0), Tier(math.inf, 5.0)], [Tier(2, 10.0), Tier(5, 8.0)]],
        ids=["empty", "not-ascending", "no-open-ended-tier"],
    )
    def test_rejects_invalid_tiers(self, tiers: list) -> None:
        with pytest.raises(ValueError, match="tiers"):
            TieredPricingStrategy(tiers=tiers)

    def test_rejects_missing_car_type_multiplier(self) -> None:
        with pytest.raises(ValueError, match="hatchback"):
            TieredPricingStrategy(car_type_multipliers={SEDAN: 1.0})
