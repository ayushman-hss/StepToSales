"""Live mode: the simulator, the event log and its rollups, pace, and the API.

The core promise carried over from the rest of the app: live numbers still
reconcile. Every rupee in the event log appears exactly once in hourly_data
and once in sale_line, and replaying an event changes nothing.
"""
import json
import random
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

from app import models_pooling  # noqa: F401
from app.db import get_session
from app.live import runner as app_runner
from app.main import app
from app.models import HourlyData, LiveEvent, Product, SaleLine, Store, Upload
from app.services.auth import upsert_user
from app.services.live.clock import end_of_day, ist_now
from app.services.live.engine import IncomingEvent, LIVE_UPLOAD, live_upload, record
from app.services.live.pace import conversion_alert, live_view
from app.services.live.runner import LiveRunner, starting_clock
from app.services.live.simulator import Calibration, Line, calibrate, simulate

PASSWORD = "correct-horse"
TODAY = ist_now().date()
OPEN = range(8, 21)


# ---------------------------------------------------------------------------
# fixtures: one shop with four weeks of steady history
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as s:
        shop, other = Store(code="S1", name="Kirana"), Store(code="S2", name="Kiosk")
        s.add_all([shop, other])
        upload = Upload(filename="history.xlsx", rows=0)
        s.add(upload)
        s.commit()
        s.add_all([
            Product(store_id=shop.id, sku="TEA", name="Tea", cost_price=8, sell_price=10),
            Product(store_id=shop.id, sku="RUSK", name="Rusk", cost_price=15, sell_price=20),
            Product(store_id=other.id, sku="COLA", name="Cola", cost_price=16, sell_price=20),
        ])
        tx = 0
        for back in range(1, 29):
            day = (TODAY - timedelta(days=back)).isoformat()
            for hour in OPEN:
                # 10 visitors, 5 bills of Tea + Rusk (Rs 30) every open hour.
                s.add(HourlyData(store_id=shop.id, upload_id=upload.id, date=day,
                                 hour=hour, footfall=10, transactions=5, sales=150.0))
                for _ in range(5):
                    tx += 1
                    for sku, price in (("TEA", 10.0), ("RUSK", 20.0)):
                        s.add(SaleLine(store_id=shop.id, upload_id=upload.id, date=day,
                                       hour=hour, transaction_id=f"T{tx}", sku=sku,
                                       qty=1, unit_price=price))
        s.commit()
        upsert_user(s, shop, "s1", PASSWORD)
        upsert_user(s, other, "s2", PASSWORD)
        yield s


@pytest.fixture
def shop(db):
    return db.exec(select(Store).where(Store.code == "S1")).one()


@pytest.fixture
def client(engine, db, monkeypatch):
    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    fresh = LiveRunner(engine, seed="test")
    for name in ("engine", "shops", "seed"):
        monkeypatch.setattr(app_runner, name, getattr(fresh, name))
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client, username="s1"):
    res = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def ts(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def live_totals(session, store):
    up = session.exec(select(Upload).where(Upload.filename == LIVE_UPLOAD)).first()
    events = session.exec(select(LiveEvent).where(LiveEvent.store_id == store.id)).all()
    hourly = session.exec(select(HourlyData).where(HourlyData.upload_id == up.id)).all()
    lines = session.exec(select(SaleLine).where(SaleLine.upload_id == up.id)).all()
    return {
        "event_paise": sum(e.amount_paise for e in events),
        "hourly_paise": round(sum(h.sales for h in hourly) * 100),
        "line_paise": round(sum(line.qty * line.unit_price for line in lines) * 100),
        "visits": sum(e.kind == "visit" for e in events),
        "hourly_visits": sum(h.footfall for h in hourly),
        "bills": sum(e.kind == "bill" for e in events),
        "hourly_bills": sum(h.transactions for h in hourly),
    }


# ---------------------------------------------------------------------------
# simulator
# ---------------------------------------------------------------------------


def test_calibration_learns_the_shops_rhythm(db, shop):
    cal = calibrate(db, shop, TODAY)
    assert cal.usable
    assert cal.visitors[(TODAY.weekday(), 10)] == pytest.approx(10)
    assert cal.visitors.get((TODAY.weekday(), 3), 0) == 0
    assert cal.conversion[10] == pytest.approx(0.5)
    assert {tuple(x.sku for x in b) for b in cal.baskets[10]} == {("TEA", "RUSK")}
    assert cal.baskets[10][0][0].unit_price_paise == 1000


def test_calibration_ignores_today(db, shop):
    db.add(HourlyData(store_id=shop.id, upload_id=1, date=TODAY.isoformat(), hour=10,
                      footfall=500, transactions=1, sales=10.0))
    db.commit()
    assert calibrate(db, shop, TODAY).visitors[(TODAY.weekday(), 10)] == pytest.approx(10)


def test_simulation_is_deterministic_for_a_seed(db, shop):
    cal = calibrate(db, shop, TODAY)
    a = simulate(cal, ts(8), ts(20), random.Random("seed"))
    b = simulate(cal, ts(8), ts(20), random.Random("seed"))
    assert a == b and len(a) > 50


def test_simulation_follows_history_on_average(db, shop):
    cal = calibrate(db, shop, TODAY)
    events = simulate(cal, ts(8), ts(21), random.Random(1))
    visits = sum(e.kind == "visit" for e in events)
    bills = [e for e in events if e.kind == "bill"]
    assert 90 < visits < 170            # 13 open hours x 10 visitors
    assert 0.35 < len(bills) / visits < 0.65
    assert all(e.amount_paise == 3000 for e in bills)


def test_simulation_stays_inside_its_window_and_hour(db, shop):
    cal = calibrate(db, shop, TODAY)
    start, end = ts(9, 50), ts(10, 10)
    events = simulate(cal, start, end, random.Random(7))
    assert all(start <= e.ts < end for e in events)
    assert events == sorted(events, key=lambda e: e.ts)


def test_a_closed_hour_has_nobody(db, shop):
    cal = calibrate(db, shop, TODAY)
    assert simulate(cal, ts(2), ts(4), random.Random(3)) == []


def test_no_history_means_no_simulation():
    assert simulate(Calibration("S9"), ts(9), ts(12), random.Random(1)) == []


# ---------------------------------------------------------------------------
# event log -> hourly_data / sale_line
# ---------------------------------------------------------------------------


def _bill(event_id, when, qty=1):
    return IncomingEvent(event_id, "bill", when, "pos", (Line("TEA", qty, 1000),))


def test_rollup_reconciles_to_the_paisa(db, shop):
    cal = calibrate(db, shop, TODAY)
    events = simulate(cal, ts(8), ts(14, 30), random.Random(5))
    record(db, shop, [IncomingEvent.from_sim(e) for e in events])
    t = live_totals(db, shop)
    assert t["event_paise"] == t["hourly_paise"] == t["line_paise"] > 0
    assert t["visits"] == t["hourly_visits"]
    assert t["bills"] == t["hourly_bills"]


def test_replaying_an_event_changes_nothing(db, shop):
    first = record(db, shop, [_bill("b-1", ts(10, 5), qty=2)])
    before = live_totals(db, shop)
    again = record(db, shop, [_bill("b-1", ts(10, 5), qty=2)])
    assert (first, again) == (1, 0)
    assert live_totals(db, shop) == before


def test_duplicate_ids_in_one_batch_count_once(db, shop):
    assert record(db, shop, [_bill("dup", ts(10)), _bill("dup", ts(10))]) == 1


def test_live_row_sits_beside_history_and_is_recomputed(db, shop):
    record(db, shop, [_bill("a", ts(10, 1))])
    record(db, shop, [_bill("b", ts(10, 30)), IncomingEvent("v", "visit", ts(10, 2), "pos")])
    up = live_upload(db)
    rows = db.exec(
        select(HourlyData).where(HourlyData.upload_id == up.id)
        .where(HourlyData.date == TODAY.isoformat()).where(HourlyData.hour == 10)
    ).all()
    assert [(r.footfall, r.transactions, r.sales) for r in rows] == [(1, 2, 20.0)]


def test_live_bills_feed_the_bundle_engine(db, shop):
    record(db, shop, [IncomingEvent("x", "bill", ts(9), "pos",
                                    (Line("TEA", 1, 1000), Line("RUSK", 1, 2000)))])
    up = live_upload(db)
    skus = db.exec(select(SaleLine.sku).where(SaleLine.upload_id == up.id)
                   .where(SaleLine.transaction_id == "x")).all()
    assert sorted(skus) == ["RUSK", "TEA"]


# ---------------------------------------------------------------------------
# runner: clocks and speeds
# ---------------------------------------------------------------------------


def test_new_shop_resumes_where_history_ends(db, shop):
    # History's last row is yesterday 20:00, so the stream picks up at 21:00.
    assert starting_clock(db, shop, ts(15, 20)) == ts(21, day=TODAY - timedelta(days=1))


def test_resume_is_capped_at_a_week(db, shop):
    later = ts(12) + timedelta(days=30)
    assert starting_clock(db, shop, later) == later - timedelta(days=7)


def test_resume_after_live_events_continues_from_the_last_one(db, shop):
    record(db, shop, [_bill("late", ts(19, 40))])
    assert starting_clock(db, shop, ts(12)) == ts(19, 40)


def test_catches_up_then_follows_the_real_clock(engine, db, shop):
    r = LiveRunner(engine, seed="t")
    now = ts(12)
    for _ in range(12):                       # catch-up comes in 3h chunks
        r.step(now=now)
    assert r.shops["S1"].clock == now
    r.step(now=now + timedelta(seconds=2))
    assert r.shops["S1"].clock == now + timedelta(seconds=2)


def test_fast_forward_runs_ahead_and_1x_then_waits(engine, db, shop):
    r = LiveRunner(engine, seed="t")
    now = ts(12)
    for _ in range(12):
        r.step(now=now)
    r.set_speed("S1", 60)
    r.step(now=now, dt=60)                    # one real minute = one shop hour
    assert r.shops["S1"].clock == ts(13)
    r.set_speed("S1", 1)
    r.step(now=now + timedelta(minutes=5))
    assert r.shops["S1"].clock == ts(13)      # waits for real time


def test_fast_forward_stops_at_midnight(engine, db, shop):
    r = LiveRunner(engine, seed="t")
    now = ts(23, 50)
    for _ in range(12):
        r.step(now=now)
    r.set_speed("S1", 60)
    r.step(now=now, dt=3600)
    assert r.shops["S1"].clock == end_of_day(now)


def test_pause_stops_the_clock(engine, db, shop):
    r = LiveRunner(engine, seed="t")
    r.step(now=ts(12))
    r.set_speed("S1", 0)
    clock = r.shops["S1"].clock
    r.step(now=ts(12) + timedelta(hours=1))
    assert r.shops["S1"].clock == clock


def test_runner_rejects_odd_speeds(engine):
    with pytest.raises(ValueError):
        LiveRunner(engine).set_speed("S1", 7)


# ---------------------------------------------------------------------------
# pace, band, projection, alert
# ---------------------------------------------------------------------------


def _history_frame(weeks=4, per_hour=150.0, day=TODAY):
    rows = []
    for w in range(1, weeks + 1):
        d = (day - timedelta(weeks=w)).isoformat()
        rows += [{"date": d, "hour": h, "footfall": 10, "transactions": 5,
                  "sales": per_hour} for h in OPEN]
    return pd.DataFrame(rows)


def _today_frame(hours, per_hour, footfall=10, transactions=5, day=TODAY):
    return pd.DataFrame([{"date": day.isoformat(), "hour": h, "footfall": footfall,
                          "transactions": transactions, "sales": per_hour} for h in hours])


def test_on_pace_day_projects_the_usual_total():
    view = live_view(_history_frame(), _today_frame(range(8, 13), 150.0), TODAY)
    assert view.typical_sales == pytest.approx(13 * 150)
    assert view.pace == pytest.approx(0)
    assert view.pace_through_hour == 11
    assert view.projected_sales == pytest.approx(13 * 150)


def test_ahead_of_pace():
    view = live_view(_history_frame(), _today_frame(range(8, 13), 180.0), TODAY)
    assert view.pace == pytest.approx(0.2)


def test_the_hour_in_progress_is_left_out_of_pace():
    today = _today_frame(range(8, 12), 150.0)
    today.loc[len(today)] = {"date": TODAY.isoformat(), "hour": 12, "footfall": 1,
                             "transactions": 0, "sales": 0.0}
    view = live_view(_history_frame(), today, TODAY)
    assert view.pace == pytest.approx(0)
    assert view.now.hour == 12 and view.now.usual_sales == pytest.approx(150)


def test_band_shows_today_only_up_to_now():
    view = live_view(_history_frame(), _today_frame(range(8, 11), 150.0), TODAY)
    assert view.band[10].actual == pytest.approx(450)
    assert view.band[11].actual is None
    assert view.band[20].p50 == pytest.approx(13 * 150)


def test_band_needs_enough_past_weekdays():
    assert live_view(_history_frame(weeks=2), _today_frame([9], 150.0), TODAY) is None


def test_first_hour_has_no_pace_yet():
    view = live_view(_history_frame(), _today_frame([8], 150.0), TODAY)
    assert view.pace is None and view.projected_sales is None


def test_conversion_alert_needs_a_real_drop_and_enough_people():
    hist = _history_frame()
    quiet = _today_frame([10, 11], 10.0, footfall=12, transactions=1)
    assert "Only 8% of the 12" in conversion_alert(quiet, hist, 11)
    few = _today_frame([10, 11], 10.0, footfall=5, transactions=0)
    assert conversion_alert(few, hist, 11) is None
    normal = _today_frame([10, 11], 150.0, footfall=10, transactions=5)
    assert conversion_alert(normal, hist, 11) is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", [
    ("get", "/api/live/status"), ("post", "/api/live/speed"), ("post", "/api/live/bill"),
    ("post", "/api/live/visit"), ("get", "/api/live/bills"),
])
def test_live_routes_need_a_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_till_bill_is_priced_from_my_list_and_counts_a_visitor(client, db, shop):
    res = client.post("/api/live/bill", headers=login(client), json={
        "event_id": "phone-0001", "lines": [{"sku": "TEA", "qty": 2}, {"sku": "RUSK", "qty": 1}],
    })
    assert res.status_code == 200, res.text
    assert res.json()["amount_paise"] == 4000 and res.json()["recorded"]
    t = live_totals(db, shop)
    assert (t["visits"], t["bills"], t["event_paise"]) == (1, 1, 4000)


def test_till_retry_is_recorded_once(client, db, shop):
    body = {"event_id": "phone-0002", "lines": [{"sku": "TEA", "qty": 1}]}
    headers = login(client)
    client.post("/api/live/bill", headers=headers, json=body)
    again = client.post("/api/live/bill", headers=headers, json=body)
    assert again.json()["recorded"] is False
    assert live_totals(db, shop)["bills"] == 1


def test_till_refuses_another_shops_products(client):
    res = client.post("/api/live/bill", headers=login(client), json={
        "event_id": "phone-0003", "lines": [{"sku": "COLA", "qty": 1}],
    })
    assert res.status_code == 400
    assert "COLA" in res.json()["detail"]


def test_bills_land_in_the_logged_in_shop_only(client, db):
    client.post("/api/live/visit", headers=login(client, "s2"), json={"event_id": "door-0001"})
    s2 = db.exec(select(Store).where(Store.code == "S2")).one()
    assert db.exec(select(func.count()).select_from(LiveEvent)
                   .where(LiveEvent.store_id == s2.id)).one() == 1
    assert client.get("/api/live/bills", headers=login(client)).json() == []


def test_recent_bills_name_the_products(client):
    headers = login(client)
    client.post("/api/live/bill", headers=headers, json={
        "event_id": "phone-0004", "lines": [{"sku": "RUSK", "qty": 3}]})
    bills = client.get("/api/live/bills", headers=headers).json()
    assert bills[0]["items"] == 3 and bills[0]["lines"][0]["name"] == "Rusk"
    assert bills[0]["source"] == "pos"


def test_status_and_speed(client):
    headers = login(client)
    assert client.post("/api/live/speed", headers=headers, json={"speed": 60}).status_code == 409
    app_runner.step(now=ist_now())
    res = client.post("/api/live/speed", headers=headers, json={"speed": 60})
    assert res.status_code == 200 and res.json()["speed"] == 60
    assert client.post("/api/live/speed", headers=headers, json={"speed": 5}).status_code == 400
    # Another shop's speed is untouched.
    assert client.get("/api/live/status", headers=login(client, "s2")).json()["speed"] == 1


def test_dashboard_carries_a_live_block_for_today_only(client):
    headers = login(client)
    client.post("/api/live/bill", headers=headers, json={
        "event_id": "phone-0005", "lines": [{"sku": "TEA", "qty": 1}]})
    day = app_runner.shop_now("S1").date().isoformat()
    today = client.get(f"/api/dashboard?start_date={day}&end_date={day}", headers=headers)
    assert today.status_code == 200, today.text
    live = today.json()["live"]
    assert live["days_compared"] == 4 and len(live["band"]) == 24
    past = (TODAY - timedelta(days=3)).isoformat()
    other = client.get(f"/api/dashboard?start_date={past}&end_date={past}", headers=headers)
    assert other.json()["live"] is None


def test_recorded_lines_are_stored_as_json(db, shop):
    record(db, shop, [_bill("j", ts(9), qty=3)])
    row = db.exec(select(LiveEvent).where(LiveEvent.event_id == "j")).one()
    assert json.loads(row.lines) == [{"sku": "TEA", "qty": 3, "unit_price_paise": 1000}]
