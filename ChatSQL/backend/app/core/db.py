from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.meta_db_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from app.models.dataset import Dataset
    from app.models.conversation import ContextSegment, Conversation, DebugRecord, Message
    from app.models.dashboard import Dashboard, DashboardCard
    from app.models.llm import LLMConfig

    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()


def _ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    if "dashboards" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("dashboards")}
    if "config_json" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN config_json TEXT DEFAULT '{}'"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
