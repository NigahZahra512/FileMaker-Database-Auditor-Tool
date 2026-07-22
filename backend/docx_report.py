"""
docx_report.py

GROUP A FEATURE: DOCX Export
--------------------------------
Inspired by the "Download DOCX" button on the FM Changelog reference
tool's Deep Audit screen. Takes the same report dict every endpoint in
main.py already returns ({"summary": {...}, "findings": [...]}) and
builds a Word document out of it, so a non-technical client can open
the audit results in Word instead of a browser.

Mirrors the frontend's own grouping logic (frontend/index.html's
categorySectionsHtml): if a finding has a "category", group by that;
DDR results fall under Fields / Scripts / Relationships / Layouts /
Unused Fields / Unused Scripts / Call Chain, in that order. Findings
from the Script Review or SQL Review tabs don't carry a "category" --
those fall back to their "module" (e.g. "script", "sql") as a single
group, matching how renderReport() shows them on the non-DDR tabs.

Nothing here talks to the AI providers or touches the filesystem on
disk -- build_docx_report() returns an in-memory BytesIO buffer, and
main.py streams that straight back as the HTTP response body. Keeps
the same "never write anything the user didn't ask to download"
pattern as the rest of the backend.
"""

import io
from datetime import datetime, timezone

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

SEVERITY_ORDER = {"Critical": 0, "Warning": 1, "Info": 2}
CATEGORY_ORDER = [
    "Fields", "Scripts", "Relationships", "Layouts",
    "Unused Fields", "Unused Scripts", "Call Chain",
]

SEVERITY_COLORS = {
    "Critical": RGBColor(0xB0, 0x20, 0x20),
    "Warning": RGBColor(0xB0, 0x7A, 0x10),
    "Info": RGBColor(0x30, 0x60, 0xA0),
}


def _group_findings(findings):
    groups = {}
    for f in findings:
        cat = f.get("category") or f.get("module") or "Findings"
        groups.setdefault(cat, []).append(f)
    ordered_keys = (
        [c for c in CATEGORY_ORDER if c in groups]
        + [c for c in groups if c not in CATEGORY_ORDER]
    )
    return [(cat, groups[cat]) for cat in ordered_keys]


def _add_summary_table(doc, summary):
    table = doc.add_table(rows=2, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.style = "Light Grid Accent 1"
    headers = ["Critical", "Warning", "Info"]
    values = [summary.get("critical", 0), summary.get("warning", 0), summary.get("info", 0)]
    for col, (label, value) in enumerate(zip(headers, values)):
        head_cell = table.cell(0, col)
        head_cell.text = label
        head_cell.paragraphs[0].runs[0].bold = True
        table.cell(1, col).text = str(value)
        table.cell(1, col).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER


def _add_findings_table(doc, items):
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for cell, label in zip(hdr, ["Severity", "Location", "Description", "Suggestion"]):
        cell.text = label
        cell.paragraphs[0].runs[0].bold = True

    for f in items:
        row = table.add_row().cells
        sev = f.get("severity", "Info")
        sev_run = row[0].paragraphs[0].add_run(sev)
        sev_run.bold = True
        sev_run.font.color.rgb = SEVERITY_COLORS.get(sev, RGBColor(0, 0, 0))
        row[1].text = f.get("location", "") or ""
        row[2].text = f.get("description", "") or ""
        row[3].text = f.get("suggestion", "") or ""


def build_docx_report(report: dict, source_label: str) -> io.BytesIO:
    """Builds a Word document from a report dict and returns it as an
    in-memory BytesIO buffer, positioned at the start and ready to be
    streamed back as an HTTP response."""
    findings = report.get("findings", []) or []
    summary = report.get("summary", {}) or {}
    findings = sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 99))

    doc = Document()

    title = doc.add_heading("FileMaker Database Audit Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT

    meta = doc.add_paragraph()
    meta.add_run(f"Source: {source_label}\n").italic = True
    meta.add_run(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    ).italic = True

    doc.add_heading("Summary", level=1)
    if findings:
        _add_summary_table(doc, summary)
    else:
        doc.add_paragraph("No findings -- looks clean, or nothing has been analysed yet.")

    for category, items in _group_findings(findings):
        doc.add_heading(category, level=1)
        doc.add_paragraph(f"{len(items)} finding{'s' if len(items) != 1 else ''}")
        _add_findings_table(doc, items)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
