from typing import List

import pytest

from cli import DEMO_SCRIPT, RideHailingCLI, build_service, parse_args


@pytest.fixture
def cli() -> RideHailingCLI:
    return RideHailingCLI(build_service())


def run(cli: RideHailingCLI, capsys: pytest.CaptureFixture, *commands: str) -> List[str]:
    """Run commands and return the output lines of the last one."""
    for command in commands[:-1]:
        cli.onecmd(command)
    capsys.readouterr()
    cli.onecmd(commands[-1])
    return capsys.readouterr().out.strip().splitlines()


SETUP = ("add_user Asha", "add_driver Ravi sedan 1 0 4.5")


@pytest.mark.parametrize("matching, expected_driver", [("nearest", "D1"), ("highest-rated", "D2")])
def test_matching_strategy_is_configurable(
    capsys: pytest.CaptureFixture, matching: str, expected_driver: str
) -> None:
    cli = RideHailingCLI(build_service(matching))
    out = run(
        cli, capsys,
        "add_user Asha",
        "add_driver Near sedan 1 0 3.9",
        "add_driver Best sedan 4 0 4.9",
        "book U1 0 0 10 0 sedan",
    )
    assert out[0].startswith(f"Booked R1: user U1, driver {expected_driver}")


def test_unknown_matching_strategy_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown matching strategy 'random'"):
        build_service("random")


@pytest.mark.parametrize("argv, expected", [([], "nearest"), (["--matching", "highest-rated"], "highest-rated")])
def test_matching_command_line_option(argv: List[str], expected: str) -> None:
    assert parse_args(argv).matching == expected


def test_invalid_matching_option_exits(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--matching", "random"])
    assert "invalid choice: 'random'" in capsys.readouterr().err


def test_book_and_end_ride(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    out = run(cli, capsys, *SETUP, "book U1 0 0 10 0 sedan", "end R1")
    assert out == ["Ride R1 completed. Base Rs 69.00, discount Rs 0.00, total Rs 69.00"]


def test_upgrade_is_shown_and_charged_at_hatchback_price(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    out = run(cli, capsys, *SETUP, "book U1 0 0 10 0 hatchback")
    assert "hatchback (upgraded to sedan)" in out[0]
    assert run(cli, capsys, "end R1") == ["Ride R1 completed. Base Rs 55.20, discount Rs 0.00, total Rs 55.20"]


def test_coupon_at_booking(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    (booked,) = run(cli, capsys, *SETUP, "add_coupon SAVE10 10", "book U1 0 0 10 0 sedan SAVE10")
    assert booked.endswith("coupon SAVE10")
    assert run(cli, capsys, "end R1") == ["Ride R1 completed. Base Rs 69.00, discount Rs 6.90, total Rs 62.10"]


def test_fractional_coupon_percent_rounds_half_up(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    out = run(cli, capsys, *SETUP, "add_coupon EIGHTH 12.5", "book U1 0 0 10 0 sedan EIGHTH", "end R1")
    assert out == ["Ride R1 completed. Base Rs 69.00, discount Rs 8.63, total Rs 60.37"]


def test_invalid_coupon_at_booking_books_nothing(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    assert run(cli, capsys, *SETUP, "book U1 0 0 10 0 sedan NOPE") == ["Error: Coupon NOPE does not exist"]
    assert run(cli, capsys, "history user U1") == ["No rides for U1"]


def test_cancel_and_history_filter(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    assert run(cli, capsys, *SETUP, "book U1 0 0 10 0 sedan", "cancel R1") == [
        "Ride R1 cancelled. Cancellation fee Rs 20.00"
    ]
    (line,) = run(cli, capsys, "history user U1 cancelled")
    assert line.startswith("R1:") and "cancelled, fare Rs 20.00" in line
    assert run(cli, capsys, "history driver D1 ongoing") == ["No rides for D1"]


def test_move_driver_into_range(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    assert run(cli, capsys, "add_user Asha", "add_driver Ravi sedan 40 40 4.5", "book U1 0 0 1 0 sedan") == [
        "Error: No sedan available within 5 km"
    ]
    out = run(cli, capsys, "move D1 1 1", "book U1 0 0 1 0 sedan")
    assert out[0].startswith("Booked R1: user U1, driver D1")


@pytest.mark.parametrize(
    "command, message",
    [
        ("book U9 0 0 1 0 sedan", "Error: User U9 not found"),
        ("add_coupon BAD ten", "Error: not a number: 'ten'"),
        ("add_coupon BAD NaN", "Error: not a number: 'NaN'"),
        ("add_coupon BAD 150", "Error: discount_percent must be in (0, 100]"),
        ("add_driver Ravi suv 0 0 4", "Error: unknown value 'suv' (choose from hatchback, sedan)"),
        ("add_driver Ravi sedan 0 0 9", "Error: rating must be between 0 and 5"),
        ("move D1 a b", "Error: could not convert string to float: 'a'"),
        ("end", "Error: usage: end RIDE_ID"),
        ("history rider U1", "Error: usage: history user|driver ID [ongoing|completed|cancelled]"),
        ("history user U1 pending", "Error: unknown value 'pending' (choose from ongoing, completed, cancelled)"),
        ("add_coupon BAD 10 tomorrow", "Error: Invalid isoformat string: 'tomorrow'"),
        ("end R9", "Error: Ride R9 not found"),
    ],
)
def test_errors_are_reported_without_crashing(
    cli: RideHailingCLI, capsys: pytest.CaptureFixture, command: str, message: str
) -> None:
    assert run(cli, capsys, "add_user Asha", command) == [message]


def test_demo_runs_every_feature(cli: RideHailingCLI, capsys: pytest.CaptureFixture) -> None:
    out = "\n".join(run(cli, capsys, "demo"))
    assert out.count("ride> ") == len(DEMO_SCRIPT)
    for expected in [
        "hatchback (upgraded to sedan)",
        "Error: Coupon OLD20 has expired",
        "Error: Coupon NOPE does not exist",
        "Ride R1 completed. Base Rs 55.20, discount Rs 5.52, total Rs 49.68",
        "Ride R2 completed. Base Rs 50.00, discount Rs 0.00, total Rs 50.00",
        "Error: No sedan available within 5 km",
        "Ride R3 cancelled. Cancellation fee Rs 20.00",
        "Error: Ride R3 is already cancelled",
        "Error: Coupon SAVE10 not found",
    ]:
        assert expected in out


def test_quit_stops_the_loop(cli: RideHailingCLI) -> None:
    assert cli.onecmd("quit") is True
