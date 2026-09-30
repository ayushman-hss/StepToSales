"""Store login: who can get in, and that a login only ever sees its own shop.

Runs the real FastAPI app against an in-memory SQLite database, so no
Postgres is needed. The startup hook (which would connect to Postgres) is not
triggered because the client is not used as a context manager.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import models_pooling  # noqa: F401  -- registers pooling tables
from app.db import get_session
from app.main import app
from app.models import (
    AuthSession,
    BundleSuggestion,
    HourlyData,
    Product,
    Store,
    StoreUser,
    Upload,
    utc_now,
)
from app.models_pooling import (
    BuyingPool,
    PoolEvent,
    PoolOrder,
    PoolProduct,
    PriceList,
    PriceTier,
    Supplier,
)
from app.services.auth import (
    hash_password,
    normalise_username,
    upsert_user,
    verify_password,
)

PASSWORD = "correct-horse"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _hours(store_id: int, upload_id: int, footfall: int) -> list[HourlyData]:
    return [
        HourlyData(
            store_id=store_id, upload_id=upload_id, date=day, hour=hour,
            footfall=footfall, transactions=footfall // 2, sales=100.0 * footfall,
        )
        for day in ("2026-09-01", "2026-09-02")
        for hour in (9, 10, 11)
    ]


@pytest.fixture
def db(engine):
    """Two shops with different numbers, a login each, and a shared pool."""
    with Session(engine) as s:
        s1, s2 = Store(code="S1", name="Kirana"), Store(code="S2", name="Kiosk")
        s.add_all([s1, s2])
        s.commit()
        upload = Upload(filename="seed.xlsx", rows=12)
        s.add(upload)
        s.commit()
        s.add_all(_hours(s1.id, upload.id, 10) + _hours(s2.id, upload.id, 40))
        s.add_all([
            Product(store_id=s1.id, sku="A", name="Tea", cost_price=8, sell_price=10),
            Product(store_id=s2.id, sku="B", name="Cola", cost_price=16, sell_price=20),
        ])
        s.add(BundleSuggestion(
            store_id=s2.id, sku_a="B", sku_b="C",
            transactions_with_both=5, transactions_with_a=9, transactions_with_b=7,
            total_transactions=50, confidence=0.5, lift=2.0,
            separate_price=30, separate_cost=24, suggested_price=28,
            suggested_margin_pct=0.14, margin_floor_pct=0.1,
        ))

        supplier = Supplier(code="SUP1", name="Wholesale")
        pool = BuyingPool(code="test", name="Test pool", status="open")
        s.add_all([supplier, pool])
        s.commit()
        price_list = PriceList(
            supplier_id=supplier.id, sku="SUGAR", version="v1", valid_from="2026-09-01",
        )
        s.add(price_list)
        s.commit()
        s.add_all([
            PriceTier(price_list_id=price_list.id, min_qty=1, max_qty=19, unit_price=4500),
            PriceTier(price_list_id=price_list.id, min_qty=20, max_qty=None, unit_price=4000),
            PoolProduct(pool_id=pool.id, sku="SUGAR", price_list_id=price_list.id),
            PoolOrder(pool_id=pool.id, store_id=s2.id, sku="SUGAR", qty=15),
        ])
        s.commit()

        upsert_user(s, s1, "s1", PASSWORD)
        upsert_user(s, s2, "s2", PASSWORD)
        yield s


@pytest.fixture
def client(engine, db):
    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client: TestClient, username: str = "s1", password: str = PASSWORD) -> dict:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


# ---------------------------------------------------------------------------
# password hashing
# ---------------------------------------------------------------------------


def test_hash_round_trips_and_is_salted():
    a, b = hash_password("secret-1"), hash_password("secret-1")
    assert a != b
    assert verify_password("secret-1", a)
    assert not verify_password("secret-2", a)


@pytest.mark.parametrize("stored", ["", "garbage", "md5$1$salt$abc", "pbkdf2_sha256$x$s$h"])
def test_malformed_hash_never_verifies(stored):
    assert not verify_password("anything", stored)


def test_usernames_are_case_and_space_insensitive():
    assert normalise_username("  S1 ") == "s1"


def test_upsert_rejects_short_passwords_and_cross_shop_names(db):
    s1 = db.exec(select(Store).where(Store.code == "S1")).one()
    s2 = db.exec(select(Store).where(Store.code == "S2")).one()
    with pytest.raises(ValueError, match="at least"):
        upsert_user(db, s1, "new", "short")
    with pytest.raises(ValueError, match="another shop"):
        upsert_user(db, s2, "s1", PASSWORD)


# ---------------------------------------------------------------------------
# login / me / logout
# ---------------------------------------------------------------------------


def test_login_returns_token_and_shop(client):
    res = client.post("/api/auth/login", json={"username": " S1 ", "password": PASSWORD})
    assert res.status_code == 200
    body = res.json()
    assert body["store_code"] == "S1"
    assert body["store_name"] == "Kirana"
    assert len(body["token"]) > 30


def test_token_is_not_stored_in_plain_text(client, db):
    token = login(client)["Authorization"].removeprefix("Bearer ")
    stored = [r.token_hash for r in db.exec(select(AuthSession)).all()]
    assert stored and token not in stored


@pytest.mark.parametrize(
    "username,password", [("s1", "wrong-password"), ("nobody", PASSWORD)]
)
def test_bad_credentials_get_the_same_401(client, username, password):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 401
    assert res.json()["detail"] == "Wrong username or password"


def test_me_requires_a_token(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"


def test_me_rejects_an_unknown_token(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer made-up"})
    assert res.status_code == 401


def test_me_names_the_logged_in_shop(client):
    res = client.get("/api/auth/me", headers=login(client, "s2"))
    assert res.json() == {"store_code": "S2", "store_name": "Kiosk"}


def test_logout_reads_the_header_and_ends_the_session(client):
    headers = login(client)
    assert client.post("/api/auth/logout", headers=headers).json() == {"ok": True}
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_without_a_token_still_succeeds(client):
    assert client.post("/api/auth/logout").status_code == 200


def test_expired_session_is_refused_and_removed(client, db):
    headers = login(client)
    row = db.exec(select(AuthSession)).one()
    row.expires_at = utc_now() - timedelta(seconds=1)
    db.add(row)
    db.commit()

    assert client.get("/api/auth/me", headers=headers).status_code == 401
    db.expire_all()
    assert db.exec(select(AuthSession)).all() == []


def test_changing_a_password_signs_that_user_out(client, db):
    headers = login(client)
    s1 = db.exec(select(Store).where(Store.code == "S1")).one()
    upsert_user(db, s1, "s1", "a-new-password")
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    login(client, "s1", "a-new-password")


# ---------------------------------------------------------------------------
# every shop route needs a login
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/dashboard"),
        ("get", "/api/stores"),
        ("post", "/api/upload"),
        ("get", "/api/products"),
        ("post", "/api/products/upload"),
        ("get", "/api/bundles"),
        ("post", "/api/bundles/generate"),
        ("post", "/api/bundles/upload-lines"),
        ("post", "/api/bundles/1/approve"),
        ("post", "/api/bundles/1/reject"),
        ("get", "/api/pools"),
        ("get", "/api/pools/test"),
        ("post", "/api/pools/test/orders"),
        ("post", "/api/pools/test/withdraw"),
        ("post", "/api/pools/test/close"),
        ("post", "/api/pools/test/reopen"),
        ("get", "/api/pools/test/events"),
    ],
)
def test_shop_routes_refuse_anonymous_requests(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_health_stays_public(client):
    assert client.get("/api/health").status_code == 200


# ---------------------------------------------------------------------------
# a login sees only its own shop
# ---------------------------------------------------------------------------


def test_dashboard_is_scoped_to_the_logged_in_shop(client):
    params = {"start_date": "2026-09-01", "end_date": "2026-09-02"}
    s1 = client.get("/api/dashboard", params=params, headers=login(client, "s1"))
    s2 = client.get("/api/dashboard", params=params, headers=login(client, "s2"))
    assert s1.status_code == s2.status_code == 200
    # 6 hours each: 10 visitors an hour at S1, 40 at S2.
    assert s1.json()["kpis"]["total_footfall"] == 60
    assert s2.json()["kpis"]["total_footfall"] == 240


@pytest.mark.parametrize("asked_for", ["S2", "all"])
def test_naming_another_shop_in_the_url_changes_nothing(client, asked_for):
    """The shop comes from the session; an old store_id parameter is ignored."""
    params = {"store_id": asked_for, "start_date": "2026-09-01", "end_date": "2026-09-02"}
    res = client.get("/api/dashboard", params=params, headers=login(client))
    assert res.json()["kpis"]["total_footfall"] == 60


def test_stores_lists_only_my_shop(client):
    res = client.get("/api/stores", headers=login(client, "s2"))
    assert res.json() == [{"code": "S2", "name": "Kiosk"}]


def test_products_are_my_shop_only(client):
    headers = login(client)
    for url in ("/api/products", "/api/products?store_id=S2"):
        assert [p["sku"] for p in client.get(url, headers=headers).json()] == ["A"]


def test_bundles_of_another_shop_are_invisible(client, db):
    headers = login(client)
    assert client.get("/api/bundles", headers=headers).json() == []
    assert client.get("/api/bundles?store_id=S2", headers=headers).json() == []

    other = db.exec(select(BundleSuggestion)).one()
    for action in ("approve", "reject"):
        res = client.post(f"/api/bundles/{other.id}/{action}", json={}, headers=headers)
        assert res.status_code == 404
    db.refresh(other)
    assert other.status == "pending"


def test_owner_can_decide_on_their_bundle(client, db):
    other = db.exec(select(BundleSuggestion)).one()
    res = client.post(
        f"/api/bundles/{other.id}/approve", json={"price": 27}, headers=login(client, "s2")
    )
    assert res.status_code == 200
    db.refresh(other)
    assert (other.status, other.approved_price) == ("approved", 27)


# ---------------------------------------------------------------------------
# the pool is shared, orders are not
# ---------------------------------------------------------------------------


def test_every_member_sees_the_whole_pool(client):
    res = client.get("/api/pools/test", headers=login(client))
    assert res.status_code == 200
    assert [s["store"] for s in res.json()["stores"]] == ["S2"]


def test_orders_are_placed_as_the_logged_in_shop(client, db):
    res = client.post(
        "/api/pools/test/orders", json={"sku": "SUGAR", "qty": 10}, headers=login(client)
    )
    assert res.status_code == 200, res.text
    assert sorted(s["store"] for s in res.json()["stores"]) == ["S1", "S2"]
    # 25 units together crosses into the 40.00 tier.
    assert res.json()["products"][0]["pooled_unit_price"] == 4000
    actors = [e.actor for e in db.exec(select(PoolEvent)).all()]
    assert actors == ["S1"]


def test_cannot_order_or_withdraw_for_another_shop(client, db):
    headers = login(client)
    order = client.post(
        "/api/pools/test/orders",
        json={"store_id": "S2", "sku": "SUGAR", "qty": 50},
        headers=headers,
    )
    withdraw = client.post("/api/pools/test/withdraw", json={"store_id": "S2"}, headers=headers)
    assert order.status_code == withdraw.status_code == 403
    assert db.exec(select(PoolOrder)).one().qty == 15


# ---------------------------------------------------------------------------
# uploads land in the uploader's shop only
# ---------------------------------------------------------------------------


def _xlsx(rows: list[dict]) -> bytes:
    import io

    import pandas as pd

    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def test_hours_upload_keeps_only_my_rows(client, db):
    row = {"date": "2026-09-03", "hour": 9, "footfall": 7, "transactions": 3, "sales": 300}
    body = _xlsx([{**row, "store_id": "S1"}, {**row, "store_id": "S2"}])
    res = client.post(
        "/api/upload",
        files={"file": ("hours.xlsx", body)},
        headers=login(client),
    )
    assert res.status_code == 200, res.text
    assert res.json()["rows"] == 1
    assert res.json()["skipped_rows"] == 1

    new = db.exec(select(HourlyData).where(HourlyData.date == "2026-09-03")).all()
    s1 = db.exec(select(Store).where(Store.code == "S1")).one()
    assert [(h.store_id, h.footfall) for h in new] == [(s1.id, 7)]


def test_hours_file_without_a_shop_column_is_mine(client, db):
    row = {"date": "2026-09-04", "hour": 9, "footfall": 5, "transactions": 2, "sales": 200}
    res = client.post(
        "/api/upload",
        files={"file": ("hours.xlsx", _xlsx([row]))},
        headers=login(client, "s2"),
    )
    assert res.status_code == 200, res.text
    s2 = db.exec(select(Store).where(Store.code == "S2")).one()
    new = db.exec(select(HourlyData).where(HourlyData.date == "2026-09-04")).one()
    assert new.store_id == s2.id


def test_hours_file_for_another_shop_only_is_refused(client):
    row = {"date": "2026-09-05", "hour": 9, "footfall": 5, "transactions": 2,
           "sales": 200, "store_id": "S2"}
    res = client.post(
        "/api/upload",
        files={"file": ("hours.xlsx", _xlsx([row]))},
        headers=login(client),
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "File contains no rows for your store"


def test_users_are_stored_lower_case(db):
    assert sorted(u.username for u in db.exec(select(StoreUser)).all()) == ["s1", "s2"]
