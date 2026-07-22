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

THREE TABLES:
    clients    - just a name, one row per client/company
    solutions  - STEP 1b (roadmap): one row per named FileMaker solution
                 that belongs to a client (e.g. a client "Acme Corp" may
                 have both an "Inventory System" and a "CRM System").
                 Added because a single client card mixing snapshots
                 from unrelated solutions made Compare Snapshots able to
                 silently diff two different solutions against each
                 other and produce a meaningless result. solution_id on
                 Snapshot is nullable, so every snapshot saved before
                 this change keeps working exactly as it did (it just
                 shows up as "No solution" instead of under a named one).
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

import hashlib
import json
import os
import secrets
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
    solutions = relationship(
        "Solution", back_populates="client", cascade="all, delete-orphan"
    )


class Solution(Base):
    """STEP 1b (roadmap): a named FileMaker solution under a client
    (e.g. "Inventory System", "CRM System"). Snapshots optionally belong
    to one of these, so a client with several unrelated solutions keeps
    each one's history/trend separate instead of all mixed together."""

    __tablename__ = "solutions"
    __table_args__ = (
        UniqueConstraint("client_id", "name", name="uq_solution_client_name"),
    )

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    client = relationship("Client", back_populates="solutions")
    snapshots = relationship(
        "Snapshot", back_populates="solution", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    # Nullable on purpose: every snapshot saved before this feature existed
    # has no solution_id, and stays valid/queryable as "No solution" rather
    # than needing a backfill migration.
    solution_id = Column(Integer, ForeignKey("solutions.id"), nullable=True)
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
    solution = relationship("Solution", back_populates="snapshots")


class User(Base):
    """STEP 7 (roadmap): Users / Login. Deliberately minimal -- no roles,
    no email, no password reset flow. Anyone with an account can sign in
    and use the whole tool; this is an access gate for a small internal
    team, not a permissions system."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_user_username"),)

    id = Column(Integer, primary_key=True)
    username = Column(String(120), nullable=False)
    # "<salt_hex>$<pbkdf2_hex>" -- see _hash_password(). stdlib-only
    # (hashlib.pbkdf2_hmac) on purpose, so this feature doesn't need a
    # new dependency like bcrypt/passlib in requirements.txt.
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserSession(Base):
    """A logged-in session, keyed by an opaque random token stored in an
    HttpOnly cookie. Kept in the database (not just server memory like
    ai_client's runtime config) so people aren't logged out every time
    the server/.exe restarts."""

    __tablename__ = "sessions"

    token = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return secrets.compare_digest(expected.hex(), digest_hex)


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


def get_or_create_solution(client_id: int, name: str) -> Solution:
    """STEP 1b (roadmap): mirrors get_or_create_client, but scoped to a
    client -- two different clients are allowed to each have a solution
    with the same name (e.g. both have a "CRM System"), so lookups are
    always filtered by client_id, never by name alone."""
    name = name.strip()
    if not name:
        raise ValueError("Solution name cannot be empty.")
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError("Client not found.")
        solution = (
            db.query(Solution)
            .filter(Solution.client_id == client_id, Solution.name == name)
            .first()
        )
        if solution:
            return solution
        solution = Solution(client_id=client_id, name=name)
        db.add(solution)
        db.commit()
        db.refresh(solution)
        return solution
    finally:
        db.close()


def list_solutions(client_id: int) -> list[dict]:
    """Solutions for one client, each with its own snapshot_count -- used
    to populate the solution dropdown/datalist once a client is chosen."""
    db = SessionLocal()
    try:
        solutions = (
            db.query(Solution)
            .filter(Solution.client_id == client_id)
            .order_by(Solution.name.asc())
            .all()
        )
        return [
            {
                "id": s.id,
                "client_id": s.client_id,
                "name": s.name,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "snapshot_count": len(s.snapshots),
            }
            for s in solutions
        ]
    finally:
        db.close()


def rename_solution(solution_id: int, new_name: str) -> dict:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Solution name cannot be empty.")
    db = SessionLocal()
    try:
        solution = db.query(Solution).filter(Solution.id == solution_id).first()
        if not solution:
            raise ValueError("Solution not found.")
        clash = (
            db.query(Solution)
            .filter(
                Solution.client_id == solution.client_id,
                Solution.name == new_name,
                Solution.id != solution_id,
            )
            .first()
        )
        if clash:
            raise ValueError(f'A solution named "{new_name}" already exists for this client.')
        solution.name = new_name
        db.commit()
        db.refresh(solution)
        return {"id": solution.id, "client_id": solution.client_id, "name": solution.name}
    finally:
        db.close()


def delete_solution(solution_id: int) -> bool:
    """Deletes a solution AND all of its snapshots (cascade, same
    reasoning as delete_client). Snapshots belonging to the client but
    NOT to this solution are untouched."""
    db = SessionLocal()
    try:
        solution = db.query(Solution).filter(Solution.id == solution_id).first()
        if not solution:
            return False
        db.delete(solution)
        db.commit()
        return True
    finally:
        db.close()


def create_snapshot(
    client_id: int,
    filename: str,
    parsed_data: dict,
    report: dict,
    solution_id: int | None = None,
) -> dict:
    db = SessionLocal()
    try:
        summary = report.get("summary", {}) or {}
        snapshot = Snapshot(
            client_id=client_id,
            solution_id=solution_id,
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


def list_snapshots(client_id: int | None = None, solution_id: int | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        query = db.query(Snapshot).order_by(Snapshot.created_at.desc())
        if client_id is not None:
            query = query.filter(Snapshot.client_id == client_id)
        if solution_id is not None:
            query = query.filter(Snapshot.solution_id == solution_id)
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


def _latest_and_trend(snaps: list) -> tuple[dict | None, str | None]:
    """Shared by client-level and solution-level dashboard rows: given a
    list of Snapshot rows (any order), returns the latest one's summary
    dict plus a "trend" comparing its Critical count against the
    snapshot before it. "up" = more criticals than before (worse),
    "down" = fewer (better), "flat" = unchanged, None = fewer than 2
    snapshots to compare."""
    if not snaps:
        return None, None
    ordered = sorted(snaps, key=lambda s: s.created_at, reverse=True)
    latest = {
        "id": ordered[0].id,
        "filename": ordered[0].filename,
        "created_at": ordered[0].created_at.isoformat() if ordered[0].created_at else None,
        "summary": {
            "critical": ordered[0].critical_count,
            "warning": ordered[0].warning_count,
            "info": ordered[0].info_count,
        },
    }
    trend = None
    if len(ordered) >= 2:
        prev_critical = ordered[1].critical_count
        cur_critical = ordered[0].critical_count
        if cur_critical > prev_critical:
            trend = "up"
        elif cur_critical < prev_critical:
            trend = "down"
        else:
            trend = "flat"
    return latest, trend


def dashboard_summary() -> list[dict]:
    """STEP 4 (roadmap, refined for the Client -> Solution -> Snapshot
    hierarchy): Multi-Client Dashboard.

    One row per client, carrying:
      - snapshot_count / latest_snapshot / critical_trend across ALL of
        the client's snapshots (same shape as before this change, so a
        client with no solutions yet renders exactly as it always did)
      - "solutions": one row per named solution under this client, each
        with its OWN snapshot_count / latest_snapshot / critical_trend,
        so unrelated solutions (e.g. "Inventory System" vs "CRM System")
        no longer get blended into a single trend line together
      - snapshots saved before this feature existed (solution_id is
        NULL) are grouped into a synthetic "No solution" bucket at the
        end of "solutions", id: None, so nothing saved earlier goes
        missing from the dashboard
    """
    db = SessionLocal()
    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()
        result = []
        for c in clients:
            all_snaps = list(c.snapshots)
            latest, trend = _latest_and_trend(all_snaps)

            solution_rows = []
            for sol in sorted(c.solutions, key=lambda s: s.name.lower()):
                sol_latest, sol_trend = _latest_and_trend(list(sol.snapshots))
                solution_rows.append(
                    {
                        "id": sol.id,
                        "name": sol.name,
                        "snapshot_count": len(sol.snapshots),
                        "latest_snapshot": sol_latest,
                        "critical_trend": sol_trend,
                    }
                )

            unassigned = [s for s in all_snaps if s.solution_id is None]
            if unassigned:
                un_latest, un_trend = _latest_and_trend(unassigned)
                solution_rows.append(
                    {
                        "id": None,
                        "name": "No solution",
                        "snapshot_count": len(unassigned),
                        "latest_snapshot": un_latest,
                        "critical_trend": un_trend,
                    }
                )

            result.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "snapshot_count": len(all_snaps),
                    "latest_snapshot": latest,
                    "critical_trend": trend,
                    "solutions": solution_rows,
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


# ---------------------------------------------------------------------------
# STEP 7 (roadmap): Users / Login helpers
# ---------------------------------------------------------------------------


def count_users() -> int:
    db = SessionLocal()
    try:
        return db.query(User).count()
    finally:
        db.close()


def create_user(username: str, password: str) -> dict:
    username = username.strip()
    if not username:
        raise ValueError("Email cannot be empty.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    db = SessionLocal()
    try:
        clash = db.query(User).filter(User.username == username).first()
        if clash:
            raise ValueError(f'A user with email "{username}" already exists.')
        user = User(username=username, password_hash=_hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"id": user.id, "username": user.username}
    finally:
        db.close()


def verify_user(username: str, password: str) -> dict | None:
    """Returns {"id", "username"} on a correct username+password, else None
    -- never distinguishes "no such user" from "wrong password" to the
    caller, so main.py can't leak which usernames exist."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username.strip()).first()
        if not user or not _verify_password(password, user.password_hash):
            return None
        return {"id": user.id, "username": user.username}
    finally:
        db.close()


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    db = SessionLocal()
    try:
        db.add(UserSession(token=token, user_id=user_id))
        db.commit()
        return token
    finally:
        db.close()


def get_user_by_session(token: str | None) -> dict | None:
    if not token:
        return None
    db = SessionLocal()
    try:
        sess = db.query(UserSession).filter(UserSession.token == token).first()
        if not sess:
            return None
        user = db.query(User).filter(User.id == sess.user_id).first()
        if not user:
            return None
        return {"id": user.id, "username": user.username}
    finally:
        db.close()


def delete_session(token: str) -> None:
    db = SessionLocal()
    try:
        db.query(UserSession).filter(UserSession.token == token).delete()
        db.commit()
    finally:
        db.close()


def list_users() -> list[dict]:
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.username.asc()).all()
        return [
            {
                "id": u.id,
                "username": u.username,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    finally:
        db.close()


def delete_user(user_id: int) -> bool:
    """Refuses to delete the last remaining account -- otherwise the tool
    would become permanently unreachable (no login screen path back in
    without editing the database by hand)."""
    db = SessionLocal()
    try:
        total = db.query(User).count()
        if total <= 1:
            raise ValueError("Cannot remove the last remaining user account.")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        db.query(UserSession).filter(UserSession.user_id == user_id).delete()
        db.delete(user)
        db.commit()
        return True
    finally:
        db.close()


def change_password(user_id: int, old_password: str, new_password: str) -> None:
    """Fills the one real gap in the minimal Users/Login design: an
    account with no way to change its own password would leave whoever
    forgot theirs permanently locked out (if they're the only user) or
    dependent on a teammate deleting+recreating their account (if not).

    Requires the CURRENT password to confirm the change (like the
    reference tool's own Profile > Change Password screen) -- this is a
    self-service change for someone still logged in, not a "forgot
    password while locked out" recovery flow. That gap remains: with no
    email/SMTP configured, a locked-out SOLE admin still has no way back
    in except direct database access. Worth flagging to Sohaib if that
    scenario matters -- the fix would need either a mail server or a
    separate out-of-band reset mechanism.
    """
    if len(new_password) < 6:
        raise ValueError("New password must be at least 6 characters.")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found.")
        if not _verify_password(old_password, user.password_hash):
            raise ValueError("Current password is incorrect.")
        user.password_hash = _hash_password(new_password)
        db.commit()
    finally:
        db.close()


def _snapshot_summary(s: Snapshot) -> dict:
    return {
        "id": s.id,
        "client_id": s.client_id,
        "client_name": s.client.name if s.client else None,
        "solution_id": s.solution_id,
        "solution_name": s.solution.name if s.solution else None,
        "filename": s.filename,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "summary": {
            "critical": s.critical_count,
            "warning": s.warning_count,
            "info": s.info_count,
        },
    }
