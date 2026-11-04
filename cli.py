"""Interactive CLI for the ride-hailing service.

build_service() is the composition root: the only place that chooses concrete
strategies. Bonus features (surge pricing, highest-rated matching) are wired
in here or swapped at runtime, without touching the service.

Run:  python cli.py        then type `help`, or `demo` for a scripted walkthrough.
"""

from __future__ import annotations

import cmd
from typing import List

from matching import NearestDriverStrategy
from models import Car, CarType, FlatCoupon, Location, PercentageCoupon, Ride
from pricing import TieredPricing
from service import RideService, RideServiceError

DEMO_SCRIPT = [
    "add_user Asha",
    "add_user Rohan",
    "add_driver Ravi MH12-1111 hatchback 1 1",
    "add_driver Sunil MH12-2222 sedan 2 2",
    "add_driver Meena MH12-3333 sedan 30 30",
    "drivers",
    "book U1 0 0 10 0 hatchback",
    "book U2 0 0 3 0 hatchback",
    "add_coupon SAVE20 percent 20 15",
    "apply_coupon R1 SAVE20",
    "end R1",
    "end R2",
    "end R1",
    "book U2 50 50 51 50 sedan",
    "move D3 50 51",
    "book U2 50 50 51 50 sedan",
    "end R3",
    "delete_coupon SAVE20",
    "history U1",
    "history U2",
]


def build_service() -> RideService:
    return RideService(pricing=TieredPricing(), matching=NearestDriverStrategy(), search_radius=5.0)


def _split(line: str, expected: int, usage: str) -> List[str]:
    args = line.split()
    if len(args) != expected:
        raise ValueError(f"usage: {usage}")
    return args


def _car_type(value: str) -> CarType:
    try:
        return CarType(value.lower())
    except ValueError:
        choices = ", ".join(c.value for c in CarType)
        raise ValueError(f"unknown car type {value!r} (choose from {choices})") from None


def _location(x: str, y: str) -> Location:
    return Location(float(x), float(y))


def _format_ride(ride: Ride) -> str:
    car = ride.requested_car_type.value
    if ride.is_upgraded:
        car += f" -> upgraded to {ride.assigned_car_type.value}"
    fare = f"Rs {ride.fare:.2f}" if ride.fare is not None else "-"
    coupon = f", coupon {ride.coupon_code}" if ride.coupon_code else ""
    return (
        f"{ride.id}: driver {ride.driver_id}, ({ride.pickup.x:g},{ride.pickup.y:g}) -> "
        f"({ride.drop.x:g},{ride.drop.y:g}), {ride.distance:.2f} km, {car}, "
        f"{ride.status.value}, fare {fare}{coupon}"
    )


class RideHailingCLI(cmd.Cmd):
    intro = "Ride hailing service. Type `help` for commands or `demo` for a walkthrough."
    prompt = "ride> "

    def __init__(self, service: RideService) -> None:
        super().__init__()
        self.service = service

    def onecmd(self, line: str) -> bool:
        try:
            return super().onecmd(line)
        except (RideServiceError, ValueError) as error:
            print(f"Error: {error}")
            return False

    def emptyline(self) -> bool:
        return False

    def do_add_user(self, line: str) -> None:
        """add_user NAME"""
        (name,) = _split(line, 1, "add_user NAME")
        user = self.service.register_user(name)
        print(f"Registered user {user.id} ({user.name})")

    def do_add_driver(self, line: str) -> None:
        """add_driver NAME CAR_NUMBER hatchback|sedan X Y"""
        name, number, car_type, x, y = _split(line, 5, "add_driver NAME CAR_NUMBER hatchback|sedan X Y")
        driver = self.service.register_driver(name, Car(number, _car_type(car_type)), _location(x, y))
        print(f"Registered driver {driver.id} ({driver.name}, {driver.car.car_type.value}) at ({x}, {y})")

    def do_move(self, line: str) -> None:
        """move DRIVER_ID X Y  - update a driver's location"""
        driver_id, x, y = _split(line, 3, "move DRIVER_ID X Y")
        driver = self.service.update_driver_location(driver_id, _location(x, y))
        print(f"Driver {driver.id} is now at ({x}, {y})")

    def do_drivers(self, line: str) -> None:
        """drivers  - list all drivers"""
        for d in self.service.list_drivers():
            status = "available" if d.is_available else "on a ride"
            print(f"{d.id}: {d.name}, {d.car.car_type.value} {d.car.number}, "
                  f"at ({d.location.x:g},{d.location.y:g}), rating {d.rating}, {status}")

    def do_book(self, line: str) -> None:
        """book USER_ID PICKUP_X PICKUP_Y DROP_X DROP_Y hatchback|sedan"""
        user_id, px, py, dx, dy, car_type = _split(
            line, 6, "book USER_ID PICKUP_X PICKUP_Y DROP_X DROP_Y hatchback|sedan"
        )
        ride = self.service.book_ride(user_id, _location(px, py), _location(dx, dy), _car_type(car_type))
        print(f"Booked {_format_ride(ride)}")

    def do_end(self, line: str) -> None:
        """end RIDE_ID  - finish a ride and show the fare"""
        (ride_id,) = _split(line, 1, "end RIDE_ID")
        fare = self.service.end_ride(ride_id)
        print(f"Ride {ride_id} completed. Base Rs {fare.base_fare:.2f}, "
              f"discount Rs {fare.discount:.2f}, total Rs {fare.total:.2f}")

    def do_history(self, line: str) -> None:
        """history USER_ID"""
        (user_id,) = _split(line, 1, "history USER_ID")
        rides = self.service.ride_history(user_id)
        if not rides:
            print(f"No rides for {user_id}")
        for ride in rides:
            print(_format_ride(ride))

    def do_add_coupon(self, line: str) -> None:
        """add_coupon CODE flat AMOUNT  |  add_coupon CODE percent PERCENT [MAX_DISCOUNT]"""
        args = line.split()
        if len(args) == 3 and args[1] == "flat":
            coupon = FlatCoupon(args[0], float(args[2]))
        elif len(args) in (3, 4) and args[1] == "percent":
            max_discount = float(args[3]) if len(args) == 4 else None
            coupon = PercentageCoupon(args[0], float(args[2]), max_discount)
        else:
            raise ValueError("usage: add_coupon CODE flat AMOUNT | add_coupon CODE percent PERCENT [MAX]")
        self.service.add_coupon(coupon)
        print(f"Added coupon {coupon.code}")

    def do_delete_coupon(self, line: str) -> None:
        """delete_coupon CODE"""
        (code,) = _split(line, 1, "delete_coupon CODE")
        self.service.delete_coupon(code)
        print(f"Deleted coupon {code}")

    def do_apply_coupon(self, line: str) -> None:
        """apply_coupon RIDE_ID CODE  - applied when the ride ends"""
        ride_id, code = _split(line, 2, "apply_coupon RIDE_ID CODE")
        self.service.apply_coupon(ride_id, code)
        print(f"Coupon {code} applied to {ride_id}")

    def do_demo(self, line: str) -> None:
        """demo  - run a scripted walkthrough on a fresh service"""
        demo_cli = RideHailingCLI(build_service())
        for command in DEMO_SCRIPT:
            print(f"\nride> {command}")
            demo_cli.onecmd(command)

    def do_quit(self, line: str) -> bool:
        """quit  - exit"""
        return True

    do_exit = do_quit
    do_EOF = do_quit


if __name__ == "__main__":
    RideHailingCLI(build_service()).cmdloop()
