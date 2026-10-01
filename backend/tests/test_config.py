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


def test_website_is_revalidated_and_hashed_assets_are_cached(tmp_path, monkeypatch):
    # After a deploy, browsers must pick up the new index.html at once; the
    # hashed files it points to never change, so they may be kept forever.
    import importlib

    from fastapi.testclient import TestClient

    import app.main
    from app.config import settings

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    monkeypatch.setattr(settings, "static_dir", str(tmp_path))
    try:
        client = TestClient(importlib.reload(app.main).app)
        for page in ("/", "/dashboard"):
            res = client.get(page)
            assert res.text == "<html>app</html>"
            assert res.headers["cache-control"] == "no-cache"
        res = client.get("/assets/index-abc123.js")
        assert "immutable" in res.headers["cache-control"]
        assert client.get("/api/nothing").status_code == 404
    finally:
        monkeypatch.undo()
        importlib.reload(app.main)


def test_locks_keep_up_with_the_requirements():
    # Docker and CI install the hashed locks, not requirements.txt: a package
    # added or bumped there must reach the locks too, or the deploy misses it.
    import re
    from pathlib import Path

    here = Path(__file__).resolve().parents[1]

    def names(path, pinned_only=False):
        out = {}
        for line in (here / path).read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            m = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*(==\s*([^\s;\\]+))?", line)
            if m and not line.startswith("-"):
                out[re.sub(r"[-_.]+", "-", m.group(1).lower())] = m.group(3)
        return out

    app, dev = names("requirements.txt"), names("requirements-dev.txt")
    lock, dev_lock = names("requirements.lock"), names("requirements-dev.lock")
    for name, version in app.items():
        assert lock.get(name) == version, f"{name} in requirements.lock"
        assert dev_lock.get(name) == version, f"{name} in requirements-dev.lock"
    for name in dev:
        assert name in dev_lock, f"{name} in requirements-dev.lock"
    # Shared packages resolve to the same version in both locks.
    assert all(dev_lock[n] == v for n, v in lock.items()), "locks disagree"
