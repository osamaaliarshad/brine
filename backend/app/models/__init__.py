"""Database models.

What brine remembers about the fleet, independently of the master's own (short-lived) caches:

* ``Minion``: one row per minion key, with its latest grains and presence.
* ``PresenceChange``: online/offline transitions, for the status timeline.
* ``GrainsSnapshot``: every distinct set of grains a minion reported, for history and diffs.
* ``InventoryRead``: when each minion's packages and checks were last asked for and read.
* ``InventoryItem``: each minion's current packages and check entries.
* ``InventoryChange``: every package or check entry that appeared, changed or went away.
* ``Job`` / ``JobReturn``: jobs and per-minion results, kept after the master forgets them.
* ``AuditEntry``: who did what.
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
    # The key's fingerprint as the master reports it (`wheel key.finger`).
    key_fingerprint: Mapped[str | None] = mapped_column(String(128))
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


class InventoryRead(Base):
    """One minion's latest read of one source ("packages" or a check's name)."""

    __tablename__ = "inventory_reads"

    minion_id: Mapped[str] = mapped_column(
        ForeignKey("minions.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    # The rules for these columns are in app/ingest.py, at "packages and checks".
    asked_at: Mapped[datetime | None]  # brine last asked, by its own clock
    asked_jid: Mapped[str | None] = mapped_column(String(32))  # brine's ask still out, if any
    answered_at: Mapped[datetime | None]  # last answer, good or failed
    read_at: Mapped[datetime | None]  # last good answer: entries are as of this
    first_read_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)  # the last answer's error, if it failed
    # The last good answer was cut short, so some entries may be missing.
    truncated: Mapped[bool] = mapped_column(default=False)
    # Read again at or after this (a minion start, a person's job finishing), until brine's
    # answer comes.
    wanted_at: Mapped[datetime | None]
    # The person's job (or jobs) since the last read, waiting for brine's answer: if brine asked
    # soon enough after it, what that answer finds is credited to it. after_jid is None after
    # several jobs, and after_user too unless one person ran them all.
    after_jid: Mapped[str | None] = mapped_column(String(32))
    after_user: Mapped[str | None] = mapped_column(String(255))
    after_at: Mapped[datetime | None]


class InventoryItem(Base):
    """What a minion said it has: a package and its version, or a check's entry."""

    __tablename__ = "inventory_items"
    __table_args__ = (Index("ix_inventory_items_source_name", "source", "name"),)

    minion_id: Mapped[str] = mapped_column(
        ForeignKey("minions.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    # "" for a check that prints a single value.
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    since: Mapped[datetime]  # first read with this value


class InventoryChange(Base):
    """One change in what a minion has, found by comparing two reads."""

    __tablename__ = "inventory_changes"
    __table_args__ = (
        Index("ix_inventory_changes_source_name_at", "source", "name", "at"),
        Index("ix_inventory_changes_minion_at", "minion_id", "at"),
        Index("ix_inventory_changes_at", "at"),
        # job_owner finds the changes credited to an orchestration's steps by their jid.
        Index("ix_inventory_changes_jid", "jid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    minion_id: Mapped[str] = mapped_column(ForeignKey("minions.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    old: Mapped[str | None] = mapped_column(Text)  # None: wasn't there
    new: Mapped[str | None] = mapped_column(Text)  # None: gone
    at: Mapped[datetime]  # the read that found it
    since: Mapped[datetime | None]  # the read before: it changed between the two
    jid: Mapped[str | None] = mapped_column(String(32))  # credited job, if any
    user: Mapped[str | None] = mapped_column(String(255))


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


class PendingRun(Base):
    """A command someone ran from brine that a minion missed because it was offline, to run on
    that minion when it's back (catch-up runs). Only ever created on request, in brine."""

    __tablename__ = "pending_runs"
    __table_args__ = (
        Index("ix_pending_runs_state_minion", "state", "minion_id"),
        Index("ix_pending_runs_source_jid", "source_jid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    minion_id: Mapped[str] = mapped_column(String(255))
    # The job it catches up on, and the command as the Run page sent it.
    source_jid: Mapped[str] = mapped_column(String(32))
    fun: Mapped[str] = mapped_column(String(255))
    args: Mapped[list[Any]] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    # waiting -> sending -> sent; or expired, cancelled, replaced (a newer identical one),
    # refused (not allowed any more), failed (salt-api failed after it may have gone out).
    state: Mapped[str] = mapped_column(String(16), default="waiting")
    reason: Mapped[str | None] = mapped_column(Text)
    sent_jid: Mapped[str | None] = mapped_column(String(32))
    sent_at: Mapped[datetime | None]


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
