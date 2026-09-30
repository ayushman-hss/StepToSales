"""Get the database ready before the API starts (used by the container).

* A brand-new database gets the demo data (reset_demo) and is marked as
  up to date with the migrations.
* An existing one is migrated to the latest schema.

Safe to run on every start: the demo data is only loaded once, so a restart
or a redeploy keeps today's live trading, alerts and connected phones.

    cd backend && python scripts/boot.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.db import engine  # noqa: E402


def main() -> None:
    cfg = Config(str(HERE.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE.parent / "alembic"))

    with engine.connect() as conn:
        insp = inspect(conn)
        has_data = insp.has_table("hourly_data") and bool(
            conn.execute(text("SELECT count(*) FROM hourly_data")).scalar()
        )
        tracked = insp.has_table("alembic_version")

    if has_data:
        if tracked:
            print("boot: existing database, applying migrations", flush=True)
            command.upgrade(cfg, "head")
        else:
            # Made by the API's create_all(), never by migrations: already current.
            print("boot: existing database without migration history, marking it current",
                  flush=True)
            command.stamp(cfg, "head")
        return

    print("boot: empty database, loading the demo data (about a minute)", flush=True)
    import reset_demo
    reset_demo.main()
    command.stamp(cfg, "head")
    print("boot: demo data loaded", flush=True)


if __name__ == "__main__":
    main()
