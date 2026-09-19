import pytest
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import configure_mappers

from alembic import command
from app.core.constants import DEFAULT_KNOWLEDGE_BASE_ID

pytestmark = pytest.mark.integration


def test_orm_mappers_configure() -> None:
    configure_mappers()


def test_orm_matches_migrations(alembic_config: Config) -> None:
    # Raises CommandError if autogenerate would emit any operation.
    command.check(alembic_config)


def test_default_knowledge_base_is_seeded(engine: Engine) -> None:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT name, version FROM knowledge_bases WHERE id = :id"),
            {"id": DEFAULT_KNOWLEDGE_BASE_ID},
        ).one()

    assert tuple(row) == ("default", 1)


def test_vector_column_is_384_dimensional(engine: Engine) -> None:
    with engine.connect() as connection:
        type_name = connection.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()

    assert type_name == "vector(384)"


def test_expected_tables_exist(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())

    assert {"knowledge_bases", "documents", "chunks", "outbox_events"} <= tables


def test_downgrade_and_upgrade_round_trip(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "base")
    assert "documents" not in inspect(engine).get_table_names()

    command.upgrade(alembic_config, "head")
    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM knowledge_bases")).scalar_one()
    assert count == 1
