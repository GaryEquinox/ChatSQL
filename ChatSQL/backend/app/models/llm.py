from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    provider_type: Mapped[str] = mapped_column(String(16))
    base_url: Mapped[str] = mapped_column(Text)
    api_key: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(160))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4000)
    temperature: Mapped[float] = mapped_column(Float, default=0)
    structured_output_mode: Mapped[str] = mapped_column(String(24), default="auto")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
