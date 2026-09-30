"""Deployment settings."""
import pytest

from app.config import Settings


@pytest.mark.parametrize("given,used", [
    ("postgres://u:p@db.example.com/shop", "postgresql+psycopg://u:p@db.example.com/shop"),
    ("postgresql://u:p@db.example.com:5432/shop?sslmode=require",
     "postgresql+psycopg://u:p@db.example.com:5432/shop?sslmode=require"),
    ("postgresql+psycopg://u:p@localhost/shop", "postgresql+psycopg://u:p@localhost/shop"),
])
def test_host_database_urls_use_the_installed_driver(given, used):
    assert Settings(database_url=given, _env_file=None).database_url == used


def test_health_check(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}
