import pytest

from models import CarType, Location
from service import NotFoundError, RideService


@pytest.fixture
def service() -> RideService:
    return RideService()


class TestRegistration:
    def test_users_get_sequential_ids(self, service: RideService) -> None:
        assert [service.register_user(name).id for name in ("Asha", "Rohan")] == ["U1", "U2"]

    def test_driver_is_registered_available_with_given_details(self, service: RideService) -> None:
        driver = service.register_driver("Ravi", CarType.SEDAN, Location(1, 2), rating=4.8)
        assert driver.id == "D1"
        assert driver.car_type is CarType.SEDAN
        assert driver.location == Location(1, 2)
        assert driver.rating == 4.8
        assert driver.is_available

    def test_user_and_driver_ids_are_independent(self, service: RideService) -> None:
        service.register_user("Asha")
        assert service.register_driver("Ravi", CarType.SEDAN, Location(0, 0), rating=5).id == "D1"

    def test_invalid_rating_is_rejected_without_using_an_id(self, service: RideService) -> None:
        with pytest.raises(ValueError, match="rating"):
            service.register_driver("Bad", CarType.SEDAN, Location(0, 0), rating=7)
        assert service.register_driver("Good", CarType.SEDAN, Location(0, 0), rating=4).id == "D1"


class TestDriverLocation:
    def test_update_moves_registered_driver(self, service: RideService) -> None:
        driver = service.register_driver("Ravi", CarType.HATCHBACK, Location(0, 0), rating=4.5)
        updated = service.update_driver_location(driver.id, Location(3, 4))
        assert updated is driver
        assert driver.location == Location(3, 4)

    def test_unknown_driver_raises_not_found(self, service: RideService) -> None:
        with pytest.raises(NotFoundError, match="D99"):
            service.update_driver_location("D99", Location(0, 0))
