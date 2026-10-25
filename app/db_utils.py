import os
from urllib.parse import urlparse

from sqlalchemy import create_engine, text


def _normalize_url(database_url):
    return database_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def ensure_database_exists(database_url):
    if not database_url:
        return

    if not database_url.startswith(("postgresql://", "postgres://")):
        return

    if os.getenv("AUTO_CREATE_DATABASE", "true").lower() not in {"1", "true", "yes", "on"}:
        return

    parsed = urlparse(_normalize_url(database_url))
    if not parsed.path or parsed.path == "/":
        return

    dbname = parsed.path.lstrip("/")
    if not dbname:
        return

    admin_url = parsed._replace(path="/postgres")
    admin_database_url = admin_url.geturl()

    try:
        engine = create_engine(admin_database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :dbname"), {"dbname": dbname}).fetchone()
            if row is None:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    except Exception:
        # The app should continue to surface a meaningful database error if the PostgreSQL
        # service itself is unreachable or the admin connection is not permitted.
        return
