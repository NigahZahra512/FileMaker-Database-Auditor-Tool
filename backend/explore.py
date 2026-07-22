"""
explore.py

GROUP A FEATURE: Unified Explore Page
--------------------------------------
Inspired by the "Explore" tab on the FM Changelog reference tool: one
page, one snapshot, tabs across the top (Tables / Fields / Scripts /
Layouts / Relationships), each tab a searchable list, and clicking a
row opens the full detail for that item -- all without leaving the
page or re-uploading anything.

Nothing here re-parses the DDR or re-implements analysis that already
exists elsewhere. It only *flattens* the already-parsed snapshot data
(`parsed_data`) into the shapes the Explore UI needs, reusing the same
building blocks the other audit tabs already use:
    table_audit.build_table_summary   -> Tables tab
    script_audit.build_script_summary -> Scripts tab
    unused_analysis._collect_field_references -> "is this field unused"
    call_chain._build_call_graph      -> script call counts for the stats strip

Per-row DETAIL is likewise not duplicated:
    - a Table row's detail is the existing /table-audit/{name} endpoint
    - a Script row's detail is the existing /script-audit/{name} endpoint
    - Field / Layout / Relationship rows carry enough in the list
      response itself (calculation text, field/portal objects,
      predicates) that no extra round trip is needed to show their
      detail -- they're small, flat records to begin with.
"""

from call_chain import _build_call_graph
from table_audit import build_table_summary
from script_audit import build_script_summary
from unused_analysis import _collect_field_references


def build_fields_list(data: dict) -> list[dict]:
    """One row per field, across every table -- the flat list the
    Fields tab searches/filters. Table name is carried on each row so
    the same list works whether the UI is grouping by table or not."""
    referenced = _collect_field_references(data)
    rows = []
    for table_name, table in data.get("tables", {}).items():
        for f in table.get("fields", []):
            rows.append({
                "table_name": table_name,
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
    rows.sort(key=lambda r: (r["table_name"].lower(), (r["name"] or "").lower()))
    return rows


def build_layouts_list(data: dict) -> list[dict]:
    """One row per layout, with enough of its own field/portal detail
    inlined that the Layouts tab doesn't need a second endpoint."""
    rows = []
    for layout in data.get("layouts", []):
        field_objects = layout.get("field_objects", [])
        portal_objects = layout.get("portal_objects", [])
        rows.append({
            "name": layout.get("name"),
            "id": layout.get("id"),
            "object_count": layout.get("object_count", 0),
            "field_object_count": len(field_objects),
            "portal_object_count": len(portal_objects),
            "max_conditional_format_depth": layout.get("max_conditional_format_depth", 0),
            "field_objects": field_objects,
            "portal_objects": portal_objects,
        })
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return rows


def build_relationships_list(data: dict) -> list[dict]:
    """One row per relationship, both tables named plus every
    predicate spelled out (left field / operator / right field) so
    the Relationships tab can render the full detail inline."""
    rows = []
    for rel in data.get("relationships", []):
        predicates = rel.get("predicates", [])
        rows.append({
            "id": rel.get("id"),
            "left_table": rel.get("left_table"),
            "right_table": rel.get("right_table"),
            "predicate_count": len(predicates),
            "predicates": predicates,
        })
    rows.sort(key=lambda r: ((r["left_table"] or ""), (r["right_table"] or "")))
    return rows


def build_explore_stats(data: dict, fields: list[dict], scripts: list[dict]) -> dict:
    """The summary strip across the top of the Explore page -- cheap
    aggregate counts computed from lists that were already built, so
    this adds no extra pass over the raw parsed data."""
    outgoing, _incoming = _build_call_graph(data)
    script_calls = sum(len(targets) for targets in outgoing.values())

    return {
        "total_tables": len(data.get("tables", {})),
        "total_fields": len(fields),
        "total_scripts": len(scripts),
        "total_layouts": len(data.get("layouts", [])),
        "total_relationships": len(data.get("relationships", [])),
        "script_calls": script_calls,
        "unused_fields": sum(1 for f in fields if f["is_unused"]),
        "unused_scripts": sum(1 for s in scripts if not s["calls"] and not s["called_by"]),
        "always_evaluate_fields": sum(1 for f in fields if f["always_evaluate"]),
        "unstored_calc_fields": sum(
            1 for f in fields if f["is_calculation"] and f["storage_index"] == "None"
        ),
    }


def build_explore(data: dict) -> dict:
    """Everything the Explore page needs for one snapshot, in a single
    response: summary stats + the five tab lists."""
    fields = build_fields_list(data)
    scripts = build_script_summary(data)

    return {
        "stats": build_explore_stats(data, fields, scripts),
        "tables": build_table_summary(data),
        "fields": fields,
        "scripts": scripts,
        "layouts": build_layouts_list(data),
        "relationships": build_relationships_list(data),
    }
