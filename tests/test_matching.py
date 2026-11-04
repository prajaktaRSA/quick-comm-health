from models import CarType, Driver, Location
from matching import HighestRatedDriverStrategy, NearestDriverStrategy

PICKUP = Location(0, 0)


def make_driver(driver_id: str, x: float, y: float, rating: float = 4.5) -> Driver:
    return Driver(driver_id, driver_id, CarType.SEDAN, Location(x, y), rating=rating)


class TestNearestDriverStrategy:
    def test_picks_closest_driver(self) -> None:
        drivers = [make_driver("D1", 4, 0), make_driver("D2", 1, 1), make_driver("D3", 0, 3)]
        assert NearestDriverStrategy().select_driver(drivers, PICKUP).id == "D2"

    def test_ignores_rating(self) -> None:
        drivers = [make_driver("D1", 4, 0, rating=5.0), make_driver("D2", 1, 0, rating=3.0)]
        assert NearestDriverStrategy().select_driver(drivers, PICKUP).id == "D2"

    def test_tie_goes_to_first_candidate(self) -> None:
        drivers = [make_driver("D1", 3, 0), make_driver("D2", 0, 3)]
        assert NearestDriverStrategy().select_driver(drivers, PICKUP).id == "D1"

    def test_no_candidates_returns_none(self) -> None:
        assert NearestDriverStrategy().select_driver([], PICKUP) is None


class TestHighestRatedDriverStrategy:
    def test_picks_best_rated_even_if_farther(self) -> None:
        drivers = [make_driver("D1", 1, 0, rating=3.9), make_driver("D2", 4, 0, rating=4.9), make_driver("D3", 2, 0, rating=4.2)]
        assert HighestRatedDriverStrategy().select_driver(drivers, PICKUP).id == "D2"

    def test_equal_rating_goes_to_nearest(self) -> None:
        drivers = [make_driver("D1", 4, 0, rating=4.8), make_driver("D2", 2, 0, rating=4.8)]
        assert HighestRatedDriverStrategy().select_driver(drivers, PICKUP).id == "D2"

    def test_equal_rating_and_distance_goes_to_first_candidate(self) -> None:
        drivers = [make_driver("D1", 3, 0, rating=4.8), make_driver("D2", 0, 3, rating=4.8)]
        assert HighestRatedDriverStrategy().select_driver(drivers, PICKUP).id == "D1"

    def test_no_candidates_returns_none(self) -> None:
        assert HighestRatedDriverStrategy().select_driver([], PICKUP) is None
