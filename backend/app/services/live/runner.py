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


@dataclass
class ShopState:
    store_id: int
    code: str
    clock: datetime
    speed: int = 1
    rng: random.Random = field(default_factory=random.Random)
    calibration: Calibration | None = None
    calibrated_at: datetime | None = None
    calibrated_for: str | None = None


def starting_clock(session: Session, store: Store, now: datetime) -> datetime:
    """Where a shop's live stream should pick up from."""
    last = last_event_time(session, store)
    if last is not None:
        # Resume exactly where the live stream stopped -- even if a previous
        # fast-forward left it ahead of the real clock, so no minute is
        # simulated twice.
        return max(last, now - MAX_BACKFILL)
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
            try:
                await self._task
            except asyncio.CancelledError:
                pass
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
                if shop is not None and shop.clock > now and last_event_time(session, store) is None:
                    # The demo data was reset under a fast-forwarded shop:
                    # start again from where the fresh history ends.
                    shop = None
                if shop is None:
                    shop = ShopState(
                        store_id=store.id,
                        code=store.code,
                        clock=starting_clock(session, store, now),
                        rng=random.Random(f"{self.seed}:{store.code}"),
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
        events = simulate(cal, shop.clock, target, shop.rng)
        shop.clock = target
        if not events:
            return 0
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
