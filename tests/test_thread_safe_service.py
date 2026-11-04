import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional, Sequence, TypeVar

import pytest

import service as service_module
from cancellation import FlatCancellationFee
from matching import NearestDriverStrategy
from models import CarType, Driver, Location, Ride, RideStatus
from pricing import TieredPricingStrategy
from service import InvalidOperationError, NoDriverAvailableError, RideService
from thread_safe_service import ThreadSafeRideService

T = TypeVar("T")
THREADS = 20


class SlowNearestDriverStrategy(NearestDriverStrategy):
    """Widens the gap between checking availability and taking the driver, so
    an unsynchronised service reliably double-books (it books all 20)."""

    def select_driver(self, candidates: Sequence[Driver], pickup: Location) -> Optional[Driver]:
        time.sleep(0.01)
        return super().select_driver(candidates, pickup)


def make_service() -> ThreadSafeRideService:
    return ThreadSafeRideService(pricing=TieredPricingStrategy(), matching=SlowNearestDriverStrategy())


def run_together(task: Callable[[int], T], count: int = THREADS) -> List[T]:
    """Run task(0..count-1) on separate threads, all released at the same moment."""
    barrier = threading.Barrier(count)

    def start(i: int) -> T:
        barrier.wait()
        return task(i)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(start, range(count)))


def test_one_driver_is_booked_exactly_once_under_concurrent_requests() -> None:
    service = make_service()
    user_ids = [service.register_user(f"user{i}").id for i in range(THREADS)]
    driver = service.register_driver("Only", CarType.SEDAN, Location(1, 0), rating=5)

    def book(i: int) -> Optional[str]:
        try:
            return service.book_ride(user_ids[i], Location(0, 0), Location(5, 0), CarType.SEDAN).id
        except NoDriverAvailableError:
            return None

    booked = [ride_id for ride_id in run_together(book) if ride_id]

    assert booked == ["R1"]
    assert not driver.is_available
    assert len(service.driver_history(driver.id, RideStatus.ONGOING)) == 1


def test_concurrent_cancellations_charge_the_fee_once() -> None:
    class SlowFlatFee(FlatCancellationFee):
        def fee_for(self, ride: Ride) -> float:
            time.sleep(0.01)
            return super().fee_for(ride)

    service = ThreadSafeRideService(
        pricing=TieredPricingStrategy(), matching=NearestDriverStrategy(), cancellation_policy=SlowFlatFee()
    )
    user = service.register_user("Asha")
    service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=5)
    ride = service.book_ride(user.id, Location(0, 0), Location(5, 0), CarType.SEDAN)

    def cancel(i: int) -> str:
        try:
            return f"fee {service.cancel_ride(ride.id)}"
        except InvalidOperationError:
            return "rejected"

    outcomes = run_together(cancel)

    assert outcomes.count("fee 20.0") == 1
    assert outcomes.count("rejected") == THREADS - 1


def test_concurrent_end_ride_charges_once() -> None:
    class SlowTieredPricing(TieredPricingStrategy):
        def calculate_fare(self, ride: Ride) -> float:
            time.sleep(0.01)
            return super().calculate_fare(ride)

    service = ThreadSafeRideService(pricing=SlowTieredPricing(), matching=NearestDriverStrategy())
    user = service.register_user("Asha")
    driver = service.register_driver("Ravi", CarType.SEDAN, Location(1, 0), rating=5)
    ride = service.book_ride(user.id, Location(0, 0), Location(10, 0), CarType.SEDAN)

    def end(i: int) -> str:
        try:
            return f"fare {service.end_ride(ride.id).total}"
        except InvalidOperationError:
            return "rejected"

    outcomes = run_together(end)

    assert outcomes.count("fare 69.0") == 1
    assert outcomes.count("rejected") == THREADS - 1
    assert ride.status is RideStatus.COMPLETED
    assert driver.is_available


def slowed(model: type) -> type:
    """Subclass of a model whose construction is slow. RideService picks the
    next id before constructing the model and stores it after, so this widens
    the window in which two unsynchronised registrations get the same id."""

    class Slow(model):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            time.sleep(0.01)
            super().__init__(*args, **kwargs)

    return Slow


@pytest.mark.parametrize(
    "model_name, prefix, register",
    [
        ("User", "U", lambda service, i: service.register_user(f"user{i}")),
        ("Driver", "D", lambda service, i: service.register_driver(f"driver{i}", CarType.SEDAN, Location(0, 0), 4)),
    ],
    ids=["users", "drivers"],
)
def test_concurrent_registrations_get_unique_ids(
    monkeypatch: pytest.MonkeyPatch, model_name: str, prefix: str, register: Callable[[RideService, int], Any]
) -> None:
    monkeypatch.setattr(service_module, model_name, slowed(getattr(service_module, model_name)))
    service = make_service()

    ids = run_together(lambda i: register(service, i).id)

    assert sorted(ids, key=lambda id_: int(id_[1:])) == [f"{prefix}{i}" for i in range(1, THREADS + 1)]


def test_is_a_drop_in_replacement_for_ride_service() -> None:
    service = make_service()
    assert isinstance(service, RideService)

    user = service.register_user("Asha")
    service.register_driver("Ravi", CarType.HATCHBACK, Location(1, 0), rating=4.5)
    ride = service.book_ride(user.id, Location(0, 0), Location(10, 0), CarType.HATCHBACK)

    assert service.end_ride(ride.id).total == 55.2
    assert [r.id for r in service.user_history(user.id, RideStatus.COMPLETED)] == ["R1"]
