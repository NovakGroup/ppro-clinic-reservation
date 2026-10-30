"""Připojení k databázi. Adresa se čte výhradně z proměnné prostředí DATABASE_URL."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Chybí proměnná prostředí DATABASE_URL (viz .env.example).")
    return url


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_sessionmaker() -> sessionmaker[Session]:
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _SessionLocal
