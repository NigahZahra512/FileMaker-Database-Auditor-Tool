"""
table_audit.py

STEP 5 OF THE ROADMAP: Deep Per-Table Audit
--------------------------------------------
Click into any single table from a saved snapshot and see everything
about it in one place: every field (type, calculation, storage,
validation, unused-or-not), which other tables it's related to and
through which fields, which layouts actually place its fields, and
which scripts touch it.

WHY THIS NEEDS A SAVED SNAPSHOT (same reasoning as compare_snapshots.py):
A fresh /analyse-ddr upload only keeps the parsed DDR dict in memory for
the length of that one request -- the findings report is what survives
into the response, not the full per-table structure. A saved snapshot's
`parsed_data_json` already has the complete parsed dict sitting in the
database, so this module works off snapshot data rather than asking
main.py to also ship the (potentially large) raw parsed dict back on
every single analysis.

Reuses unused_analysis.py's field-reference scan instead of
duplicating it, so "is this field unused" always means the exact same
thing here as it does on the main DDR Analysis / Unused Fields report.
"""

from unused_analysis import _collect_field_references


def build_table_summary(data: dict) -> list[dict]:
    """One row per table -- the lightweight list used for the table
    picker screen. No field-by-field detail here, just enough to help
    someone decide which table to open next."""
    referenced = _collect_field_references(data)
    summaries = []

    for table_name, table in data.get("tables", {}).items():
        fields = table.get("fields", [])
        unstored_calc_count = sum(
            1 for f in fields if f.get("is_calculation") and f.get("storage_index") == "None"
        )
        always_evaluate_count = sum(
            1 for f in fields if f.get("is_calculation") and f.get("always_evaluate")
        )
        unused_field_count = sum(
            1 for f in fields if (table_name, f.get("name")) not in referenced
        )
        validated_field_count = sum(1 for f in fields if f.get("has_validation"))

        summaries.append({
            "table_name": table_name,
            "record_count": table.get("record_count", 0),
            "field_count": len(fields),
            "unstored_calc_count": unstored_calc_count,
            "always_evaluate_count": always_evaluate_count,
            "unused_field_count": unused_field_count,
            "validated_field_count": validated_field_count,
        })

    summaries.sort(key=lambda s: s["table_name"].lower())
    return summaries


def build_table_detail(data: dict, table_name: str) -> dict | None:
    """Full audit for one table. Returns None if the table doesn't
    exist in this snapshot's parsed data (e.g. stale link, typo'd
    table name in the URL)."""
    table = data.get("tables", {}).get(table_name)
    if table is None:
        return None

    referenced = _collect_field_references(data)

    fields_detail = []
    for f in table.get("fields", []):
        fields_detail.append({
            "name": f.get("name"),
            "data_type": f.get("data_type"),
            "field_type": f.get("field_type"),
            "is_calculation": f.get("is_calculation", False),
            "calculation_text": f.get("calculation_text"),
            "always_evaluate": f.get("always_evaluate", False),
            "storage_index": f.get("storage_index"),
            "is_global": f.get("is_global", False),
            "has_validation": f.get("has_validation", False),
            "validation_flags": f.get("validation_flags", {}),
            "is_unused": (table_name, f.get("name")) not in referenced,
        })

    # Relationships that touch this table, from either side, with the
    # OTHER table named so the UI can show "related to X via Y = Z".
    relationships = []
    for rel in data.get("relationships", []):
        left, right = rel.get("left_table"), rel.get("right_table")
        if table_name not in (left, right):
            continue
        other_table = right if left == table_name else left
        predicates = [
            {
                "type": p.get("type"),
                "left_field": p.get("left_field"),
                "right_field": p.get("right_field"),
            }
            for p in rel.get("predicates", [])
        ]
        relationships.append({"other_table": other_table, "predicates": predicates})

    # Layouts that place at least one field from this table.
    layouts = []
    for layout in data.get("layouts", []):
        used = [
            fo.get("field")
            for fo in layout.get("field_objects", [])
            if fo.get("table") == table_name
        ]
        if used:
            layouts.append({
                "layout_name": layout.get("name"),
                "fields_used": sorted(set(used)),
            })

    # Scripts with at least one step referencing a field on this table
    # (structured "Set Field [Table::Field]"-style refs, same source
    # ddr_parser.py already captures for every step).
    scripts = []
    for script in data.get("scripts", []):
        touched_fields = set()
        for step in script.get("steps", []):
            ref = step.get("field")
            if ref and ref.get("table") == table_name and ref.get("name"):
                touched_fields.add(ref["name"])
        if touched_fields:
            scripts.append({
                "script_name": script.get("name"),
                "fields_touched": sorted(touched_fields),
            })

    return {
        "table_name": table_name,
        "record_count": table.get("record_count", 0),
        "fields": fields_detail,
        "relationships": relationships,
        "layouts": layouts,
        "scripts": scripts,
    }
