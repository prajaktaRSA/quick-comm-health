# Ride Hailing Service

A small in-memory backend for a ride-hailing app, with a command-line interface.
You can register users and drivers, book rides within a radius, end or cancel
them, apply coupons and see ride history. Plain Python, standard library only;
pytest is used for the tests.

## How to run

You need Python 3.9 or newer (`python --version` on Windows, `python3 --version`
on macOS/Linux) and Git.

```bash
git clone https://github.com/prajaktaRSA/quick-comm-health.git
cd quick-comm-health
```

Create a virtual environment and install pytest:

```bash
# Windows (PowerShell or Command Prompt)
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt

# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run the tests (you should see `149 passed`):

```bash
.venv\Scripts\python -m pytest        # Windows
.venv/bin/python -m pytest            # macOS / Linux
```

Start the CLI:

```bash
.venv\Scripts\python cli.py                              # Windows
.venv/bin/python cli.py                                  # macOS / Linux
.venv\Scripts\python cli.py --matching highest-rated     # pick the matching strategy
```

At the `ride>` prompt, type `demo` for a scripted walkthrough of everything,
`help` for the command list, and `quit` to exit. A short session:

```text
ride> add_user Asha
Registered user U1 (Asha)
ride> add_driver Ravi hatchback 1 1 4.6
Registered driver D1 (Ravi, hatchback, rating 4.6) at (1, 1)
ride> add_coupon SAVE10 10
Added coupon SAVE10 (10% off)
ride> book U1 0 0 10 0 hatchback SAVE10
Booked R1: user U1, driver D1, (0,0) -> (10,0), 10.00 km, hatchback, ongoing, fare -, coupon SAVE10
ride> end R1
Ride R1 completed. Base Rs 55.20, discount Rs 5.52, total Rs 49.68
```

Other commands: `move DRIVER_ID X Y`, `cancel RIDE_ID`,
`history user|driver ID [ongoing|completed|cancelled]`, `delete_coupon CODE`,
and `add_coupon CODE PERCENT YYYY-MM-DD` for a coupon with an expiry date.

If `python` isn't recognised on Windows, use `py -m venv .venv` instead; the
`.venv\Scripts\python` commands then work as written. There's no need to
activate the virtual environment (PowerShell often blocks that anyway).

## Assumptions

- Locations are (x, y) points in km and distance is a straight line. A driver
  exactly on the 5 km search radius counts as in range.
- Pickup and drop are given when booking; the fare is worked out when the ride ends.
- Pricing tiers: first 2 km at ₹10/km, km 3–5 at ₹8/km, beyond that ₹5/km.
  Hatchbacks cost 20% less than sedans. Every ride costs at least ₹50.
- The ₹50 minimum applies before the coupon, so 10% off a ₹50 ride is ₹45.
- Coupons are a percentage off, with an optional expiry date, and are given
  when booking. An unknown or expired coupon is rejected and nothing is booked.
  If a coupon expires or is deleted while the ride is in progress, the ride
  ends at full price instead of failing.
- If no hatchback is free, the rider gets a sedan at the hatchback price. A
  sedan request never gets a hatchback.
- A user can have one ongoing ride at a time. When a ride ends, the driver's
  location becomes the drop point.
- Cancelling costs a flat ₹20, only ongoing rides can be cancelled, and coupons
  don't reduce the fee.

## Key design decisions and trade-offs

**Strategies for the parts that change.** Pricing, driver matching and the
cancellation fee are each an abstract class with one or more implementations,
passed into `RideService` when it's created. Switching from nearest-driver to
highest-rated matching is a command-line flag and doesn't touch the booking
code. The trade-off is a few more small classes than a single service with
if/else branches.

**Matching is split in two.** The service decides which drivers are eligible
(free, in range, right car type) and the strategy only picks one of them. That
keeps every strategy tiny and means the eligibility rules can't drift between
strategies.

**The free upgrade is a pricing rule, not a matching hack.** A ride stores both
the car type that was requested and the one that was assigned, and the fare is
always based on the requested type. Matching can hand out a sedan without
knowing anything about price. The upgrade order itself is a small lookup table.

**Money is `Decimal`, never `float`.** All amounts are rounded to the paisa,
half up, in one helper (`money.py`). See the AI notes below for why.

**One lock around every service method.** Two people booking the same driver
at the same moment get exactly one ride (there's a test that fires 20
simultaneous bookings at one driver). It's simple and obviously correct, but it
means every operation waits for every other one. That's fine in memory; with
real traffic I'd lock per driver or rely on database transactions.

**CLI and in-memory dicts rather than an API and a database.** Quicker to build
and demo in two hours, and the service has no idea it's behind a CLI, so an
HTTP layer could sit on top of it. Ids are simple counters (`U1`, `D1`, `R1`)
because nothing is ever deleted.

**Surge pricing was left out on purpose.** Demand and supply need to be
measured when the ride is booked, not when it ends, so it touches booking as
well as pricing. With the time available I chose to finish the other bonuses
properly instead.

## What I'd do with more time

- **Surge pricing:** a pluggable policy that counts open requests and free
  drivers near the pickup at booking time, stores the multiplier on the ride,
  and a pricing strategy that applies it.
- **A proper `Cab` entity** (registration number, car type) instead of the car
  type living on the driver.
- **Finer-grained locking**, and a spatial index for finding nearby drivers
  instead of scanning all of them.
- **Persistence and an HTTP API** in front of the same service.
- **A fuller ride lifecycle** (driver arriving, trip started), so cancellation
  fees could depend on how far along the ride is.
- **Richer coupons:** flat amounts, caps, per-user limits.
- **Fail fast on configuration:** check at start-up that every car type has a
  price and an upgrade rule. Today a missing upgrade rule only shows up on the
  first booking.

## How I used AI

I used Claude Code as a pair programmer. I wrote the brief: the requirements,
the rule that bonus features should be added without rewriting existing code,
strategies passed into the service, no dead code, small steps, and tests for
the pricing engine. I asked for one file or feature at a time and reviewed
and committed each step before moving on.

I also asked it to check its own work rather than taking it on trust: whether
anything was hard-coded to pass the tests, and whether the tests would fail if
the logic were broken.

Two things I rejected and had rewritten:

**Coupons.** The first version booked the ride and then had a separate
"apply coupon" step for a ride already in progress. When I re-read the
problem statement, it says the coupon is applied *when starting* the ride. I
had it changed so the coupon is passed with the booking and checked before a
driver is assigned. An invalid or expired coupon now books nothing, and the
separate apply step is gone.

**Floats for money.** Fares and discounts were originally floats rounded with
Python's `round()`. I asked how the discounted price was actually calculated.
Checking it showed that 12.5% off ₹69.00 came out as ₹8.62 instead of ₹8.63,
because floats can't store most decimal fractions exactly and `round()` rounds
halves to even. The existing tests hadn't caught it because none of them hit
an exact half paisa. I had all money switched to `Decimal` with half-up
rounding in a single place, and added tests for those half-paisa cases.
