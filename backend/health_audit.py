"""
health_audit.py

Health Score
------------
Inspired by the "Health" tab on the FM Changelog reference tool: one
overall score (0-100) built from numbers the rest of the app already
computes -- the saved Critical/Warning/Info finding counts, Explore's
structural stats, the Variable audit, and the ERD's orphan-table
count -- plus a short breakdown of which factors cost the most
points.

This module never re-runs a detection rule itself; it only combines
existing results, so the score can't drift out of sync with what the
other tabs show for the same snapshot.
"""

from explore import build_explore_stats, build_fields_list
from script_audit import build_script_summary
from variable_audit import build_variable_audit
from erd_audit import build_erd_summary

# (label, stat source, weight per occurrence)
_PENALTY_WEIGHTS = {
    "critical": 5,
    "warning": 2,
    "info": 0.5,
    "unused_fields": 0.2,
    "unused_scripts": 1,
    "always_evaluate_fields": 0.5,
    "unstored_calc_fields": 0.3,
    "write_only_vars": 1,
    "orphan_tables": 1,
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
    for key, weight in _PENALTY_WEIGHTS.items():
        count = counts[key]
        points_lost = round(count * weight, 1)
        total_penalty += points_lost
        if count:
            penalties.append({"label": labels[key], "count": count, "points_lost": points_lost})

    penalties.sort(key=lambda p: -p["points_lost"])
    score = max(0, min(100, round(100 - total_penalty)))

    return {
        "score": score,
        "grade": _grade(score),
        "penalties": penalties,
        "structural_stats": structural,
    }
