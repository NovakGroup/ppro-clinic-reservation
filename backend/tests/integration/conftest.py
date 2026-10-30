"""Integrační testy běží proti skutečné PostgreSQL (služba db-test v docker compose).

Schéma se vytváří migracemi Alembic, mezi testy se data mažou a znovu vkládá seed.
"""
import os
from datetime import date, datetime, time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_URL = os.environ.get("TEST_DATABASE_URL")
TODAY = date(2026, 10, 30)  # pevné "dnes" – testy nezávisí na skutečném datu

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def engine():
    if not TEST_URL:
        pytest.skip("Chybí TEST_DATABASE_URL – integrační testy se spouští přes docker compose (test-integration).")
    os.environ["DATABASE_URL"] = TEST_URL
    eng = create_engine(TEST_URL)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def Session(engine):
    tables = "visit_procedure, visit, doctor_absence, appointment, patient, doctor_schedule, medical_procedure, doctor"
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    from app.seed import seed

    with factory() as s:
        seed(s, today=TODAY)
    return factory


class FixedClock:
    def today(self):
        return TODAY

    def now(self):
        return datetime.combine(TODAY, time(7, 0))


@pytest.fixture
def client(Session):
    from fastapi.testclient import TestClient

    from app import container
    from app.main import app
    from app.repositories.sql import SqlUnitOfWork

    def get_uow():
        s = Session()
        try:
            yield SqlUnitOfWork(s)
        finally:
            s.close()

    app.dependency_overrides[container.get_uow] = get_uow
    app.dependency_overrides[container.get_clock] = FixedClock
    yield TestClient(app)
    app.dependency_overrides.clear()
