"""Phone alerts: what is raised, that it is raised once, and the Telegram bot.

Telegram itself is replaced by a fake that records what would have been sent.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.alerts import alerts as app_alerts
from app.db import get_session
from app.main import app
from app.models import AlertChat, AlertLinkCode, AlertSent, HourlyData, Store, Upload, utc_now
from app.services.alerts.rules import (
    HOURLY,
    due_alerts,
    inr,
    status_text,
    usual_close_hour,
)
from app.services.alerts.service import AlertService
from app.services.alerts.telegram import TelegramError
from app.services.auth import upsert_user
from app.services.live.clock import ist_now
from app.services.live.runner import ShopState
from app.services.live.today import today_view

TODAY = ist_now().date()
OPEN = range(8, 21)          # 8:00 to 21:00, Rs 150 an hour on a usual day
PASSWORD = "correct horse"


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute)


class FakeTelegram:
    def __init__(self, token: str = "test") -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail_for: set[int] = set()

    def get_me(self):
        return {"username": "steptosales_test_bot"}

    def get_updates(self, offset, timeout=20):
        return []

    def set_commands(self, commands):
        self.commands = commands
        return True

    def send_message(self, chat_id, text):
        if chat_id in self.fail_for:
            raise TelegramError("Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text))
        return {}


class NoRunner:
    def state(self, code):
        return None


# ---------------------------------------------------------------------------
# fixtures: two shops with four weeks of steady history
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
        s.add_all([Store(code="S1", name="Kirana"), Store(code="S2", name="Kiosk")])
        upload = Upload(filename="history.xlsx", rows=0)
        s.add(upload)
        s.commit()
        for store in s.exec(select(Store)).all():
            for back in range(1, 29):
                day = (TODAY - timedelta(days=back)).isoformat()
                s.add_all([
                    HourlyData(store_id=store.id, upload_id=upload.id, date=day, hour=h,
                               footfall=10, transactions=5, sales=150.0)
                    for h in OPEN
                ])
        s.commit()
        upsert_user(s, s.exec(select(Store).where(Store.code == "S1")).one(), "s1", PASSWORD)
        upsert_user(s, s.exec(select(Store).where(Store.code == "S2")).one(), "s2", PASSWORD)
        yield s


def store(db, code="S1") -> Store:
    return db.exec(select(Store).where(Store.code == code)).one()


def today(db, code, hours, sales=150.0, footfall=10, transactions=5):
    shop = store(db, code)
    upload = db.exec(select(Upload)).first()
    db.add_all([
        HourlyData(store_id=shop.id, upload_id=upload.id, date=TODAY.isoformat(), hour=h,
                   footfall=footfall, transactions=transactions, sales=sales)
        for h in hours
    ])
    db.commit()


@pytest.fixture
def telegram():
    return FakeTelegram()


@pytest.fixture
def service(engine, db, telegram):
    return AlertService(engine, NoRunner(), token="test", client_factory=lambda _t: telegram)


def link(db, code="S1", chat_id=111):
    db.add(AlertChat(store_id=store(db, code).id, chat_id=chat_id, title="Owner"))
    db.commit()


def view_at(db, clock, code="S1"):
    return today_view(db, store(db, code), clock)


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


def test_rupees_use_indian_grouping():
    assert inr(950) == "₹950"
    assert inr(1000) == "₹1,000"
    assert inr(123456.4) == "₹1,23,456"
    assert inr(12345678) == "₹1,23,45,678"


def test_a_usual_day_closes_after_its_last_trading_hour(db):
    today(db, "S1", range(8, 10))
    view, _ = view_at(db, at(9, 30))
    assert usual_close_hour(view) == 21


def news(view, now_hour, totals):
    """What would buzz a phone -- everything but the opt-in hourly update."""
    return [a for a in due_alerts(view, TODAY, now_hour, totals) if a.kind != HOURLY]


def test_steady_day_raises_nothing(db):
    today(db, "S1", range(8, 15))
    view, totals = view_at(db, at(14, 30))
    assert news(view, 14.5, totals) == []


def test_every_trading_hour_has_an_update_for_those_who_want_it(db):
    today(db, "S1", range(8, 15))
    view, totals = view_at(db, at(14, 30))
    [update] = [a for a in due_alerts(view, TODAY, 14.5, totals) if a.kind == HOURLY]
    assert update.key == f"{TODAY.isoformat()}T13"
    assert "13:00\u201314:00: \u20b9150 (usual \u20b9150), 5 bills from 10 visitors" in update.text
    assert "Today by 14:00: \u20b9900, about a usual" in update.text


def test_hourly_update_judges_the_hour_it_is_about(db):
    today(db, "S1", range(8, 13))
    today(db, "S1", [13], footfall=30, transactions=15, sales=600.0)   # big 13:00
    view, totals = view_at(db, at(14, 2))       # nothing yet in the 14:00 hour
    [update] = [a for a in due_alerts(view, TODAY, 14.03, totals) if a.kind == HOURLY]
    assert "Today by 14:00: \u20b91,350, 50% ahead of a usual" in update.text


def test_few_buyers_makes_a_slow_hour(db):
    today(db, "S1", range(8, 13))
    today(db, "S1", [13], footfall=12, transactions=1, sales=30.0)   # 13:00 went badly
    today(db, "S1", [14], footfall=2, transactions=1)
    view, totals = view_at(db, at(14, 20))
    [alert] = news(view, 14.33, totals)
    assert (alert.kind, alert.key) == ("slow_hour", f"{TODAY.isoformat()}T13")
    assert "Slow hour, 13:00\u201314:00: \u20b930 against about \u20b9150" in alert.text
    assert "Only 8% of the 12 who came in bought, against 50% usually" in alert.text
    assert "came in, against" not in alert.text      # as many people as usual


def test_few_visitors_makes_a_slow_hour_too(db):
    today(db, "S1", range(8, 13))
    today(db, "S1", [13], footfall=4, transactions=2, sales=60.0)
    view, totals = view_at(db, at(14, 5))
    [alert] = news(view, 14.08, totals)
    assert alert.kind == "slow_hour"
    assert "Only 4 people came in, against about 10 usually" in alert.text
    assert "who came in bought" not in alert.text    # too few to judge buying


def test_a_busy_hour_is_good_news(db):
    today(db, "S1", range(8, 13))
    today(db, "S1", [13], footfall=20, transactions=10, sales=300.0)
    view, totals = view_at(db, at(14, 5))
    [alert] = news(view, 14.08, totals)
    assert alert.kind == "busy_hour"
    assert "Busy hour, 13:00\u201314:00: \u20b9300, 2.0\u00d7 a usual 13:00" in alert.text


def test_a_strong_day_is_good_news(db):
    today(db, "S1", range(8, 13), sales=200.0)
    view, totals = view_at(db, at(12, 30))
    kinds = {a.kind: a for a in news(view, 12.5, totals)}
    assert "33% ahead of a usual" in kinds["ahead_pace"].text
    assert "behind_pace" not in kinds


def test_old_hours_are_not_news(db):
    today(db, "S1", range(8, 13))
    today(db, "S1", [13], footfall=12, transactions=1)
    today(db, "S1", [14], footfall=2, transactions=1)
    view, totals = view_at(db, at(14, 20))
    # The same data judged much later (say, found while catching up).
    assert not [a for a in due_alerts(view, TODAY, 17.5, totals)
                if a.kind in ("slow_hour", HOURLY)]


def test_behind_pace_waits_for_enough_of_the_day(db):
    today(db, "S1", range(8, 11), sales=60.0)
    view, totals = view_at(db, at(10, 30))
    assert not [a for a in due_alerts(view, TODAY, 10.5, totals) if a.kind == "behind_pace"]


def test_behind_pace_warns_with_the_numbers(db):
    today(db, "S1", range(8, 13), sales=60.0)
    view, totals = view_at(db, at(12, 30))
    [alert] = [a for a in due_alerts(view, TODAY, 12.5, totals) if a.kind == "behind_pace"]
    assert alert.key == TODAY.isoformat()
    assert "60% behind" in alert.text and "₹240 by 12:00" in alert.text


def test_summary_only_after_closing(db):
    today(db, "S1", OPEN)
    view, totals = view_at(db, at(20, 50))
    assert not [a for a in due_alerts(view, TODAY, 20.8, totals) if a.kind == "day_summary"]
    view, totals = view_at(db, at(21, 5))
    [alert] = [a for a in due_alerts(view, TODAY, 21.1, totals) if a.kind == "day_summary"]
    assert "₹1,950" in alert.text and "65 bills from 130 visitors" in alert.text


def test_status_text_reads_like_a_person(db):
    today(db, "S1", range(8, 13), sales=180.0)
    view, totals = view_at(db, at(12, 40))
    text = status_text(view, totals, at(12, 40))
    assert text.startswith("₹900 sold by 12:40")
    assert "20% ahead of a usual" in text


# ---------------------------------------------------------------------------
# the watcher
# ---------------------------------------------------------------------------


def test_an_alert_is_raised_once_and_sent_to_linked_chats(db, service, telegram, monkeypatch):
    link(db, "S1", 111)
    today(db, "S1", range(8, 13), sales=60.0)
    monkeypatch.setattr(service, "shop_clock", lambda code: at(12, 30))
    assert service.check_all() == 2          # behind pace, and the 11:00 update
    assert service.check_all() == 0          # already raised
    [(chat, text)] = telegram.sent           # the update is opt-in
    assert chat == 111 and text.startswith("S1 \u00b7 Kirana\n") and "behind" in text
    row = db.exec(select(AlertSent).where(AlertSent.kind == "behind_pace")).one()
    assert row.delivered == 1


def test_hourly_updates_go_only_to_chats_that_asked(db, service, telegram, monkeypatch):
    link(db, "S1", 111)
    db.add(AlertChat(store_id=store(db).id, chat_id=222, title="Staff", hourly=True))
    db.commit()
    today(db, "S1", range(8, 13))
    monkeypatch.setattr(service, "shop_clock", lambda code: at(12, 30))
    service.check_all()
    assert [c for c, _ in telegram.sent] == [222]
    assert "11:00\u201312:00" in telegram.sent[0][1]


def test_alerts_are_recorded_without_telegram(engine, db):
    service = AlertService(engine, NoRunner())
    today(db, "S1", range(8, 13), sales=60.0)
    service.shop_clock = lambda code: at(12, 30)
    assert service.check_all() == 2
    assert {a.delivered for a in db.exec(select(AlertSent)).all()} == {0}


def test_a_blocked_chat_does_not_stop_the_others(db, service, telegram, monkeypatch):
    link(db, "S1", 111)
    link(db, "S1", 222)
    telegram.fail_for = {111}
    today(db, "S1", range(8, 13), sales=60.0)
    monkeypatch.setattr(service, "shop_clock", lambda code: at(12, 30))
    service.check_all()
    assert [c for c, _ in telegram.sent] == [222]
    assert db.exec(select(AlertSent).where(AlertSent.kind == "behind_pace")).one().delivered == 1


def test_alerts_go_to_the_right_shop_only(db, service, telegram, monkeypatch):
    link(db, "S2", 222)
    today(db, "S1", range(8, 13), sales=60.0)
    today(db, "S2", range(8, 13))
    monkeypatch.setattr(service, "shop_clock", lambda code: at(12, 30))
    service.check_all()
    assert telegram.sent == []


def test_no_alerts_while_the_shop_catches_up(engine, db):
    class CatchingUp:
        def __init__(self, speed):
            self.shop = ShopState(store_id=1, code="S1", clock=ist_now() - timedelta(hours=3),
                                  speed=speed)

        def state(self, code):
            return self.shop

    assert AlertService(engine, CatchingUp(speed=1)).shop_clock("S1") is None
    paused = AlertService(engine, CatchingUp(speed=0))
    assert paused.shop_clock("S1") == paused.runner.shop.clock


# ---------------------------------------------------------------------------
# the bot
# ---------------------------------------------------------------------------


def message(text, chat_id=555, first_name="Amartya"):
    return {"update_id": 1, "message": {"text": text, "chat": {
        "id": chat_id, "type": "private", "first_name": first_name}}}


def test_start_with_a_code_links_the_chat_once(db, service, telegram):
    code = service.new_link_code(db, store(db, "S2")).code
    reply = service.handle_update(message(f"/start {code}"))
    assert reply.startswith("Connected to S2 · Kiosk")
    chat = db.exec(select(AlertChat)).one()
    assert (chat.chat_id, chat.title) == (555, "Amartya")
    assert telegram.sent[-1] == (555, reply)
    again = service.handle_update(message(f"/start {code}", chat_id=666))
    assert "expired or was already used" in again
    assert len(db.exec(select(AlertChat)).all()) == 1


def test_an_expired_code_links_nothing(db, service):
    db.add(AlertLinkCode(code="old", store_id=store(db).id,
                         expires_at=utc_now() - timedelta(minutes=1)))
    db.commit()
    assert "expired" in service.handle_update(message("/start old"))
    assert db.exec(select(AlertChat)).all() == []


def test_status_answers_for_the_linked_shop(db, service, monkeypatch):
    link(db, "S1", 555)
    today(db, "S1", range(8, 13), sales=180.0)
    monkeypatch.setattr(service, "shop_clock", lambda code: at(12, 40))
    reply = service.handle_update(message("/status"))
    assert reply.startswith("S1 · Kirana\n₹900 sold by 12:40")


def test_hourly_command_toggles_updates(db, service):
    link(db, "S1", 555)
    assert service.handle_update(message("/hourly")).startswith("Hourly updates on")
    assert db.exec(select(AlertChat)).one().hourly is True
    assert service.handle_update(message("/hourly")).startswith("Hourly updates off")
    assert service.handle_update(message("/hourly on")).startswith("Hourly updates on")


def test_start_reply_says_what_to_expect(db, service):
    code = service.new_link_code(db, store(db)).code
    reply = service.handle_update(message(f"/start {code}"))
    assert "an hour is busy" in reply and "/status" in reply and "/hourly" in reply


def test_status_from_a_stranger_explains_how_to_connect(service):
    assert "isn't connected" in service.handle_update(message("/status", chat_id=999))


def test_stop_unlinks_the_chat(db, service):
    link(db, "S1", 555)
    assert "won't get alerts" in service.handle_update(message("/stop"))
    assert db.exec(select(AlertChat)).all() == []


def test_the_bot_command_can_carry_its_name(db, service):
    link(db, "S1", 555)
    assert "won't get alerts" in service.handle_update(message("/stop@steptosales_test_bot"))


def test_polling_learns_the_bot_name_and_moves_the_offset(service, telegram):
    telegram.get_updates = lambda offset, timeout=20: [
        {"update_id": 41, "message": {"text": "hi", "chat": {"id": 1, "type": "private"}}},
    ]
    service.poll_once()
    assert service.bot_username == "steptosales_test_bot"
    assert [c["command"] for c in telegram.commands] == ["status", "hourly", "stop", "help"]
    assert service._offset == 42
    assert "This bot sends StepToSales alerts" in telegram.sent[-1][1]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def client(engine, db, telegram, monkeypatch):
    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr(app_alerts, "engine", engine)
    monkeypatch.setattr(app_alerts, "client", telegram)
    monkeypatch.setattr(app_alerts, "bot_username", "steptosales_test_bot")
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client, username="s1"):
    res = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.mark.parametrize("method,path", [
    ("get", "/api/alerts"),
    ("post", "/api/alerts/telegram/link"),
    ("post", "/api/alerts/test"),
    ("delete", "/api/alerts/chats/1"),
])
def test_alert_routes_need_a_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_link_opens_the_bot_with_a_code_for_my_shop(client, db):
    res = client.post("/api/alerts/telegram/link", headers=login(client, "s2"))
    body = res.json()
    assert body["url"] == f"https://t.me/steptosales_test_bot?start={body['code']}"
    assert db.get(AlertLinkCode, body["code"]).store_id == store(db, "S2").id


def test_link_needs_a_bot(client, monkeypatch):
    monkeypatch.setattr(app_alerts, "client", None)
    res = client.post("/api/alerts/telegram/link", headers=login(client))
    assert res.status_code == 400 and "not set up" in res.json()["detail"]


def test_overview_shows_only_my_chats_and_alerts(client, db):
    link(db, "S1", 111)
    link(db, "S2", 222)
    db.add(AlertSent(store_id=store(db, "S2").id, kind="behind_pace", key="k",
                     text="S2 news", shop_time=at(12)))
    db.commit()
    body = client.get("/api/alerts", headers=login(client)).json()
    assert body["telegram"] == {"configured": True, "bot_username": "steptosales_test_bot",
                                "error": None}
    assert [c["title"] for c in body["chats"]] == ["Owner"]
    assert body["recent"] == []


def test_cannot_remove_another_shops_chat(client, db):
    link(db, "S2", 222)
    other = db.exec(select(AlertChat)).one()
    assert client.delete(f"/api/alerts/chats/{other.id}", headers=login(client)).status_code == 404
    assert client.delete(f"/api/alerts/chats/{other.id}",
                         headers=login(client, "s2")).status_code == 200


def test_test_message_reaches_my_chats(client, db, telegram):
    assert client.post("/api/alerts/test", headers=login(client)).status_code == 400
    link(db, "S1", 111)
    res = client.post("/api/alerts/test", headers=login(client))
    assert res.json() == {"delivered": 1}
    chat, text = telegram.sent[-1]
    assert chat == 111 and "/status" in text and "an hour is slow" in text


def test_hourly_updates_can_be_switched_from_the_page(client, db):
    link(db, "S1", 111)
    chat = db.exec(select(AlertChat)).one()
    res = client.patch(f"/api/alerts/chats/{chat.id}", headers=login(client), json={"hourly": True})
    assert res.json()["hourly"] is True
    assert client.patch(f"/api/alerts/chats/{chat.id}", headers=login(client, "s2"),
                        json={"hourly": False}).status_code == 404


def test_page_feed_leaves_out_routine_updates(client, db):
    db.add(AlertSent(store_id=store(db).id, kind=HOURLY, key="a", text="update", shop_time=at(12)))
    db.add(AlertSent(store_id=store(db).id, kind="busy_hour", key="b", text="busy", shop_time=at(12)))
    db.commit()
    body = client.get("/api/alerts", headers=login(client)).json()
    assert [a["kind"] for a in body["recent"]] == ["busy_hour"]


# ---------------------------------------------------------------------------
# the HTTP client, against a local stand-in for api.telegram.org
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_api():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = self.path.rsplit("/", 1)[-1]
            seen.append((self.path, method, body))
            status, reply = {
                "getMe": (200, {"ok": True, "result": {"username": "shop_bot"}}),
                "getUpdates": (409, {"ok": False, "description": "Conflict: terminated by other getUpdates request"}),
                "sendMessage": (403, {"ok": False, "description": "Forbidden: bot was blocked by the user"}),
            }[method]
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_client_speaks_the_bot_api(fake_api, monkeypatch):
    from app.services.alerts import telegram as tg

    base, seen = fake_api
    monkeypatch.setattr(tg, "API", base)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    client = tg.TelegramClient("123:SECRET")
    assert client.get_me() == {"username": "shop_bot"}
    assert seen[0][0] == "/bot123:SECRET/getMe"
    with pytest.raises(tg.TelegramConflict):
        client.get_updates(7, timeout=1)
    assert seen[1][2] == {"offset": 7, "timeout": 1, "allowed_updates": ["message"]}
    with pytest.raises(tg.TelegramError, match="blocked"):
        client.send_message(42, "hello")
