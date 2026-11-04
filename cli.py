"""Interactive CLI for the ride-hailing service.

build_service() is the composition root: the only place that picks concrete
strategies and the service class. Swapping in surge pricing or highest-rated
matching is a change to this function only.

Run:  python cli.py    then type `help`, or `demo` for a scripted walkthrough.
"""

from __future__ import annotations

import cmd
from datetime import datetime
from typing import List, Optional

from matching import NearestDriverStrategy
from models import CarType, Coupon, Location, Ride, RideStatus
from pricing import TieredPricingStrategy
from service import RideService, RideServiceError
from thread_safe_service import ThreadSafeRideService

DEMO_SCRIPT = [
    "add_user Asha",
    "add_user Rohan",
    "add_user Meera",
    "add_driver Ravi hatchback 1 1 4.6",
    "add_driver Sunil sedan 2 2 4.9",
    "add_driver Kiran sedan 30 30 4.2",
    "book U1 0 0 10 0 hatchback",
    "book U2 0 0 3 0 hatchback",
    "add_coupon SAVE10 10",
    "add_coupon OLD20 20 2020-01-01",
    "apply_coupon R1 OLD20",
    "apply_coupon R1 NOPE",
    "apply_coupon R1 SAVE10",
    "end R1",
    "end R2",
    "book U3 50 50 51 50 sedan",
    "move D3 50 51",
    "book U3 50 50 51 50 sedan",
    "cancel R3",
    "end R3",
    "history user U1",
    "history user U2 completed",
    "history user U3 cancelled",
    "history driver D2",
    "delete_coupon SAVE10",
    "delete_coupon SAVE10",
]


def build_service() -> RideService:
    return ThreadSafeRideService(
        pricing=TieredPricingStrategy(),
        matching=NearestDriverStrategy(),
        search_radius=5.0,
    )


def _split(line: str, usage: str, required: int, optional: int = 0) -> List[str]:
    args = line.split()
    if not required <= len(args) <= required + optional:
        raise ValueError(f"usage: {usage}")
    return args


def _choice(enum_type, value: str):
    try:
        return enum_type(value.lower())
    except ValueError:
        choices = ", ".join(member.value for member in enum_type)
        raise ValueError(f"unknown value {value!r} (choose from {choices})") from None


def _location(x: str, y: str) -> Location:
    return Location(float(x), float(y))


def _format_ride(ride: Ride) -> str:
    car = ride.requested_car_type.value
    if ride.is_upgraded:
        car += f" (upgraded to {ride.assigned_car_type.value})"
    fare = f"Rs {ride.fare:.2f}" if ride.fare is not None else "-"
    coupon = f", coupon {ride.coupon_code}" if ride.coupon_code else ""
    return (
        f"{ride.id}: user {ride.user_id}, driver {ride.driver_id}, "
        f"({ride.pickup.x:g},{ride.pickup.y:g}) -> ({ride.drop.x:g},{ride.drop.y:g}), "
        f"{ride.distance:.2f} km, {car}, {ride.status.value}, fare {fare}{coupon}"
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
        (name,) = _split(line, "add_user NAME", 1)
        user = self.service.register_user(name)
        print(f"Registered user {user.id} ({user.name})")

    def do_add_driver(self, line: str) -> None:
        """add_driver NAME hatchback|sedan X Y RATING"""
        name, car_type, x, y, rating = _split(line, "add_driver NAME hatchback|sedan X Y RATING", 5)
        driver = self.service.register_driver(name, _choice(CarType, car_type), _location(x, y), float(rating))
        print(f"Registered driver {driver.id} ({driver.name}, {driver.car_type.value}, rating {driver.rating:g}) at ({x}, {y})")

    def do_move(self, line: str) -> None:
        """move DRIVER_ID X Y  - update a driver's location"""
        driver_id, x, y = _split(line, "move DRIVER_ID X Y", 3)
        driver = self.service.update_driver_location(driver_id, _location(x, y))
        print(f"Driver {driver.id} is now at ({x}, {y})")

    def do_book(self, line: str) -> None:
        """book USER_ID PICKUP_X PICKUP_Y DROP_X DROP_Y hatchback|sedan"""
        user_id, px, py, dx, dy, car_type = _split(
            line, "book USER_ID PICKUP_X PICKUP_Y DROP_X DROP_Y hatchback|sedan", 6
        )
        ride = self.service.book_ride(user_id, _location(px, py), _location(dx, dy), _choice(CarType, car_type))
        print(f"Booked {_format_ride(ride)}")

    def do_end(self, line: str) -> None:
        """end RIDE_ID  - finish a ride and show the fare"""
        (ride_id,) = _split(line, "end RIDE_ID", 1)
        fare = self.service.end_ride(ride_id)
        print(
            f"Ride {ride_id} completed. Base Rs {fare.base_fare:.2f}, "
            f"discount Rs {fare.discount:.2f}, total Rs {fare.total:.2f}"
        )

    def do_cancel(self, line: str) -> None:
        """cancel RIDE_ID  - cancel an ongoing ride and charge the cancellation fee"""
        (ride_id,) = _split(line, "cancel RIDE_ID", 1)
        fee = self.service.cancel_ride(ride_id)
        print(f"Ride {ride_id} cancelled. Cancellation fee Rs {fee:.2f}")

    def do_history(self, line: str) -> None:
        """history user|driver ID [ongoing|completed|cancelled]"""
        args = _split(line, "history user|driver ID [ongoing|completed|cancelled]", 2, optional=1)
        kind, owner_id = args[0].lower(), args[1]
        status: Optional[RideStatus] = _choice(RideStatus, args[2]) if len(args) == 3 else None
        if kind == "user":
            rides = self.service.user_history(owner_id, status)
        elif kind == "driver":
            rides = self.service.driver_history(owner_id, status)
        else:
            raise ValueError("usage: history user|driver ID [ongoing|completed|cancelled]")
        if not rides:
            print(f"No rides for {owner_id}")
        for ride in rides:
            print(_format_ride(ride))

    def do_add_coupon(self, line: str) -> None:
        """add_coupon CODE PERCENT [EXPIRES_AT]  - EXPIRES_AT as YYYY-MM-DD or YYYY-MM-DDTHH:MM"""
        args = _split(line, "add_coupon CODE PERCENT [EXPIRES_AT]", 2, optional=1)
        expires_at = datetime.fromisoformat(args[2]) if len(args) == 3 else None
        coupon = Coupon(args[0], float(args[1]), expires_at)
        self.service.add_coupon(coupon)
        expiry = f", expires {expires_at:%Y-%m-%d %H:%M}" if expires_at else ""
        print(f"Added coupon {coupon.code} ({coupon.discount_percent:g}% off{expiry})")

    def do_delete_coupon(self, line: str) -> None:
        """delete_coupon CODE"""
        (code,) = _split(line, "delete_coupon CODE", 1)
        self.service.delete_coupon(code)
        print(f"Deleted coupon {code}")

    def do_apply_coupon(self, line: str) -> None:
        """apply_coupon RIDE_ID CODE  - the discount is taken when the ride ends"""
        ride_id, code = _split(line, "apply_coupon RIDE_ID CODE", 2)
        self.service.apply_coupon(ride_id, code)
        print(f"Coupon {code} applied to {ride_id}")

    def do_demo(self, line: str) -> None:
        """demo  - run a scripted walkthrough on a fresh service"""
        demo = RideHailingCLI(build_service())
        for command in DEMO_SCRIPT:
            print(f"\nride> {command}")
            demo.onecmd(command)

    def do_quit(self, line: str) -> bool:
        """quit  - exit"""
        return True

    do_exit = do_quit
    do_EOF = do_quit


if __name__ == "__main__":
    RideHailingCLI(build_service()).cmdloop()
