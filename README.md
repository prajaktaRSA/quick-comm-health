# Ride Hailing Service

An in-memory ride-hailing backend (users, drivers, booking, pricing, coupons,
history) with a command-line demo. Built in Python using only the standard
library; `pytest` is the only development dependency.

The design rule throughout is the **Open/Closed Principle**: pricing, driver
matching and cancellation fees are strategies injected into the service, so
new behaviour is added as new classes, not by rewriting existing logic.

## Quick start

Requires Python 3.9+ (developed and tested on 3.12).

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r requirements-dev.txt     # macOS / Linux

.venv\Scripts\python -m pytest            # run the test suite
.venv\Scripts\python cli.py               # start the CLI (nearest-driver matching)
.venv\Scripts\python cli.py --matching highest-rated
```

In the CLI, type `demo` for a scripted walkthrough of every feature, or `help`
for the command list:

| Command | Purpose |
|---|---|
| `add_user NAME` | Register a user (ids `U1`, `U2`, ...) |
| `add_driver NAME hatchback\|sedan X Y RATING` | Register a driver (ids `D1`, ...) |
| `move DRIVER_ID X Y` | Update a driver's location |
| `book USER_ID PICKUP_X PICKUP_Y DROP_X DROP_Y hatchback\|sedan [COUPON]` | Book the best driver within the search radius, optionally with a coupon |
| `end RIDE_ID` | Complete a ride and show base fare, discount and total |
| `cancel RIDE_ID` | Cancel an ongoing ride and charge the cancellation fee |
| `history user\|driver ID [ongoing\|completed\|cancelled]` | Ride history, optionally filtered by status |
| `add_coupon CODE PERCENT [YYYY-MM-DD]` | Add a percentage coupon with optional expiry |
| `delete_coupon CODE` | Remove a coupon |

Errors (unknown ids, no driver in range, expired coupons, bad input) are
printed as `Error: ...` and the CLI keeps running.

## Design

```
cli.py                CLI + build_service(): the only place concrete classes are chosen
  └─ service.py         RideService: in-memory dicts, booking, fares, coupons, history; one lock
       ├─ pricing.py      PricingStrategy        ← TieredPricingStrategy
       ├─ matching.py     MatchingStrategy       ← NearestDriverStrategy, HighestRatedDriverStrategy
       ├─ cancellation.py CancellationFeePolicy  ← FlatCancellationFee
       ├─ models.py       User, Driver, Ride, Coupon, Location, CarType, RideStatus
       └─ money.py        to_money(): Decimal rupees rounded half-up to the paisa
```

- **Strategies via dependency injection.** `RideService(pricing, matching, ...)`
  depends only on the abstract base classes. Tests inject other strategies
  (flat pricing, highest-rated matching, free cancellation for upgrades) to
  prove the service uses whatever it is given.
- **Matching is split in two.** The service applies the rules every strategy
  shares (driver available, within radius, acceptable car type); the strategy
  only chooses among eligible drivers.
- **The upgrade rule is data.** `CAR_TYPE_FALLBACKS` maps a requested type to
  the types tried in order (`hatchback → hatchback, sedan`). Pricing uses the
  ride's *requested* car type, which is what charges an upgraded ride the
  hatchback price.
- **Thread safety is built in.** Every public `RideService` method is decorated
  with `@_synchronized`, which holds one `threading.Lock`, so each operation is
  atomic and two users can never book the same driver.
- **Tiered pricing is configuration.** Tiers, minimum fare and per-car-type
  multipliers are constructor arguments of `TieredPricingStrategy`.
- **Money is `Decimal`, never `float`.** Fares, discounts, fees and coupon
  percentages are exact decimals, rounded to the paisa with `ROUND_HALF_UP` in
  one place (`money.py`). With floats, 12.5% off ₹69.00 came out as ₹8.62
  instead of ₹8.63. Distance is the only float input, converted once.
- **Models guard their own state.** A ride can only be completed or cancelled
  while `ONGOING`; coupons validate their percentage; drivers validate rating.

### Pricing

| Distance slab | Rate |
|---|---|
| First 2 km | ₹10/km |
| Next 3 km (2–5 km) | ₹8/km |
| Beyond 5 km | ₹5/km |


## Bonus features

| Feature | Status | How |
|---|---|---|
| Concurrency safety | Done | Every public `RideService` method runs under one `threading.Lock` via the `@_synchronized` decorator. Tests show 20 simultaneous bookings of one driver produce exactly one ride. |
| Ride cancellation with fee | Done | New `CancellationFeePolicy` (default flat ₹20), `Ride.cancel()` and `RideService.cancel_ride()`. Purely additive: no existing lines changed. |
| Configurable matching | Done | New `HighestRatedDriverStrategy` (ties go to the nearest driver), chosen with `cli.py --matching nearest\|highest-rated`. `service.py` was not edited; a further strategy is one more entry in `MATCHING_STRATEGIES`. |
| Surge pricing | Not implemented | Out of scope by decision. A demand/supply-based multiplier would be a new `SurgePolicy` injected into the service and evaluated at booking, plus a `PricingStrategy` that applies it. |


## Assumptions

1. **Distance is Euclidean** on the (x, y) plane, in km. A driver exactly on
   the search radius (default 5 km) is eligible.
2. **The fare is calculated when the ride ends**, from the pickup and drop
   coordinates given at booking.
3. **The cancellation fee is a flat ₹20.** Only ongoing rides can be cancelled;
   coupons do not reduce the fee; the driver is freed at their current location.
4. **Coupons are applied when starting a ride** (`book ... COUPON`). Unknown or
   expired coupons return an error without crashing, and the ride is not booked.
   The discount is taken from the fare when the ride ends; a coupon that expires
   or is deleted in between is dropped, so it never blocks ending a ride.
5. **The ₹50 minimum applies before coupons.** A 10% coupon on a ₹50 ride
   charges ₹45.
6. **Upgrades go one way:** a hatchback request may get a sedan; a sedan request
   never gets a hatchback. A hatchback within range is always preferred over a
   nearer sedan.
7. **One ongoing ride per user.** A driver is unavailable while on a ride and
   moves to the drop location when it is completed.
8. Coupons are percentage discounts. Ids are sequential per type (`U1`, `D1`, `R1`)
   because storage is in-memory and nothing is deleted.

## Testing

```bash
.venv\Scripts\python -m pytest -v
```

148 tests, all passing:

| File | Covers |
|---|---|
| `test_pricing.py` | Every tier boundary, minimum fare, hatchback rate, free upgrade, Decimal fares rounded half-up, custom/invalid configuration |
| `test_models.py` | Coupon discount (including half-paisa cases such as 12.5% of ₹69.00 = ₹8.63) and expiry, ride state transitions, rating validation |
| `test_matching.py` | Nearest and highest-rated selection, their tie-breaks, no candidates |
| `test_cancellation.py` | Flat fee default, custom and invalid amounts |
| `test_service.py` | Registration, booking and upgrades, radius edge, no-driver messages, end ride, coupons at booking (valid, unknown, expired, deleted, expiring mid-ride), cancellation, history filters, injected strategies |
| `test_concurrency.py` | 20 threads booking one driver → exactly one ride; concurrent ends and cancels charge once; unique ids under concurrent registration |
| `test_cli.py` | Each command, `--matching` option, error messages for bad input, the full demo |

The concurrency tests were checked against the unlocked `RideService`, where
they fail (all 20 threads book the same driver), so they detect the race they
are meant to.

## AI usage notes

This project was built as an AI-assisted pair-programming exercise:

- **The developer acted as architect.** They wrote the requirements, the
  Open/Closed and dependency-injection constraints, the commit plan, and the
  assumptions, and reviewed and committed each step.
- **The AI assistant (Claude Code) acted as coder.** It generated one file or
  feature per step, with tests, and stopped for review before the next step.
- **Verification was not left to the AI's word.** Every fare in the tests was
  hand-calculated from the tier table; the concurrency tests were run against
  the unsynchronised service to show they fail without the lock; the full suite
  was run after every step.
- **Design decisions made during the session:** pricing uses the requested car
  type (so upgrades need no special pricing code); coupon validity is checked
  both when applied and when the ride ends; cancellation was added as an
  optional injected policy rather than a subclass, to avoid a separate class
  for every combination of bonus features. A review pass then removed
  redundant code: a thread-safe subclass of pass-through wrappers was folded
  into `RideService` as one lock decorator, a second way of applying coupons
  was dropped in favour of applying them at booking, and a constructor option
  used only by tests was replaced by a constant.
