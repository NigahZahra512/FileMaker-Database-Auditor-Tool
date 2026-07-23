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
import re

# Functions that let a calculation reach a field it doesn't reference
# by name at author-time -- static analysis can only report the
# compile-time literal cases (see the "Verification Before Deploy"
# note the Deep Audit view surfaces alongside this).
DYNAMIC_ACCESS_PATTERN = re.compile(r"\b(ExecuteSQL|GetField|GetFieldName|Evaluate)\s*\(", re.IGNORECASE)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = curr
    return prev[-1]


def _find_likely_typos(field_names: list[str]) -> list[dict]:
    """Pairs of field names on the same table that are suspiciously
    close to each other (small edit distance, not an identical or
    pure-case rename) -- a common sign of a copy-pasted field that
    should have been renamed but wasn't."""
    pairs = []
    seen = set()
    names = [n for n in field_names if n]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if a.lower() == b.lower():
                continue
            if max(len(a), len(b)) <= 3:
                continue
            dist = _levenshtein(a.lower(), b.lower())
            if 0 < dist <= 2:
                key = tuple(sorted((a, b)))
                if key not in seen:
                    seen.add(key)
                    pairs.append({"field_a": a, "field_b": b, "distance": dist})
    return pairs


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

    # Auto-Enter Calcs that don't re-evaluate on every commit -- the
    # "Other Auto-Enter Calcs" section on the Deep Audit view. Distinct
    # from unstored calc FIELDS: this covers any field (including plain
    # Normal fields like a UUID primary key) that has an auto-enter
    # calculation defined on it.
    calc_field_count = sum(1 for f in table.get("fields", []) if (f.get("field_type") or "").lower() == "calculation")
    auto_enter_fields = [f for f in table.get("fields", []) if f.get("is_calculation")]
    other_auto_enter_calcs = [
        {
            "name": f.get("name"),
            "data_type": f.get("data_type"),
            "calculation_text": f.get("calculation_text"),
        }
        for f in auto_enter_fields if not f.get("always_evaluate")
    ]

    # Dynamic access: fields whose own calculation reaches other fields
    # through ExecuteSQL / GetField / Evaluate instead of a literal
    # reference -- these can't be safely renamed/removed by static
    # analysis alone (see docstring at the top of this module).
    dynamic_access_fields = []
    for f in table.get("fields", []):
        calc = f.get("calculation_text") or ""
        match = DYNAMIC_ACCESS_PATTERN.search(calc)
        if match:
            dynamic_access_fields.append({
                "name": f.get("name"),
                "function": match.group(1),
                "calculation_text": calc,
            })

    likely_typos = _find_likely_typos([f.get("name") for f in table.get("fields", [])])

    return {
        "table_name": table_name,
        "record_count": table.get("record_count", 0),
        "fields": fields_detail,
        "relationships": relationships,
        "layouts": layouts,
        "scripts": scripts,
        "calc_field_count": calc_field_count,
        "auto_enter_total": len(auto_enter_fields),
        "other_auto_enter_calcs": other_auto_enter_calcs,
        "dynamic_access_fields": dynamic_access_fields,
        "likely_typos": likely_typos,
    }
