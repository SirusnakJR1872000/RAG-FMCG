"""Create an administrator account (PROJECT_SPEC §24.1; the first admin cannot be made in the UI).

Usage (from backend/):  python -m scripts.create_admin [--username admin] [--full-name "..."]

The password is typed at a hidden prompt, never passed on the command line (it would stay in
the shell history). It must satisfy the password policy (§13.2). The admin chose it themselves,
so it is not marked "must change"; the event is recorded as created by the system account.
"""

import argparse
import getpass
import sys
from collections.abc import Callable

from sqlalchemy import update

from audit.writer import Actor
from auth import passwords, service
from config import Settings, get_settings
from database.init_db import SYSTEM_USER_ID, init_db
from database.models import users
from database.session import Database

SYSTEM = Actor(SYSTEM_USER_ID, "system", "system")


def create_admin(db: Database, settings: Settings, username: str, full_name: str,
                 password: str) -> dict:
    """Create the account; raises ValueError (with a readable message) if it can't."""
    username = service.normalise_username(username)
    problems = passwords.check_policy(password, username=username,
                                      min_length=settings.password_min_length, recent_hashes=[])
    if problems:
        raise ValueError("The password is not acceptable: " + ", ".join(problems))
    with db.write() as conn:
        if service.get_user_by_username(conn, username):
            raise ValueError(f"The username '{username}' already exists.")
        user = service.create_user(conn, username=username, full_name=full_name, role="admin",
                                   password=password, created_by=SYSTEM_USER_ID, actor=SYSTEM)
        conn.execute(update(users).where(users.c.id == user["id"]).values(
            must_change_password=0))
    return user


def main(argv: list[str] | None = None,
         read_password: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description="Create an administrator account.")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--full-name", default="Administrator")
    args = parser.parse_args(argv)
    settings = get_settings()
    password = read_password("Password: ")
    if password != read_password("Repeat password: "):
        print("The two passwords differ.", file=sys.stderr)
        return 1
    db = Database(settings.sqlite_path)
    try:
        init_db(db)
        user = create_admin(db, settings, args.username, args.full_name, password)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        db.dispose()
    print(f"Created admin '{user['username']}'. Sign in at the web app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
