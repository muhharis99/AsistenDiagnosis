"""Engine, sesi dan trigger audit append-only."""
from __future__ import annotations
from pathlib import Path
from sqlalchemy import create_engine, event, text, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from rme.models import Base
from rme.settings import Settings

def build_engine(database_url: str | None = None) -> Engine:
    settings = Settings.from_env()
    url = database_url or settings.database_url
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        elif url.startswith("sqlite:///"):
            path = Path(url.replace("sqlite:///", "", 1))
            if not path.is_absolute():
                path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine

def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.execute(text("CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit append-only'); END;"))
            conn.execute(text("CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit append-only'); END;"))
    elif engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("""CREATE OR REPLACE FUNCTION rme_audit_immutable() RETURNS trigger AS $$
                BEGIN RAISE EXCEPTION 'audit append-only'; END; $$ LANGUAGE plpgsql;"""))
            conn.execute(text("DROP TRIGGER IF EXISTS audit_no_update ON audit_logs"))
            conn.execute(text("DROP TRIGGER IF EXISTS audit_no_delete ON audit_logs"))
            conn.execute(text("CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW EXECUTE FUNCTION rme_audit_immutable()"))
            conn.execute(text("CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION rme_audit_immutable()"))

def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
