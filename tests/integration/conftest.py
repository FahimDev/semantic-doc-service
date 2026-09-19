"""Integration fixtures: a throwaway database migrated with the real Alembic history."""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.infrastructure.database import build_engine

ROOT = Path(__file__).resolve().parents[2]
TEST_DB = "policy_vault_test"
DROP_TEST_DB = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB))


def _admin_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql", database="postgres").render_as_string(False)


@pytest.fixture(scope="session")
def alembic_config(monkeypatch_session: pytest.MonkeyPatch) -> Iterator[Config]:
    base_url = get_settings().database_url
    test_url = make_url(base_url).set(database=TEST_DB).render_as_string(hide_password=False)

    with psycopg.connect(_admin_dsn(base_url), autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB))
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))

    # Alembic's env.py and the app both read the URL from cached settings.
    monkeypatch_session.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")
    yield config

    get_settings.cache_clear()
    with psycopg.connect(_admin_dsn(base_url), autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB))
        )


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    patch = pytest.MonkeyPatch()
    yield patch
    patch.undo()


@pytest.fixture(scope="session")
def engine(alembic_config: Config) -> Iterator[Engine]:
    engine = build_engine(get_settings().database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Each test runs in a transaction that is rolled back, so tests stay independent."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
