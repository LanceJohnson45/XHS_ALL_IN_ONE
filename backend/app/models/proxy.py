from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class ProxyEndpoint(Base):
    """One purchased static IP / proxy line owned by a user.

    Passwords are encrypted with the same Fernet key as account cookies. They
    are never returned by the HTTP API.
    """

    __tablename__ = "proxy_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    protocol: Mapped[str] = mapped_column(String(16), default="http")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(128), default="")
    password_encrypted: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    status_message: Mapped[str] = mapped_column(Text, default="")
    exit_ip: Mapped[str] = mapped_column(String(64), default="")
    exit_country: Mapped[str] = mapped_column(String(64), default="")
    exit_region: Mapped[str] = mapped_column(String(64), default="")
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
