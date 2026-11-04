"""Database engine and session helpers."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from nginx_perf_agent.db.models import Base

SQLITE_PREFIX = "sqlite:///"


def create_engine_for(database_url: str) -> Engine:
    """Create an engine, making sure a SQLite file's parent directory exists."""
    connect_args: dict[str, object] = {}
    if database_url.startswith(SQLITE_PREFIX):
        db_path = Path(database_url[len(SQLITE_PREFIX) :])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args, future=True)


def init_db(database_url: str) -> Engine:
    """Create all tables if they do not exist and return the engine."""
    engine = create_engine_for(database_url)
    Base.metadata.create_all(engine)
    _add_email_project_column(engine)
    return engine


def _add_email_project_column(engine: Engine) -> None:
    """Additive migration for databases created before `emails.project`."""
    # shortcut: one hand-written additive migration; switch to Alembic when
    # schema changes become frequent.
    columns = {column["name"] for column in inspect(engine).get_columns("emails")}
    if "project" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE emails ADD COLUMN project VARCHAR(64)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_emails_project ON emails (project)")
        )


def table_names(engine: Engine) -> list[str]:
    return sorted(inspect(engine).get_table_names())


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
