"""The shop assistant: plain questions in, answers from the shop's own data."""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.alerts import alerts as app_alerts
from app.db import get_session
from app.main import app
from app.models import AlertChat, HourlyData, Product, SaleLine, Store, Upload
from app.services.alerts.service import AlertService
from app.services.assistant import parse as P
from app.services.assistant.answers import answer
from app.services.auth import upsert_user
from app.services.live.clock import ist_now

TODAY = ist_now().date()
OPEN = range(8, 21)
PASSWORD = "correct horse"
# A Wednesday, so weekday rules are testable whatever day the suite runs.
WED = date(2026, 9, 30)


def at(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


# ---------------------------------------------------------------------------
# understanding the question
# ---------------------------------------------------------------------------

CATALOGUE = [
    P.CatalogueItem("TEA", "Tea", "Tea"),
    P.CatalogueItem("GREENTEA", "Vedic Suraksha Green Tea", "Vedic Suraksha Green Tea"),
    P.CatalogueItem("MAGGI", "2-Minute Instant Masala Noodles - Made With Quality Spices",
                    "2-Minute Instant Masala Noodles"),
    P.CatalogueItem("HAKKA", "Veg Hakka Noodles - Authentic Chinese", "Veg Hakka Noodles"),
    P.CatalogueItem("COLA", "Soft Drink", "Soft Drink"),
    P.CatalogueItem("BLACKCOLA", "Black Soft Drink - Max Taste, Zero Sugar(Diet)", "Black Soft Drink"),
    P.CatalogueItem("PANEER", "Paneer - Premium Fresh", "Paneer"),
    P.CatalogueItem("OIL", "Organic - Mustard Oil", "Mustard Oil (Organic)"),
    P.CatalogueItem("POHA", "White Thick Poha - For Breakfast & Evening Tea", "White Thick Poha"),
]


def ask(text: str) -> P.Query:
    return P.parse(text, WED, CATALOGUE)


@pytest.mark.parametrize("text,intent", [
    ("how much was sold today?", P.SALES),
    ("What's the total sale today", P.SALES),
    ("aaj kitna becha", P.SALES),
    ("kal ki sale", P.SALES),
    ("what was sold most today?", P.TOP),
    ("sabse zyada kya bika", P.TOP),
    ("which products are not selling", P.BOTTOM),
    ("what should I do to improve sales?", P.ADVICE),
    ("tips to increase profit", P.ADVICE),
    ("how many people came in today", P.VISITORS),
    ("kitne log aaye aaj", P.VISITORS),
    ("how many bills yesterday", P.BILLS),
    ("what's my conversion rate this week", P.CONVERSION),
    ("average bill last 7 days", P.AVG_BILL),
    ("profit today", P.PROFIT),
    ("busiest hour", P.PEAK_HOUR),
    ("what time do most customers come", P.PEAK_HOUR),
    ("when is my shop quietest", P.QUIET_HOUR),
    ("which day is my best day", P.BEST_DAY),
    ("how is today going", P.STATUS),
    ("any combo suggestions?", P.BUNDLES),
    ("give me a report for last month", P.SUMMARY),
    ("yesterday?", P.SUMMARY),
    ("compare today with yesterday", P.COMPARE),
    ("how are sales compared to last week", P.COMPARE),
    ("what is the stock situation", P.STOCK),
    ("hi", P.GREETING),
    ("ok thanks", P.THANKS),
    ("what can you do", P.HELP),
    ("turn on hourly updates", P.HOURLY_ON),
    ("stop hourly updates", P.HOURLY_OFF),
    ("is it raining", P.UNKNOWN),
    ("how much money came in this week", P.SALES),
    ("did we do better than yesterday", P.COMPARE),
    ("show me today's numbers", P.SUMMARY),
    ("sabse kam kya bika is hafte", P.BOTTOM),
    ("kya karu sales badhane ke liye", P.ADVICE),
    ("when should I run an offer", P.OFFER),
    ("should I open earlier?", P.OPENING),
    ("biggest bill today", P.BIG_BILL),
    ("which days are slow", P.BEST_DAY),
    ("how many customers came yesterday evening", P.VISITORS),
    ("was yesterday a good day", P.SUMMARY),
    ("how much butter is left", P.STOCK),
])
def test_understands_plain_questions(text, intent):
    assert ask(text).intent == intent


def test_one_answer_per_question_not_two():
    assert ask("how many customers came yesterday evening").intents == [P.VISITORS]
    assert ask("how many people left without buying").intents == [P.VISITORS]


@pytest.mark.parametrize("text,intent", [
    ("sales in september", P.SALES),
])
def test_month_names(text, intent):
    q = ask(text)
    assert q.intent == intent
    assert (q.period.start, q.period.end, q.period.label) == (date(2026, 9, 1), WED, "this month")
    aug = ask("revenue for august").period
    assert (aug.start, aug.end, aug.label) == (date(2026, 8, 1), date(2026, 8, 31), "August")



@pytest.mark.parametrize("text,start,end,label", [
    ("sales today", WED, WED, "today"),
    ("sales yesterday", date(2026, 9, 29), date(2026, 9, 29), "yesterday"),
    ("day before yesterday", date(2026, 9, 28), date(2026, 9, 28), "Mon 28 Sep"),
    ("this week", date(2026, 9, 28), WED, "this week"),
    ("last week", date(2026, 9, 21), date(2026, 9, 27), "last week"),
    ("this month", date(2026, 9, 1), WED, "this month"),
    ("last month", date(2026, 8, 1), date(2026, 8, 31), "last month (August)"),
    ("last 7 days", date(2026, 9, 24), WED, "the last 7 days"),
    ("sales on monday", date(2026, 9, 28), date(2026, 9, 28), "Mon 28 Sep"),
    ("last wednesday", date(2026, 9, 23), date(2026, 9, 23), "Wed 23 Sep"),
    ("sales on 25 sept", date(2026, 9, 25), date(2026, 9, 25), "Fri 25 Sep"),
    ("sales on 25/9", date(2026, 9, 25), date(2026, 9, 25), "Fri 25 Sep"),
    ("what about 5 oct", date(2025, 10, 5), date(2025, 10, 5), "Sun 5 Oct"),   # not yet: last year
])
def test_reads_when(text, start, end, label):
    period = ask(text).period
    assert (period.start, period.end, period.label) == (start, end, label)


@pytest.mark.parametrize("text,hours", [
    ("sales in the evening", (16, 20)),
    ("how many people came in the morning", (6, 12)),
    ("sales tonight", (20, 24)),
    ("how many came at 6pm", (18, 19)),
    ("sales at 6", (18, 19)),
    ("between 5 and 8 pm", (17, 20)),
    ("from 10 am to 1 pm", (10, 13)),
])
def test_reads_hours(text, hours):
    assert ask(text).hours == hours


@pytest.mark.parametrize("text,skus", [
    ("how many maggi sold today", ["MAGGI"]),
    ("how much tea", ["TEA"]),                  # the product called just "Tea"
    ("green tea sales", ["GREENTEA"]),
    ("black soft drink", ["BLACKCOLA"]),
    ("soft drink", ["COLA"]),
    ("noodles sold last week", ["HAKKA", "MAGGI"]),
    ("how many cold drinks today", ["COLA"]),
    ("paneer this month", ["PANEER"]),
    ("tel ki bikri", ["OIL"]),
    ("paneer vs butter this week", ["PANEER"]),  # butter is not in this catalogue
    ("maggi vs hakka noodles", ["HAKKA", "MAGGI"]),
    ("sales in the evening", []),               # "evening" is in the poha's name
    ("what sold most today", []),
])
def test_finds_products(text, skus):
    assert sorted(ask(text).products) == sorted(skus)


def test_ranking_options():
    q = ask("top 3 products this month by revenue")
    assert (q.intent, q.limit, q.rank_by) == (P.TOP, 3, "revenue")
    assert ask("most profitable products").rank_by == "profit"


def test_short_names_are_what_people_say():
    class Row:
        def __init__(self, sku, name):
            self.sku, self.name = sku, name

    items = P.build_catalogue([
        Row("A", "Butter - Pasteurised"),
        Row("B", "Organic - Mustard Oil"),
        Row("C", "Sunrise Instant Coffee"),
        Row("D", "Sunrise Instant Coffee - Chicory Mixture"),
    ])
    assert [i.short for i in items] == [
        "Butter", "Mustard Oil (Organic)", "Sunrise Instant Coffee",
        "Sunrise Instant Coffee (Chicory Mixture)",
    ]


# ---------------------------------------------------------------------------
# answers from data: four weeks of steady trade, Rs 150 an hour
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
            Product(store_id=shop.id, sku="RUSK", name="Rusk-Milk", cost_price=15, sell_price=20),
            Product(store_id=shop.id, sku="MAGGI",
                    name="2-Minute Instant Masala Noodles - Made With Quality Spices",
                    cost_price=12, sell_price=14),
        ])
        s.commit()
        upsert_user(s, shop, "s1", PASSWORD)
        upsert_user(s, other, "s2", PASSWORD)
        tx = 0
        for back in range(1, 29):
            day = (TODAY - timedelta(days=back)).isoformat()
            for hour in OPEN:
                s.add(HourlyData(store_id=shop.id, upload_id=upload.id, date=day, hour=hour,
                                 footfall=10, transactions=5, sales=150.0))
                for _ in range(5):
                    tx += 1
                    for sku, price in (("TEA", 10.0), ("RUSK", 20.0)):
                        s.add(SaleLine(store_id=shop.id, upload_id=upload.id, date=day, hour=hour,
                                       transaction_id=f"T{tx}", sku=sku, qty=1, unit_price=price))
        s.commit()
        yield s


def store(db, code="S1") -> Store:
    return db.exec(select(Store).where(Store.code == code)).one()


def trade_today(db, hours, per_bill=(("TEA", 10.0), ("RUSK", 20.0)), bills=5, footfall=10):
    shop = store(db)
    upload = db.exec(select(Upload)).first()
    tx = 0
    for hour in hours:
        amount = sum(p for _, p in per_bill) * bills
        db.add(HourlyData(store_id=shop.id, upload_id=upload.id, date=TODAY.isoformat(),
                          hour=hour, footfall=footfall, transactions=bills, sales=amount))
        for _ in range(bills):
            tx += 1
            for sku, price in per_bill:
                db.add(SaleLine(store_id=shop.id, upload_id=upload.id, date=TODAY.isoformat(),
                                hour=hour, transaction_id=f"TODAY{hour}-{tx}", sku=sku, qty=1,
                                unit_price=price))
    db.commit()


def reply(db, text, clock=None, code="S1", **kw):
    return answer(db, store(db, code), text, clock or at(14, 0), **kw)


def test_sales_today_against_a_usual_day_by_the_same_time(db):
    trade_today(db, range(8, 14))
    text = reply(db, "how much did I sell today?")
    assert text.startswith("Today so far (till 14:00): ₹900 from 30 bills (60 items).")
    assert "About the same as a usual" in text and "by this time (₹900)" in text


def test_a_slow_morning_says_by_how_much(db):
    trade_today(db, range(8, 14), bills=3, footfall=10)
    text = reply(db, "aaj kitna becha")
    assert "₹540 from 18 bills" in text and "40% below a usual" in text


def test_nothing_sold_yet(db):
    assert reply(db, "sales today", clock=at(7, 30)) == "Nothing sold today so far (till 07:30)."


def test_yesterday_is_a_whole_day(db):
    text = reply(db, "kal ki sale")
    assert text.startswith("Yesterday: ₹1,950 from 65 bills (130 items).")


def test_visitors_and_buying_rate(db):
    trade_today(db, range(8, 14))
    assert "60 people came in and 30 bought (50%)" in reply(db, "how many people came in today")
    assert "50% of visitors bought (30 of 60)" in reply(db, "what's my conversion today")


def test_evening_that_has_not_started(db):
    trade_today(db, range(8, 14))
    assert "hasn't come yet today" in reply(db, "sales this evening")


def test_best_sellers_today(db):
    trade_today(db, range(8, 14))
    trade_today(db, [13], per_bill=(("MAGGI", 14.0),), bills=2, footfall=0)
    text = reply(db, "what was sold most today?")
    assert text.splitlines()[1:] == [
        "1. Rusk-Milk: 30 sold, ₹600",
        "2. Tea: 30 sold, ₹300",
        "3. 2-Minute Instant Masala Noodles: 2 sold, ₹28",
    ]


def test_a_named_product(db):
    trade_today(db, [13], per_bill=(("MAGGI", 14.0),), bills=2, footfall=0)
    text = reply(db, "how many maggi did I sell today")
    assert text.startswith("2-Minute Instant Masala Noodles today so far (till 14:00): 2 sold in 2 bills")
    assert "Sells at ₹14 each." in text


def test_price_and_margin(db):
    assert reply(db, "margin on rusk") == \
        "Rusk-Milk: sells at ₹20, costs you ₹15, so you make ₹5 each (25%)."


def test_profit(db):
    text = reply(db, "profit yesterday")
    # 65 bills x (Rs 2 on tea + Rs 5 on rusk)
    assert text.startswith("Yesterday: about ₹455 gross profit on ₹1,950 of sales (23% margin).")


def test_compare_two_days_like_with_like(db):
    trade_today(db, range(8, 14), bills=6, footfall=10)
    text = reply(db, "compare today with yesterday")
    lines = text.splitlines()
    assert lines[0].startswith("Today so far (till 14:00): ₹1,080 from 36 bills")
    assert lines[1].startswith("Yesterday by the same time: ₹900 from 30 bills")
    assert lines[2] == "Sales are 20% up (+₹180)."
    assert lines[3] == "More of them bought (60% against 50%)."


def test_advice_is_built_from_the_numbers(db):
    trade_today(db, range(8, 14))
    text = reply(db, "what should I do to improve sales?")
    assert text.startswith("Here's what your numbers suggest:\n1. ")
    assert "Rusk-Milk is your best seller" in text or "Tea is your best seller" in text


def test_busiest_hour_needs_no_date(db):
    assert reply(db, "busiest hour").startswith("Busiest hour on an average day over the last 4 weeks")


def test_greeting_and_unknown(db):
    assert reply(db, "hello").startswith("Namaste!")
    assert reply(db, "is it raining").startswith("Sorry, I didn't catch that.")


def test_hourly_updates_by_asking(db):
    calls = []
    text = reply(db, "please send hourly updates", set_hourly=lambda on: calls.append(on) or "done")
    assert calls == [True] and text == "done"
    assert "Phone alerts page" in reply(db, "hourly updates on")          # the web page


def test_answers_are_for_the_asking_shop_only(db):
    assert reply(db, "sales yesterday", code="S2") == "Nothing sold yesterday."


# ---------------------------------------------------------------------------
# the bot and the page
# ---------------------------------------------------------------------------


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class NoRunner:
    def state(self, code):
        return None


def message(text, chat_id=555):
    return {"update_id": 1, "message": {"text": text, "chat": {"id": chat_id, "type": "private"}}}


def test_the_bot_answers_plain_questions(engine, db, monkeypatch):
    telegram = FakeTelegram()
    service = AlertService(engine, NoRunner(), token="t", client_factory=lambda _t: telegram)
    monkeypatch.setattr(service, "shop_clock", lambda code: at(14, 0))
    db.add(AlertChat(store_id=store(db).id, chat_id=555, title="Owner"))
    db.commit()
    trade_today(db, range(8, 14))
    text = service.handle_update(message("How much did I sell today?"))
    assert text.startswith("Today so far (till 14:00): ₹900")
    assert telegram.sent[-1] == (555, text)
    assert service.handle_update(message("hourly updates on")).startswith("Hourly updates on")
    assert db.exec(select(AlertChat)).one().hourly is True


def test_the_bot_asks_strangers_to_connect_first(engine, db):
    service = AlertService(engine, NoRunner())
    assert "isn't connected" in service.handle_update(message("sales today", chat_id=999))


@pytest.fixture
def client(engine, db, monkeypatch):
    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr(app_alerts, "shop_clock", lambda code: at(14, 0))
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client, username="s1"):
    res = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_ask_from_the_page(client, db):
    assert client.post("/api/assistant/ask", json={"question": "sales"}).status_code == 401
    res = client.post("/api/assistant/ask", headers=login(client),
                      json={"question": "sales yesterday"})
    assert res.json()["answer"].startswith("Yesterday: ₹1,950")
    other = client.post("/api/assistant/ask", headers=login(client, "s2"),
                        json={"question": "sales yesterday"})
    assert other.json()["answer"] == "Nothing sold yesterday."
