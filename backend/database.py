"""
database.py

STEP 1 OF THE ROADMAP: Database Foundation
-------------------------------------------
Everything else in the roadmap (snapshot history, compare snapshots,
multi-client dashboard, timeline) depends on the tool actually
remembering DDR uploads instead of forgetting them the moment the
browser tab closes. This module adds that memory layer.

SQLite chosen deliberately (matches the reasoning already discussed):
    - one single .db file, no server process to install/run
    - works the same on a dev machine and inside the PyInstaller .exe
    - trivial to swap for Postgres later (SQLAlchemy's engine URL is
      the only thing that would need to change)

TWO TABLES:
    clients    - just a name, one row per client/company
    snapshots  - one row per DDR upload that was saved. Stores the
                 full parsed DDR dict AND the full findings report as
                 JSON text columns, so a snapshot can be reloaded and
                 re-rendered exactly as it looked at analysis time, or
                 fed into a future "compare two snapshots" feature
                 without re-uploading or re-parsing anything.

WHERE THE .db FILE LIVES:
    backend/auditor.db (created automatically on first run, next to
    this file). Same folder-resolution trick as main.py's
    _frontend_dir() is used here so this also works from inside the
    PyInstaller .exe, where "next to this file" means the temp
    _MEIPASS unpack folder -- NOT what we want for a database that
    needs to persist across runs. So for the frozen .exe case, the
    .db file is placed next to the .exe itself instead.
"""

import json
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# ---------------------------------------------------------------------------
# Engine / session setup
# ---------------------------------------------------------------------------


def _db_path() -> str:
    """Resolve where auditor.db should live -- persistent in both the
    normal `python main.py` run and the bundled .exe (see main.py's
    _frontend_dir() for the same reasoning applied to the frontend)."""
    if getattr(sys, "frozen", False):
        # Next to the .exe itself, so it survives between runs and
        # isn't wiped with the temp PyInstaller unpack folder.
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "auditor.db")


DB_PATH = _db_path()
DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False: FastAPI/uvicorn can hand a request to a
# different thread than the one that created the engine; SQLite
# objects default to being single-thread-only, so this is required
# for a web app (each request still gets its own short-lived Session).
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("name", name="uq_client_name"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    snapshots = relationship(
        "Snapshot", back_populates="client", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    filename = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Stored as JSON text rather than separate normalised tables -- the
    # shape of `data` (from ddr_parser.parse_ddr) and `report`
    # (summary + findings) already exists and is well understood; JSON
    # columns let us store/reload them as-is with zero schema
    # migrations every time a new finding field gets added upstream.
    parsed_data_json = Column(Text, nullable=False)
    report_json = Column(Text, nullable=False)

    # Denormalised summary counts, kept alongside the JSON so the
    # snapshot list endpoint can show Critical/Warning/Info counts
    # without parsing report_json for every row.
    critical_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    info_count = Column(Integer, default=0)

    client = relationship("Client", back_populates="snapshots")


def init_db() -> None:
    """Create the .db file and tables if they don't exist yet. Safe to
    call on every app startup -- create_all() no-ops on existing tables."""
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Helpers -- main.py only ever calls these, never touches Session/Base
# directly, so the storage details stay swappable later (e.g. Postgres).
# ---------------------------------------------------------------------------


def get_or_create_client(name: str) -> Client:
    name = name.strip()
    if not name:
        raise ValueError("Client name cannot be empty.")
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.name == name).first()
        if client:
            return client
        client = Client(name=name)
        db.add(client)
        db.commit()
        db.refresh(client)
        return client
    finally:
        db.close()


def list_clients() -> list[dict]:
    db = SessionLocal()
    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "snapshot_count": len(c.snapshots),
            }
            for c in clients
        ]
    finally:
        db.close()


def create_snapshot(client_id: int, filename: str, parsed_data: dict, report: dict) -> dict:
    db = SessionLocal()
    try:
        summary = report.get("summary", {}) or {}
        snapshot = Snapshot(
            client_id=client_id,
            filename=filename,
            parsed_data_json=json.dumps(parsed_data, default=str),
            report_json=json.dumps(report, default=str),
            critical_count=summary.get("critical", 0),
            warning_count=summary.get("warning", 0),
            info_count=summary.get("info", 0),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return _snapshot_summary(snapshot)
    finally:
        db.close()


def list_snapshots(client_id: int | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        query = db.query(Snapshot).order_by(Snapshot.created_at.desc())
        if client_id is not None:
            query = query.filter(Snapshot.client_id == client_id)
        return [_snapshot_summary(s) for s in query.all()]
    finally:
        db.close()


def get_snapshot(snapshot_id: int) -> dict | None:
    """Full snapshot detail, including the parsed DDR data and report --
    used to reload a past analysis, and later to feed the compare-
    snapshots feature (Step 3) two of these without re-parsing XML."""
    db = SessionLocal()
    try:
        s = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
        if not s:
            return None
        detail = _snapshot_summary(s)
        detail["parsed_data"] = json.loads(s.parsed_data_json)
        detail["report"] = json.loads(s.report_json)
        return detail
    finally:
        db.close()


def rename_client(client_id: int, new_name: str) -> dict:
    """STEP 4 (roadmap): Multi-Client Dashboard -- lets a client be
    renamed after the fact (e.g. typo when it was first created)."""
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Client name cannot be empty.")
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError("Client not found.")
        clash = (
            db.query(Client)
            .filter(Client.name == new_name, Client.id != client_id)
            .first()
        )
        if clash:
            raise ValueError(f'A client named "{new_name}" already exists.')
        client.name = new_name
        db.commit()
        db.refresh(client)
        return {"id": client.id, "name": client.name}
    finally:
        db.close()


def delete_client(client_id: int) -> bool:
    """STEP 4 (roadmap): removes a client AND all of its snapshots --
    the `cascade="all, delete-orphan"` on Client.snapshots handles the
    snapshot rows automatically once the client object itself is
    deleted through the ORM (not a raw SQL DELETE)."""
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return False
        db.delete(client)
        db.commit()
        return True
    finally:
        db.close()


def delete_snapshot(snapshot_id: int) -> bool:
    """STEP 4 (roadmap): removes a single snapshot without touching its
    client or any other snapshot -- e.g. a test upload that shouldn't
    count toward that client's history."""
    db = SessionLocal()
    try:
        snap = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
        if not snap:
            return False
        db.delete(snap)
        db.commit()
        return True
    finally:
        db.close()


def dashboard_summary() -> list[dict]:
    """STEP 4 (roadmap): Multi-Client Dashboard.

    One row per client, each carrying:
      - snapshot_count
      - latest snapshot's filename/date/C-W-I counts (None if the
        client has no snapshots yet)
      - a "trend" on the Critical count: comparing the latest snapshot
        against the one before it, so the dashboard can show whether a
        client's most recent upload got better or worse without the
        user having to open Compare Snapshots themselves.
        "up" = more criticals than before (worse), "down" = fewer
        (better), "flat" = unchanged, None = fewer than 2 snapshots to
        compare.
    """
    db = SessionLocal()
    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()
        result = []
        for c in clients:
            snaps = sorted(c.snapshots, key=lambda s: s.created_at, reverse=True)
            latest = None
            trend = None
            if snaps:
                latest = {
                    "id": snaps[0].id,
                    "filename": snaps[0].filename,
                    "created_at": snaps[0].created_at.isoformat() if snaps[0].created_at else None,
                    "summary": {
                        "critical": snaps[0].critical_count,
                        "warning": snaps[0].warning_count,
                        "info": snaps[0].info_count,
                    },
                }
                if len(snaps) >= 2:
                    prev_critical = snaps[1].critical_count
                    cur_critical = snaps[0].critical_count
                    if cur_critical > prev_critical:
                        trend = "up"
                    elif cur_critical < prev_critical:
                        trend = "down"
                    else:
                        trend = "flat"
            result.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "snapshot_count": len(snaps),
                    "latest_snapshot": latest,
                    "critical_trend": trend,
                }
            )
        return result
    finally:
        db.close()


def timeline_summary(client_id: int | None = None) -> list[dict]:
    """STEP 6 (roadmap): Timeline / Releases.

    Return each client's saved DDR snapshots in chronological order.  Each
    snapshot is a release event and carries the change in its Critical,
    Warning, and Info counts compared with that client's preceding saved
    snapshot.  Keeping this calculation here means the frontend does not
    need to fetch and stitch together separate client histories.
    """
    db = SessionLocal()
    try:
        client_query = db.query(Client).order_by(Client.name.asc())
        if client_id is not None:
            client_query = client_query.filter(Client.id == client_id)

        result = []
        for client in client_query.all():
            snapshots = sorted(client.snapshots, key=lambda s: s.created_at)
            events = []
            previous = None
            for snapshot in snapshots:
                summary = {
                    "critical": snapshot.critical_count,
                    "warning": snapshot.warning_count,
                    "info": snapshot.info_count,
                }
                delta = None if previous is None else {
                    key: summary[key] - previous[key]
                    for key in ("critical", "warning", "info")
                }
                events.append({
                    "id": snapshot.id,
                    "filename": snapshot.filename,
                    "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
                    "summary": summary,
                    "delta": delta,
                })
                previous = summary
            if events:
                result.append({
                    "id": client.id,
                    "name": client.name,
                    "events": events,
                })
        return result
    finally:
        db.close()


def _snapshot_summary(s: Snapshot) -> dict:
    return {
        "id": s.id,
        "client_id": s.client_id,
        "client_name": s.client.name if s.client else None,
        "filename": s.filename,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "summary": {
            "critical": s.critical_count,
            "warning": s.warning_count,
            "info": s.info_count,
        },
    }
