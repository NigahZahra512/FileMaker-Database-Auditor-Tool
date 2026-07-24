"""
health_audit.py

Health Score + Category Report Cards
-------------------------------------
Inspired by the "Health" tab on the FM Changelog reference tool: one
overall score (0-100) built from numbers the rest of the app already
computes, PLUS a set of per-category report cards (Structure Quality,
Data Model, Broken References, Calculation Complexity, Unused
Entities) -- each with its own A-F grade, a one-line summary, and an
expandable findings list. Security and Naming Conventions cards are a
later phase: they need new DDR parsing (Accounts/Privilege Sets) this
file doesn't have yet.

This module never re-runs a detection rule itself when it can help
it; it only combines existing results (health_findings.py, explore.py,
script_audit.py, variable_audit.py, erd_audit.py), so the score can't
drift out of sync with what the other tabs show for the same snapshot.
"""

from explore import build_explore_stats, build_fields_list
from script_audit import build_script_summary
from variable_audit import build_variable_audit
from erd_audit import build_erd_summary
import health_findings as hf

# (label, weight, per-category point cap, sqrt-scale?)
# Critical/Warning are rare and each occurrence genuinely matters, so
# they stay linear. The high-volume categories (Info findings, unused
# fields/scripts, orphan tables) are sqrt-scaled with a cap -- 140
# Info findings should nudge the score, not single-handedly floor it
# to 0. Each category also has a hard cap so no one factor can ever
# tank the whole score by itself.
_PENALTY_CONFIG = {
    "critical": {"weight": 6, "cap": 40, "sqrt": False},
    "warning": {"weight": 2, "cap": 25, "sqrt": False},
    "info": {"weight": 0.3, "cap": 12, "sqrt": True},
    "unused_fields": {"weight": 0.15, "cap": 10, "sqrt": True},
    "unused_scripts": {"weight": 0.6, "cap": 12, "sqrt": True},
    "always_evaluate_fields": {"weight": 0.4, "cap": 6, "sqrt": False},
    "unstored_calc_fields": {"weight": 0.25, "cap": 6, "sqrt": False},
    "write_only_vars": {"weight": 0.8, "cap": 8, "sqrt": False},
    "orphan_tables": {"weight": 0.6, "cap": 12, "sqrt": True},
}


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _category_grade(findings: list) -> dict:
    """Turn a category's own findings list into a score/grade + counts.
    Simpler and more transparent than the global _PENALTY_CONFIG above
    (fixed points per severity, capped) since these cards need to explain
    themselves at a glance -- see the 'why' in each card's own findings,
    not a hidden weighting table."""
    critical = sum(1 for f in findings if f["severity"] == "critical")
    warning = sum(1 for f in findings if f["severity"] == "warning")
    info = sum(1 for f in findings if f["severity"] == "info")
    penalty = min(critical * 25, 70) + min(warning * 10, 50) + min(info * 3, 20)
    score = max(0, min(100, 100 - penalty))
    return {"score": score, "grade": _grade(score), "critical_count": critical, "warning_count": warning}


def _build_category(key, label, summary, findings):
    g = _category_grade(findings)
    return {
        "key": key,
        "label": label,
        "grade": g["grade"],
        "summary": summary,
        "critical_count": g["critical_count"],
        "warning_count": g["warning_count"],
        "findings": findings,
    }


def build_health_summary(data: dict, severity_counts: dict) -> dict:
    """severity_counts: {"critical": N, "warning": N, "info": N} --
    pass in the snapshot's own saved summary (already stored on the
    Snapshot row) so this doesn't need to re-run any rule."""
    fields = build_fields_list(data)
    scripts = build_script_summary(data)
    structural = build_explore_stats(data, fields, scripts)
    variables = build_variable_audit(data)
    erd = build_erd_summary(data)

    counts = {
        "critical": severity_counts.get("critical", 0),
        "warning": severity_counts.get("warning", 0),
        "info": severity_counts.get("info", 0),
        "unused_fields": structural["unused_fields"],
        "unused_scripts": structural["unused_scripts"],
        "always_evaluate_fields": structural["always_evaluate_fields"],
        "unstored_calc_fields": structural["unstored_calc_fields"],
        "write_only_vars": variables["stats"]["write_only_count"],
        "orphan_tables": erd["stats"]["orphan_table_count"],
    }

    labels = {
        "critical": "Critical findings",
        "warning": "Warning findings",
        "info": "Info findings",
        "unused_fields": "Unused fields",
        "unused_scripts": "Unused scripts",
        "always_evaluate_fields": "Always-evaluate calculations",
        "unstored_calc_fields": "Unstored calculations",
        "write_only_vars": "Write-only variables (dead code?)",
        "orphan_tables": "Orphan tables (no relationships)",
    }

    penalties = []
    total_penalty = 0.0
    for key, cfg in _PENALTY_CONFIG.items():
        count = counts[key]
        magnitude = (count ** 0.5) if cfg["sqrt"] else count
        points_lost = round(min(magnitude * cfg["weight"], cfg["cap"]), 1)
        total_penalty += points_lost
        if count:
            penalties.append({"label": labels[key], "count": count, "points_lost": points_lost})

    penalties.sort(key=lambda p: -p["points_lost"])
    score = max(0, min(100, round(100 - total_penalty)))

    # ---- category report cards ------------------------------------
    total_tables = structural["total_tables"]
    total_scripts = structural["total_scripts"]
    total_layouts = structural["total_layouts"]
    total_relationships = structural["total_relationships"]

    unused_findings, unused_field_count, unused_script_count = hf.unused_entities_findings(data)
    unused_summary_parts = []
    if unused_field_count:
        unused_summary_parts.append(f"{unused_field_count} unused fields")
    if unused_script_count:
        unused_summary_parts.append(f"{unused_script_count} unused scripts")
    unused_summary = ", ".join(unused_summary_parts) if unused_summary_parts else "No unused fields or scripts found"

    broken_findings = hf.broken_reference_findings(data)
    broken_summary = "No broken references found" if not broken_findings else (
        f"{sum(len(f['tags']) for f in broken_findings)} issue(s) found"
    )

    structure_findings = hf.structure_quality_findings(data)
    structure_summary = f"{total_tables} tables, {total_scripts} scripts, {total_layouts} layouts"

    data_model_findings_list = hf.data_model_findings(data, erd)
    data_model_summary = f"{total_tables} tables, {total_relationships} relationships"

    calc_findings = hf.calc_complexity_findings(data)
    c_stats = hf.calc_stats(data)
    calc_summary = f"{c_stats['total_calcs']} calcs, {c_stats['circular_count']} circular"

    categories = [
        _build_category("unused_entities", "Unused Entities", unused_summary, unused_findings),
        _build_category("broken_references", "Broken References", broken_summary, broken_findings),
        _build_category("structure_quality", "Structure Quality", structure_summary, structure_findings),
        _build_category("data_model", "Data Model", data_model_summary, data_model_findings_list),
        _build_category("calc_complexity", "Calculation Complexity", calc_summary, calc_findings),
    ]

    return {
        "score": score,
        "grade": _grade(score),
        "penalties": penalties,
        "structural_stats": structural,
        "categories": categories,
    }
