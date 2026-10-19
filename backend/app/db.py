from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

_url = config.database_url()
if _url.startswith("sqlite:///"):
    Path(_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(_url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create or upgrade the schema (non-destructive migrations; see migrations.py)."""
    from .migrations import migrate
    migrate(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
