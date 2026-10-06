"""Developer-only destructive reset for the shared Ylobook demo database."""

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError

from ylobook_backend.database import make_database
from ylobook_backend.models import Agent, ContactRequest, Conversation, Message


def reset_demo(database_url: str | None = None) -> dict[str, int]:
    """Delete network records while preserving the database schema."""
    engine, sessions = make_database(database_url)
    try:
        with sessions.begin() as db:
            counts = {}
            for model in (Message, Conversation, ContactRequest, Agent):
                counts[model.__tablename__] = db.query(model).delete(synchronize_session=False)
        return counts
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset all Ylobook demo network data.")
    parser.add_argument(
        "--confirm", action="store_true",
        help="confirm the destructive reset (required for non-interactive use)",
    )
    args = parser.parse_args()
    print("WARNING: this permanently deletes all agents, requests, conversations, and messages "
          "from the configured Ylobook database.")
    if not args.confirm:
        answer = input("Type RESET to continue: ").strip()
        if answer != "RESET":
            print("Reset cancelled.")
            return
    try:
        counts = reset_demo()
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        print(f"Reset failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print("Ylobook demo reset complete; schema was preserved.")
    for table, count in counts.items():
        print(f"  {table}: {count} deleted")


if __name__ == "__main__":
    main()
