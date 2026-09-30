"""Create a shop login, or reset its password.

    cd backend && python scripts/create_user.py S1 ramesh
    cd backend && python scripts/create_user.py S1 ramesh --password 'long-secret'

Without --password you are prompted, so the password stays out of shell
history. Resetting a password signs that login out everywhere.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.models import Store  # noqa: E402
from app.services.auth import upsert_user  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("store", help="shop code, e.g. S1")
    parser.add_argument("username")
    parser.add_argument("--password", help="omit to be prompted")
    args = parser.parse_args(argv)

    password = args.password
    if password is None:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Again: "):
            print("Passwords did not match.", file=sys.stderr)
            return 1

    init_db()
    with Session(engine) as session:
        store = session.exec(select(Store).where(Store.code == args.store)).first()
        if store is None:
            print(f"No shop with code {args.store!r}.", file=sys.stderr)
            return 1
        try:
            user = upsert_user(session, store, args.username, password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"{user.username} can now log in to {store.code}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
