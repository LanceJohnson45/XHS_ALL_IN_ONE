from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class BrowserFingerprint(Base):
    """A reusable browser fingerprint bound to one or more accounts.

    ``profile_json`` stores the complete generated device profile. It is kept as
    JSON text (not individual columns) so the signer-specific fields can evolve
    without a schema migration.
    """

    __tablename__ = "browser_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    target: Mapped[str] = mapped_column(String(16), default="pc", index=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
