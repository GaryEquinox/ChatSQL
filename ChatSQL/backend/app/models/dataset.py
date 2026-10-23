from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    short_code: Mapped[str] = mapped_column(String(4), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    dialect: Mapped[str] = mapped_column(String(32))
    db_version: Mapped[str] = mapped_column(String(80), default="")
    storage_path: Mapped[str] = mapped_column(Text, default="")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    schema_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
