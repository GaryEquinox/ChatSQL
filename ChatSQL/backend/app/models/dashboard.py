from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Dashboard(Base):
    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("owner_username", "name", name="uq_dashboard_owner_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_username: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(160))
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cards: Mapped[list["DashboardCard"]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardCard.created_at",
    )


class DashboardCard(Base):
    __tablename__ = "dashboard_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dashboard_id: Mapped[str] = mapped_column(ForeignKey("dashboards.id", ondelete="CASCADE"), index=True)
    card_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(180), default="")
    layout_json: Mapped[str] = mapped_column(Text, default="{}")
    dataset_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="snapshot")
    query_json: Mapped[str] = mapped_column(Text, default="{}")
    chart_config_json: Mapped[str] = mapped_column(Text, default="{}")
    result_snapshot_json: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    dashboard: Mapped[Dashboard] = relationship(back_populates="cards")
