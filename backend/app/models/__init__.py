"""Database models.

What brine remembers about the fleet, independently of the master's own (short-lived) caches:

* ``Minion``: one row per minion key, with its latest grains and presence.
* ``PresenceChange``: online/offline transitions, for the status timeline.
* ``GrainsSnapshot``: every distinct set of grains a minion reported, for history and diffs.
* ``Job`` / ``JobReturn``: jobs and per-minion results, kept after the master forgets them.
* ``AuditEntry``: who did what (written from Phase 2 on).
* ``SystemState``: small key/value facts, such as when presence was last observed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.types import UTCDateTime

# Key states, as reported by `wheel key.list_all`. "deleted" means the key went away.
KEY_STATES = ("accepted", "pending", "rejected", "denied", "deleted")


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: UTCDateTime(),
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class Minion(Base):
    __tablename__ = "minions"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    key_state: Mapped[str] = mapped_column(String(16))
    first_seen_at: Mapped[datetime]
    # Last time brine saw evidence the minion was alive: present in a presence check, a job
    # return, or a start event. None = never.
    last_seen_at: Mapped[datetime | None]
    # Whether the most recent presence observation included this minion.
    connected: Mapped[bool] = mapped_column(default=False)
    # Latest grains and when they were collected. grains_source is "minion" (fresh from the
    # minion) or "master_cache" (the master's cached copy, age unknown).
    grains: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    grains_at: Mapped[datetime | None]
    grains_source: Mapped[str | None] = mapped_column(String(16))


class PresenceChange(Base):
    __tablename__ = "presence_changes"
    __table_args__ = (Index("ix_presence_changes_minion_at", "minion_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    minion_id: Mapped[str] = mapped_column(ForeignKey("minions.id", ondelete="CASCADE"))
    at: Mapped[datetime]
    connected: Mapped[bool]


class GrainsSnapshot(Base):
    __tablename__ = "grains_snapshots"
    __table_args__ = (Index("ix_grains_snapshots_minion_at", "minion_id", "collected_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    minion_id: Mapped[str] = mapped_column(ForeignKey("minions.id", ondelete="CASCADE"))
    # When this content was first collected; later identical collections don't add rows.
    collected_at: Mapped[datetime]
    sha256: Mapped[str] = mapped_column(String(64))
    grains: Mapped[dict[str, Any]] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_started_at", "started_at"),)

    jid: Mapped[str] = mapped_column(String(32), primary_key=True)
    # "local" for minion jobs (salt/job/*), "runner" for master-side runs (salt/run/*).
    kind: Mapped[str] = mapped_column(String(16))
    fun: Mapped[str] = mapped_column(String(255))
    args: Mapped[list[Any]] = mapped_column(JSON, default=list)
    target: Mapped[str | None] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(String(32))
    user: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime]
    # Minions the master expected to answer (local jobs only).
    minions: Mapped[list[Any]] = mapped_column(JSON, default=list)


class JobReturn(Base):
    __tablename__ = "job_returns"
    __table_args__ = (Index("ix_job_returns_minion", "minion_id", "returned_at"),)

    jid: Mapped[str] = mapped_column(ForeignKey("jobs.jid", ondelete="CASCADE"), primary_key=True)
    # Minion ID for local jobs; "master" for runner jobs.
    minion_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    returned_at: Mapped[datetime]
    success: Mapped[bool | None]
    retcode: Mapped[int | None]
    data: Mapped[Any] = mapped_column(JSON)


class AuditEntry(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_at", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime]
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime]
