"""The background loop that keeps every shop trading.

One ``LiveRunner`` per API process. Every couple of seconds it moves each
shop's simulated clock forward and records what happened in between.

* At 1x the shop clock follows the real clock.
* Fast-forward (10x, 60x, 300x) runs the shop's day ahead of real time -- the demo
  move. It stops at the end of today, and back at 1x the shop waits for real
  time to catch up rather than rewrite events it already recorded.
* After downtime (a restart, a redeploy, a laptop lid) the shop catches up in
  chunks from where its data ends, so there is never a gap in "today".

Run it in exactly one process: two runners would both invent the same hour.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from ...models import HourlyData, Store
from .clock import end_of_day, ist_now
from .engine import IncomingEvent, last_event_time, record
from .simulator import Calibration, calibrate, simulate

log = logging.getLogger("steptosales.live")

TICK_SECONDS = 2.0
#: Largest slice simulated in one tick while catching up, so one tick never
#: blocks for long.
CATCH_UP_CHUNK = timedelta(hours=3)
#: Further behind the real clock than this counts as downtime to catch up on.
CATCH_UP_AFTER = timedelta(minutes=1)
#: Further back than this, history is not backfilled -- start from a day ago.
MAX_BACKFILL = timedelta(days=7)
RECALIBRATE_AFTER = timedelta(minutes=30)
SPEEDS = (0, 1, 10, 60, 300)
#: Demo days: (visitors, chance of buying) against the shop's usual. Lets a
#: demo show the phone alerts for a bad or a good day on demand.
SCENARIOS: dict[str, tuple[float, float]] = {
    "normal": (1.0, 1.0),
    "slow": (0.5, 0.45),
    "busy": (1.7, 1.2),
}


@dataclass
class ShopState:
    store_id: int
    code: str
    clock: datetime
    speed: int = 1
    scenario: str = "normal"
    rng: random.Random = field(default_factory=random.Random)
    calibration: Calibration | None = None
    calibrated_at: datetime | None = None
    calibrated_for: str | None = None
    #: This shop has live events in the database (found at start, or
    #: recorded since). If they vanish, the demo data was reset underneath.
    has_events: bool = False


def starting_clock(session: Session, store: Store, now: datetime) -> datetime:
    """Where a shop's live stream should pick up from."""
    last = last_event_time(session, store)
    if last is not None:
        # Resume exactly where the live stream stopped -- even if a previous
        # fast-forward left it ahead of the real clock, so no minute is
        # simulated twice.
        return max(last, now - MAX_BACKFILL)
    return history_end(session, store, now)


def history_end(session: Session, store: Store, now: datetime) -> datetime:
    """Just after the shop's last recorded hour (capped to [now - a week, now])."""
    day = session.exec(
        select(func.max(HourlyData.date)).where(HourlyData.store_id == store.id)
    ).first()
    if not day:
        return now
    hour = session.exec(
        select(func.max(HourlyData.hour))
        .where(HourlyData.store_id == store.id)
        .where(HourlyData.date == day)
    ).first()
    # History covers up to some minute of its last hour; resume at the next
    # hour, or at "now" if that hour is still in progress.
    resume = datetime.fromisoformat(day) + timedelta(hours=int(hour) + 1)
    return max(min(resume, now), now - MAX_BACKFILL)


class LiveRunner:
    def __init__(self, engine, seed: str = "steptosales") -> None:
        self.engine = engine
        self.seed = seed
        self.shops: dict[str, ShopState] = {}
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            # Wait for the loop to finish without swallowing a cancellation
            # of stop() itself (asyncio.wait never raises the task's error).
            await asyncio.wait({self._task})
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.step)
            except Exception:  # keep ticking; a bad tick must not end live mode
                log.exception("live tick failed")
            await asyncio.sleep(TICK_SECONDS)

    # ---- controls -------------------------------------------------------

    def reset_today(self, code: str, clear) -> datetime | None:
        """Start the shop's day again: ``clear(session, store, day)`` removes
        today's activity, then the shop resumes from midnight (or from where
        uploaded history ends, if that is later) at real time, on a usual day.
        The hours up to now are simply simulated again. Returns the new
        clock, or None for an unknown shop.

        Holds the tick lock throughout, so no tick can write into the day
        while it is being cleared.
        """
        with self._lock, Session(self.engine) as session:
            store = session.exec(select(Store).where(Store.code == code)).first()
            if store is None:
                return None
            now = ist_now()
            day = now.date()
            clear(session, store, day.isoformat())
            session.commit()
            midnight = datetime(day.year, day.month, day.day)
            clock = max(midnight, history_end(session, store, now))
            self.shops[code] = ShopState(
                store_id=store.id,
                code=code,
                clock=clock,
                rng=random.Random(f"{self.seed}:{code}:{now.isoformat()}"),
                has_events=last_event_time(session, store) is not None,
            )
            return clock

    def state(self, code: str) -> ShopState | None:
        return self.shops.get(code)

    def set_speed(self, code: str, speed: int) -> ShopState | None:
        if speed not in SPEEDS:
            raise ValueError(f"speed must be one of {SPEEDS}")
        with self._lock:
            shop = self.shops.get(code)
            if shop is not None:
                shop.speed = speed
            return shop

    def set_scenario(self, code: str, scenario: str) -> ShopState | None:
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {list(SCENARIOS)}")
        with self._lock:
            shop = self.shops.get(code)
            if shop is not None:
                shop.scenario = scenario
            return shop

    def shop_now(self, code: str) -> datetime:
        """The shop's current time: its simulated clock if that runs ahead."""
        now = ist_now()
        shop = self.shops.get(code)
        return max(now, shop.clock) if shop else now

    # ---- one tick -------------------------------------------------------

    def step(self, now: datetime | None = None, dt: float = TICK_SECONDS) -> int:
        """Advance every shop by one tick. Returns how many events were recorded."""
        now = now or ist_now()
        total = 0
        with self._lock, Session(self.engine) as session:
            for store in session.exec(select(Store).order_by(Store.code)).all():
                shop = self.shops.get(store.code)
                if shop is not None and shop.clock > now:
                    if last_event_time(session, store) is not None:
                        shop.has_events = True      # e.g. a bill from the till
                    elif shop.has_events:
                        # The demo data was reset under a fast-forwarded
                        # shop: start again from where the fresh history
                        # ends. (A shop fast-forwarding through quiet night
                        # hours has simply recorded nothing yet -- that is
                        # not a reset, and must keep its speed.)
                        shop = None
                if shop is None:
                    shop = ShopState(
                        store_id=store.id,
                        code=store.code,
                        clock=starting_clock(session, store, now),
                        rng=random.Random(f"{self.seed}:{store.code}"),
                        has_events=last_event_time(session, store) is not None,
                    )
                    self.shops[store.code] = shop
                total += self._advance(session, store, shop, now, dt)
        return total

    def _advance(self, session: Session, store: Store, shop: ShopState,
                 now: datetime, dt: float) -> int:
        if shop.clock < now - MAX_BACKFILL:
            shop.clock = now - MAX_BACKFILL
        if shop.speed == 0:
            return 0
        if shop.clock < now - CATCH_UP_AFTER:
            target = min(now, shop.clock + CATCH_UP_CHUNK)   # back from downtime
        elif shop.speed > 1:
            target = max(now, shop.clock + timedelta(seconds=dt * shop.speed))
        else:
            target = now                                      # 1x; waits if ahead
        target = min(target, end_of_day(max(now, shop.clock)))
        if target <= shop.clock:
            return 0

        cal = self._calibration(session, store, shop, target)
        visitors, buying = SCENARIOS.get(shop.scenario, SCENARIOS["normal"])
        events = simulate(cal, shop.clock, target, shop.rng, visitors, buying)
        shop.clock = target
        if not events:
            return 0
        shop.has_events = True
        return record(session, store, [IncomingEvent.from_sim(e) for e in events])

    def _calibration(self, session: Session, store: Store, shop: ShopState,
                     at: datetime) -> Calibration:
        day = at.date().isoformat()
        stale = (
            shop.calibration is None
            or shop.calibrated_for != day
            or shop.calibrated_at is None
            or ist_now() - shop.calibrated_at > RECALIBRATE_AFTER
        )
        if stale:
            shop.calibration = calibrate(session, store, at.date())
            shop.calibrated_at = ist_now()
            shop.calibrated_for = day
        return shop.calibration
