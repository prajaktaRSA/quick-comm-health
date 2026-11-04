from models import CarType, Driver, Location
from matching import NearestDriverStrategy


def make_driver(driver_id: str, x: float, y: float) -> Driver:
    return Driver(driver_id, driver_id, CarType.SEDAN, Location(x, y), rating=4.5)


class TestNearestDriverStrategy:
    def test_picks_closest_driver(self) -> None:
        drivers = [make_driver("D1", 4, 0), make_driver("D2", 1, 1), make_driver("D3", 0, 3)]
        assert NearestDriverStrategy().select_driver(drivers, Location(0, 0)).id == "D2"

    def test_tie_goes_to_first_candidate(self) -> None:
        drivers = [make_driver("D1", 3, 0), make_driver("D2", 0, 3)]
        assert NearestDriverStrategy().select_driver(drivers, Location(0, 0)).id == "D1"

    def test_no_candidates_returns_none(self) -> None:
        assert NearestDriverStrategy().select_driver([], Location(0, 0)) is None
