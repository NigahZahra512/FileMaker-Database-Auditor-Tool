"""
main.py

DAY 4: FastAPI backend for the Web UI
-----------------------------------------
Same overall approach as the Week 2 chatbot project: a small FastAPI
backend with a few endpoints, and a plain HTML/CSS/JS frontend (no
React/build step) that just calls those endpoints with fetch().

This file wires together everything already built in Day 1-3:
    ddr_parser.py        -> Day 1  (parses an uploaded DDR XML file)
    detection_rules.py    -> Day 2  (18 static rules on the parsed data)
    script_reviewer.py    -> Day 3  (AI review of a pasted script)
    sql_reviewer.py       -> Day 3  (AI review of a pasted SQL statement)

THREE ENDPOINTS (one per tab, paths match the brief's API spec):
    POST /analyse-ddr    - multipart file upload (the DDR .xml)
    POST /review-script  - JSON body: {"script_text": "..."}
    POST /review-sql     - JSON body: {"query": "..."}
                            -> response also includes "rewritten_query"

All three ALWAYS return a 200 with a JSON body shaped like:
    {"summary": {"critical": N, "warning": N, "info": N}, "findings": [...]}
(summary keys are lowercase per the brief; each finding's own
"severity" field stays "Critical"/"Warning"/"Info")
even if something inside failed -- errors get converted into a single
Info-level finding instead of an HTTP 500, so the frontend never has
to handle "the whole request blew up" as a special case. This keeps
the same "always valid JSON, no exceptions" guarantee from Day 3
consistent all the way out to the browser.

HOW TO RUN:
    pip install fastapi uvicorn python-multipart python-dotenv anthropic google-generativeai
    python main.py
    -> open http://127.0.0.1:8000 in your browser

FOLDER LAYOUT THIS FILE EXPECTS:
    backend/main.py              (this file)
    backend/ddr_parser.py        (copy of Day 1)
    backend/detection_rules.py   (copy of Day 2)
    backend/ai_client.py         (copy of Day 3)
    backend/script_reviewer.py   (copy of Day 3)
    backend/sql_reviewer.py      (copy of Day 3)
    backend/.env                 (your API key)
    frontend/index.html          (the 3-tab UI)
"""

import os
import sys
import json
import tempfile
import traceback

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ddr_parser import parse_ddr
from detection_rules import run_all_rules
from script_reviewer import review_script_text
from sql_reviewer import review_sql_text, get_sql_rewrite
from ai_client import set_runtime_config, get_runtime_status
from unused_analysis import run_unused_rules
from call_chain import build_call_chain
from docx_report import build_docx_report
from compare_snapshots import compare_snapshots
from table_audit import build_table_summary, build_table_detail
from script_audit import build_script_summary, build_script_detail
from sql_audit import build_sql_audit
from database import (
    init_db,
    get_or_create_client,
    list_clients,
    create_snapshot,
    list_snapshots,
    get_snapshot,
    rename_client,
    delete_client,
    delete_snapshot,
    dashboard_summary,
    timeline_summary,
)

app = FastAPI(title="FileMaker Database Auditor Tool")

# STEP 1 (roadmap): create auditor.db / its tables on startup if they
# don't exist yet. Safe to call every time the app boots.
init_db()

SEVERITY_ORDER = {"Critical": 0, "Warning": 1, "Info": 2}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_report(findings: list[dict]) -> dict:
    """Sorts findings by severity and computes the summary counts.

    NOTE: the finding's own "severity" field stays "Critical" / "Warning"
    / "Info" (matches the Finding Object Structure in the brief), but the
    summary dict keys are lowercase ("critical"/"warning"/"info") to match
    the brief's documented endpoint response shape
    (`summary: { critical: N, warning: N, info: N }`)."""
    findings = sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 99))
    summary = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity")
        if sev in SEVERITY_ORDER:
            summary[sev.lower()] += 1
    return {"summary": summary, "findings": findings}


def _error_report(message: str, module: str) -> dict:
    """Never let an endpoint return a raw 500 -- turn any unexpected
    failure into a single Info finding so the frontend always gets a
    normal-shaped response to render."""
    finding = {
        "module": module,
        "severity": "Info",
        "location": "Server",
        "description": f"Something went wrong while processing this request: {message}",
        "suggestion": "Check the terminal running the backend for the full error, and try again.",
    }
    return _build_report([finding])


class ScriptReviewRequest(BaseModel):
    script_text: str


class SqlReviewRequest(BaseModel):
    query: str


class SettingsRequest(BaseModel):
    provider: str
    api_key: str
    custom_base_url: str | None = None
    custom_model: str | None = None


class DocxExportRequest(BaseModel):
    report: dict
    source_label: str = "FileMaker Audit"


class ClientCreateRequest(BaseModel):
    name: str


class ClientRenameRequest(BaseModel):
    name: str


class CompareRequest(BaseModel):
    snapshot_id_a: int
    snapshot_id_b: int


# ---------------------------------------------------------------------------
# Settings: lets the frontend's Settings panel read/write which AI provider
# and key are active, without anyone touching the .env file. Key is kept in
# server memory only (see ai_client.set_runtime_config) -- never written
# to disk, resets on server restart.
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def get_settings():
    return JSONResponse(get_runtime_status())


@app.post("/api/settings")
async def save_settings(body: SettingsRequest):
    set_runtime_config(
        provider=body.provider,
        api_key=body.api_key,
        custom_base_url=body.custom_base_url,
        custom_model=body.custom_model,
    )
    return JSONResponse(get_runtime_status())


# ---------------------------------------------------------------------------
# Tab 1: DDR file upload -> Day 1 parser + Day 2 static rules
# ---------------------------------------------------------------------------

@app.post("/analyse-ddr")
async def analyze_ddr(
    file: UploadFile = File(...),
    client_name: str | None = Form(None),
    save_snapshot: bool = Form(False),
):
    tmp_path = None
    try:
        # Save the uploaded file to a temp path -- ddr_parser.py's
        # iterparse-based parser reads from a file path, not from
        # in-memory bytes.
        suffix = os.path.splitext(file.filename or "ddr.xml")[1] or ".xml"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        data = parse_ddr(tmp_path)
        # 18 static rules (Day 2) + unused fields/scripts + call chain
        # (Group A additions, inspired by the FM Changelog reference
        # tool's Explore tab) -- all three share the exact same finding
        # shape, so they just concatenate into one list.
        findings = run_all_rules(data) + run_unused_rules(data) + build_call_chain(data)
        report = _build_report(findings)

        # STEP 1 (roadmap): optionally persist this analysis as a
        # snapshot -- get-or-create the client by name, then store the
        # parsed DDR dict + the report as one row. The frontend decides
        # whether to send save_snapshot=true (checkbox) and a
        # client_name; if either is missing, behaviour is unchanged
        # from before (analyze, show, don't save).
        if save_snapshot and client_name and client_name.strip():
            try:
                client = get_or_create_client(client_name)
                snapshot = create_snapshot(
                    client_id=client.id,
                    filename=file.filename or "ddr.xml",
                    parsed_data=data,
                    report=report,
                )
                report["snapshot"] = snapshot
            except Exception as e:
                # Saving the snapshot failing should never hide the
                # analysis the user is waiting on -- report it back as
                # a soft warning field instead of a 500.
                traceback.print_exc()
                report["snapshot_error"] = str(e)

        return JSONResponse(report)

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(_error_report(str(e), module="ddr"))

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# Tab 2: pasted script text -> Day 3 AI script review
# ---------------------------------------------------------------------------

@app.post("/review-script")
async def review_script_endpoint(body: ScriptReviewRequest):
    try:
        findings = review_script_text(body.script_text)
        return JSONResponse(_build_report(findings))
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(_error_report(str(e), module="script"))


# ---------------------------------------------------------------------------
# Tab 3: pasted SQL text -> Day 3 AI SQL review
# ---------------------------------------------------------------------------

@app.post("/review-sql")
async def review_sql_endpoint(body: SqlReviewRequest):
    try:
        findings = review_sql_text(body.query)
        report = _build_report(findings)
        # DAY 5: the demo requirement is "a SQL paste producing a
        # rewrite" -- alongside the usual findings list, also return
        # an actual corrected version of the query in the same
        # response, so the frontend can show both in one place.
        # "rewritten_query" (string | null) matches the brief's
        # documented response shape; "rewrite_explanation" is an extra
        # field the contract doesn't forbid, kept so the UI can still
        # explain *why* the query changed.
        rewrite = get_sql_rewrite(body.query)
        report["rewritten_query"] = rewrite["rewritten_sql"] or None
        report["rewrite_explanation"] = rewrite["explanation"]
        return JSONResponse(report)
    except Exception as e:
        traceback.print_exc()
        error_report = _error_report(str(e), module="sql")
        error_report["rewritten_query"] = None
        error_report["rewrite_explanation"] = "Not available due to an error."
        return JSONResponse(error_report)


# ---------------------------------------------------------------------------
# STEP 1 (roadmap): Clients + Snapshots
#
# These sit alongside /analyse-ddr rather than replacing it:
#   - /analyse-ddr stays the "analyze and show" endpoint, now with an
#     optional save.
#   - the endpoints below are for the frontend to populate the client
#     dropdown/datalist, and to list + reload past snapshots (Step 2's
#     "Snapshot History" screen builds directly on top of these).
# ---------------------------------------------------------------------------


@app.get("/api/clients")
async def get_clients():
    return JSONResponse(list_clients())


@app.post("/api/clients")
async def post_client(body: ClientCreateRequest):
    try:
        client = get_or_create_client(body.name)
        return JSONResponse({"id": client.id, "name": client.name})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.put("/api/clients/{client_id}")
async def put_client(client_id: int, body: ClientRenameRequest):
    try:
        client = rename_client(client_id, body.name)
        return JSONResponse(client)
    except ValueError as e:
        status = 404 if "not found" in str(e).lower() else 400
        return JSONResponse({"error": str(e)}, status_code=status)


@app.delete("/api/clients/{client_id}")
async def delete_client_endpoint(client_id: int):
    ok = delete_client(client_id)
    if not ok:
        return JSONResponse({"error": "Client not found."}, status_code=404)
    return JSONResponse({"deleted": True})


@app.get("/api/snapshots")
async def get_snapshots(client_id: int | None = None):
    return JSONResponse(list_snapshots(client_id=client_id))


@app.get("/api/snapshots/{snapshot_id}")
async def get_snapshot_detail(snapshot_id: int):
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        return JSONResponse({"error": "Snapshot not found."}, status_code=404)
    return JSONResponse(snapshot)


@app.delete("/api/snapshots/{snapshot_id}")
async def delete_snapshot_endpoint(snapshot_id: int):
    ok = delete_snapshot(snapshot_id)
    if not ok:
        return JSONResponse({"error": "Snapshot not found."}, status_code=404)
    return JSONResponse({"deleted": True})


# ---------------------------------------------------------------------------
# STEP 4 (roadmap): Multi-Client Dashboard
#
# One combined endpoint rather than making the frontend stitch together
# /api/clients + N calls to /api/snapshots -- this returns everything the
# dashboard tab needs (per client: snapshot count, latest snapshot, and a
# Critical-count trend vs. the snapshot before it) in a single round trip.
# ---------------------------------------------------------------------------


@app.get("/api/dashboard")
async def get_dashboard():
    return JSONResponse(dashboard_summary())


# ---------------------------------------------------------------------------
# STEP 6 (roadmap): Timeline / Releases
#
# Every saved snapshot represents a point-in-time release of a client's
# database. This endpoint returns those releases chronologically, including
# the C/W/I delta from the previous saved release for the same client.
# ---------------------------------------------------------------------------


@app.get("/api/timeline")
async def get_timeline(client_id: int | None = None):
    return JSONResponse(timeline_summary(client_id=client_id))


# ---------------------------------------------------------------------------
# STEP 3 (roadmap): Compare two snapshots
#
# Doesn't touch the DDR file at all -- both snapshots already have their
# parsed_data stored (Step 1), so this just loads two rows from the
# database and diffs them. Older snapshot (by created_at) is always
# treated as the "before" side regardless of the order the two ids were
# sent in, so "Added"/"Removed" always reads in the intuitive direction.
# ---------------------------------------------------------------------------


@app.post("/api/compare-snapshots")
async def compare_snapshots_endpoint(body: CompareRequest):
    snap_a = get_snapshot(body.snapshot_id_a)
    snap_b = get_snapshot(body.snapshot_id_b)
    if snap_a is None or snap_b is None:
        return JSONResponse({"error": "One or both snapshots were not found."}, status_code=404)
    if snap_a["id"] == snap_b["id"]:
        return JSONResponse({"error": "Choose two different snapshots to compare."}, status_code=400)

    # Order by created_at so the diff direction always reads old -> new,
    # no matter which snapshot the frontend sent as "a" vs "b".
    older, newer = (snap_a, snap_b) if snap_a["created_at"] <= snap_b["created_at"] else (snap_b, snap_a)
    label_older = f"{older['filename']} ({older['created_at']})"
    label_newer = f"{newer['filename']} ({newer['created_at']})"

    try:
        findings = compare_snapshots(older["parsed_data"], newer["parsed_data"], label_older, label_newer)
        report = _build_report(findings)
        report["compared"] = {
            "older": {k: older[k] for k in ("id", "client_name", "filename", "created_at")},
            "newer": {k: newer[k] for k in ("id", "client_name", "filename", "created_at")},
        }
        return JSONResponse(report)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(_error_report(str(e), module="compare"))


# ---------------------------------------------------------------------------
# STEP 5 (roadmap): Deep Per-Table Audit
#
# Works off a saved snapshot's parsed_data (same reasoning as Compare
# Snapshots above -- a fresh unsaved analysis doesn't keep its full
# parsed dict around after the response is sent). Two endpoints:
#   - the table picker list (lightweight per-table counts)
#   - the full detail for one table (fields, relationships, layouts,
#     scripts) once the user clicks into it
# ---------------------------------------------------------------------------


@app.get("/api/snapshots/{snapshot_id}/table-audit")
async def get_table_audit_summary(snapshot_id: int):
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        return JSONResponse({"error": "Snapshot not found."}, status_code=404)
    try:
        tables = build_table_summary(snapshot["parsed_data"])
        return JSONResponse({
            "snapshot": {k: snapshot[k] for k in ("id", "client_name", "filename", "created_at")},
            "tables": tables,
        })
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/snapshots/{snapshot_id}/table-audit/{table_name}")
async def get_table_audit_detail(snapshot_id: int, table_name: str):
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        return JSONResponse({"error": "Snapshot not found."}, status_code=404)
    try:
        detail = build_table_detail(snapshot["parsed_data"], table_name)
        if detail is None:
            return JSONResponse({"error": f'Table "{table_name}" not found in this snapshot.'}, status_code=404)
        return JSONResponse(detail)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Script Audit: scripts are read from the saved DDR, not copy/pasted.
# ---------------------------------------------------------------------------


@app.get("/api/snapshots/{snapshot_id}/script-audit")
async def get_script_audit_summary(snapshot_id: int):
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        return JSONResponse({"error": "Snapshot not found."}, status_code=404)
    return JSONResponse({
        "snapshot": {k: snapshot[k] for k in ("id", "client_name", "filename", "created_at")},
        "scripts": build_script_summary(snapshot["parsed_data"]),
    })


@app.get("/api/snapshots/{snapshot_id}/script-audit/{script_name}")
async def get_script_audit_detail(snapshot_id: int, script_name: str):
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        return JSONResponse({"error": "Snapshot not found."}, status_code=404)
    detail = build_script_detail(snapshot["parsed_data"], script_name)
    if detail is None:
        return JSONResponse({"error": f'Script "{script_name}" not found in this snapshot.'}, status_code=404)
    return JSONResponse(detail)


# ---------------------------------------------------------------------------
# ExecuteSQL Audit: discover SQL-related steps directly from saved DDR data.
# ---------------------------------------------------------------------------


@app.get("/api/snapshots/{snapshot_id}/sql-audit")
async def get_sql_audit(snapshot_id: int):
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        return JSONResponse({"error": "Snapshot not found."}, status_code=404)
    return JSONResponse({
        "snapshot": {k: snapshot[k] for k in ("id", "client_name", "filename", "created_at")},
        "queries": build_sql_audit(snapshot["parsed_data"]),
    })


# ---------------------------------------------------------------------------
# Shared: DOCX export. Any tab can call this with whatever report dict
# it already has in memory (frontend/index.html's `latestReports`) --
# this endpoint doesn't re-run any analysis, it just formats an
# existing report as a downloadable Word document.
# ---------------------------------------------------------------------------

@app.post("/export-docx")
async def export_docx_endpoint(body: DocxExportRequest):
    buf = build_docx_report(body.report, body.source_label)
    return StreamingResponse(
        buf,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="filemaker_audit_report.docx"'
        },
    )


# ---------------------------------------------------------------------------
# Serve the frontend (the plain HTML/CSS/JS UI) at the root URL
# ---------------------------------------------------------------------------

def _frontend_dir() -> str:
    """
    Resolve the frontend folder's path in two different situations:
      - Normal `python main.py` run: frontend/ lives one level up from
        this file (backend/main.py -> ../frontend).
      - Bundled as a PyInstaller .exe (`sys.frozen` is True): PyInstaller
        unpacks bundled data into a temp folder at sys._MEIPASS instead,
        so the "../frontend" relative path no longer points anywhere.
    """
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "frontend")
    return os.path.join(os.path.dirname(__file__), "..", "frontend")


FRONTEND_DIR = _frontend_dir()
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import threading
    import webbrowser

    import uvicorn

    # When running as a double-clicked .exe there's no terminal for the
    # person to read "open http://127.0.0.1:8000" from -- open their
    # default browser automatically instead, shortly after the server
    # has had time to start.
    if getattr(sys, "frozen", False):
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()

    uvicorn.run(app, host="127.0.0.1", port=8000)
