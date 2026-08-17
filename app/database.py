from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 — register models on Base before create_all

    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


# Columns added to a model *after* a local secopsmesh.db was first created.
# create_all() creates missing tables but never ALTERs an existing one, and
# this POC has no Alembic, so without this an added column would be missing
# from the on-disk table and break every SELECT against it. Each entry is
# (table, column, SQL type) and is applied only if the column is absent.
_ADDED_COLUMNS = [
    ("incidents", "analyzed_at_count", "INTEGER"),
    ("incidents", "llm_explanation", "TEXT"),
]


def _run_lightweight_migrations() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, column, sql_type in _ADDED_COLUMNS:
        if table not in existing_tables:
            continue  # create_all already built it with the column
        columns = {col["name"] for col in inspector.get_columns(table)}
        if column not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
