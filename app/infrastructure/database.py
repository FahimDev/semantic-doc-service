""" PostgreSQL engine and transaction/ session construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker, DeclarativeBase
# A SQLAlchemy Session is a unit-of-work boundary and identity map. It is not a global connection. Create a short-lived session per use case and define transaction scope explicitly.

class Base(DeclarativeBase):
    """All ORM tables inherit one metadata registry."""

def build_engine(database_url: str) -> Engine:
    # pool_pre_ping replaces dead pooled connections before a requested uses one.
    return create_engine(database_url, pool_pre_ping=True)

def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False keeps ORM objects alive after a commit, which is convenient for read-only snapshots.
    return sessionmaker(bind=engine, expire_on_commit=False)