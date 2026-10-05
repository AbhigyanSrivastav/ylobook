import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_database(url: str | None = None):
    url = url or os.getenv("DATABASE_URL")
    if not url:
        if os.getenv("RENDER"):
            raise RuntimeError("DATABASE_URL is required on Render; use persistent hosted Postgres.")
        # New schema: preserve the earlier prototype database without modifying it.
        url = f"sqlite:///{Path.home() / '.ylobook' / 'demo.sqlite3'}"
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    parsed = make_url(url)
    sqlite = parsed.get_backend_name() == "sqlite"
    if os.getenv("RENDER") and sqlite:
        raise RuntimeError("Render deployments require persistent Postgres, not local SQLite.")
    if sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    engine = create_engine(
        url, pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 15} if sqlite else {},
    )
    if sqlite:
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)
