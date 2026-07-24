"""
compare_snapshots.py

STEP 3 OF THE ROADMAP: Compare Snapshots
------------------------------------------
Takes two parsed DDR dicts (the exact `parsed_data` shape ddr_parser.py's
parse_ddr() produces -- and the same shape database.py stores for every
saved snapshot) and works out what changed between them: which tables,
fields, scripts, relationships, and layouts were added, removed, or
modified.

DESIGN CHOICE -- reuse the finding shape:
    Rather than inventing a brand new UI component for "diff results",
    this returns a plain list of findings using the EXACT same shape as
    detection_rules.py / unused_analysis.py / call_chain.py:
        {
          "module": "compare",
          "category": "Fields Added" | "Fields Removed" | "Fields Changed"
                       | "Scripts Added" | ... | "Layouts Changed"
                       | "Tables Added" | "Tables Removed"
                       | "Relationships Added" | "Relationships Removed",
          "severity": "Info" | "Warning",
          "location": "TableName" | "TableName::FieldName" | "ScriptName",
          "description": "...",
          "suggestion": "...",
        }
    That means the frontend's existing category-box grid + findings
    table (renderDDRReport / categorySectionsHtml / findingsTableHtml)
    can render a comparison with ZERO new rendering code -- it's just
    another findings list.

SEVERITY CONVENTION used here:
    Added   -> Info    (growth, usually not concerning on its own)
    Removed -> Warning (something disappeared -- worth a second look)
    Changed -> Warning (behaviour may have shifted -- worth a second look)
"""


def _field_key(field: dict) -> str:
    return field.get("name", "")


def _field_signature(field: dict) -> tuple:
    """The attributes that matter for detecting a "changed" field.
    Renaming isn't detected here (a rename looks like remove+add,
    same as most diff tools) -- only in-place attribute changes."""
    return (
        field.get("data_type"),
        field.get("field_type"),
        bool(field.get("is_calculation")),
        bool(field.get("always_evaluate")),
        field.get("calculation_text"),
        bool(field.get("is_global")),
        field.get("storage_index"),
        bool(field.get("has_validation")),
        tuple(sorted((field.get("validation_flags") or {}).items())),
    )


def _script_signature(script: dict) -> tuple:
    steps = script.get("steps") or []
    return tuple((s.get("name"), s.get("text")) for s in steps)


def _relationship_key(rel: dict) -> str:
    # Prefer the DDR's own id (stable across re-exports of the same
    # solution); fall back to the table pair if id is missing.
    if rel.get("id"):
        return f"id:{rel['id']}"
    return f"{rel.get('left_table')}<->{rel.get('right_table')}"


def compare_snapshots(data_a: dict, data_b: dict, label_a: str = "Snapshot A", label_b: str = "Snapshot B") -> list[dict]:
    """Returns findings describing what changed going from data_a -> data_b
    (data_a = older/baseline snapshot, data_b = newer snapshot)."""
    findings: list[dict] = []

    tables_a = data_a.get("tables", {}) or {}
    tables_b = data_b.get("tables", {}) or {}

    # ---------------- Tables ----------------
    added_tables = sorted(set(tables_b) - set(tables_a))
    removed_tables = sorted(set(tables_a) - set(tables_b))
    for t in added_tables:
        findings.append(_finding("Tables Added", "Info", t,
            f"Table '{t}' exists in {label_b} but not in {label_a}.",
            "New table -- confirm it's expected and has the right access privileges set up."))
    for t in removed_tables:
        findings.append(_finding("Tables Removed", "Warning", t,
            f"Table '{t}' existed in {label_a} but is missing from {label_b}.",
            "Confirm this table was intentionally deleted -- any scripts/layouts still referencing it will break."))

    # ---------------- Fields (per common table) ----------------
    common_tables = sorted(set(tables_a) & set(tables_b))
    for table in common_tables:
        fields_a = {_field_key(f): f for f in (tables_a[table].get("fields") or [])}
        fields_b = {_field_key(f): f for f in (tables_b[table].get("fields") or [])}

        for name in sorted(set(fields_b) - set(fields_a)):
            findings.append(_finding("Fields Added", "Info", f"{table}::{name}",
                f"Field '{name}' added to table '{table}' in {label_b}.",
                "New field -- confirm it has the validation/type it's supposed to."))

        for name in sorted(set(fields_a) - set(fields_b)):
            findings.append(_finding("Fields Removed", "Warning", f"{table}::{name}",
                f"Field '{name}' removed from table '{table}' (present in {label_a}, gone in {label_b}).",
                "Confirm nothing (scripts, layouts, calculations) still expects this field to exist."))

        for name in sorted(set(fields_a) & set(fields_b)):
            fa, fb = fields_a[name], fields_b[name]
            if _field_signature(fa) != _field_signature(fb):
                changes = _describe_field_changes(fa, fb)
                findings.append(_finding("Fields Changed", "Warning", f"{table}::{name}",
                    f"Field '{name}' in table '{table}' changed between {label_a} and {label_b}: {changes}.",
                    "Review the change -- calculation/type/validation edits can affect existing data or scripts."))

    # ---------------- Scripts ----------------
    scripts_a = {s.get("name"): s for s in (data_a.get("scripts") or [])}
    scripts_b = {s.get("name"): s for s in (data_b.get("scripts") or [])}

    for name in sorted(set(scripts_b) - set(scripts_a)):
        findings.append(_finding("Scripts Added", "Info", name,
            f"Script '{name}' exists in {label_b} but not in {label_a}.",
            "New script -- confirm it's wired up wherever it's supposed to run."))

    for name in sorted(set(scripts_a) - set(scripts_b)):
        findings.append(_finding("Scripts Removed", "Warning", name,
            f"Script '{name}' existed in {label_a} but is missing from {label_b}.",
            "Confirm nothing (buttons, other scripts, Server schedules) still tries to call this script."))

    for name in sorted(set(scripts_a) & set(scripts_b)):
        sa, sb = scripts_a[name], scripts_b[name]
        if _script_signature(sa) != _script_signature(sb):
            steps_a, steps_b = len(sa.get("steps") or []), len(sb.get("steps") or [])
            findings.append(_finding("Scripts Changed", "Warning", name,
                f"Script '{name}' steps changed between {label_a} ({steps_a} steps) and {label_b} ({steps_b} steps).",
                "Review the script's logic -- step changes can alter behaviour in ways that aren't visible from outside."))

    # ---------------- Relationships ----------------
    rels_a = {_relationship_key(r): r for r in (data_a.get("relationships") or [])}
    rels_b = {_relationship_key(r): r for r in (data_b.get("relationships") or [])}

    for key in sorted(set(rels_b) - set(rels_a)):
        r = rels_b[key]
        loc = f"{r.get('left_table')} <-> {r.get('right_table')}"
        findings.append(_finding("Relationships Added", "Info", loc,
            f"Relationship between '{r.get('left_table')}' and '{r.get('right_table')}' added in {label_b}.",
            "Confirm the join predicate is what's intended."))

    for key in sorted(set(rels_a) - set(rels_b)):
        r = rels_a[key]
        loc = f"{r.get('left_table')} <-> {r.get('right_table')}"
        findings.append(_finding("Relationships Removed", "Warning", loc,
            f"Relationship between '{r.get('left_table')}' and '{r.get('right_table')}' existed in {label_a} but is gone in {label_b}.",
            "Confirm nothing (portals, related-field calcs, Go to Related Record) still depends on this relationship."))

    # ---------------- Layouts ----------------
    layouts_a = {l.get("name"): l for l in (data_a.get("layouts") or [])}
    layouts_b = {l.get("name"): l for l in (data_b.get("layouts") or [])}

    for name in sorted(set(layouts_b) - set(layouts_a)):
        findings.append(_finding("Layouts Added", "Info", name,
            f"Layout '{name}' exists in {label_b} but not in {label_a}.",
            "New layout -- confirm access privileges are set for the roles that need it."))

    for name in sorted(set(layouts_a) - set(layouts_b)):
        findings.append(_finding("Layouts Removed", "Warning", name,
            f"Layout '{name}' existed in {label_a} but is missing from {label_b}.",
            "Confirm nothing (scripts with 'Go to Layout', custom menus) still targets this layout."))

    for name in sorted(set(layouts_a) & set(layouts_b)):
        la, lb = layouts_a[name], layouts_b[name]
        if la.get("object_count") != lb.get("object_count"):
            findings.append(_finding("Layouts Changed", "Warning", name,
                f"Layout '{name}' object count changed from {la.get('object_count')} ({label_a}) to {lb.get('object_count')} ({label_b}).",
                "Objects were added or removed from this layout -- worth a visual check."))

    return findings


def _describe_field_changes(fa: dict, fb: dict) -> str:
    parts = []
    if fa.get("data_type") != fb.get("data_type"):
        parts.append(f"type {fa.get('data_type')} -> {fb.get('data_type')}")
    if bool(fa.get("is_calculation")) != bool(fb.get("is_calculation")):
        parts.append(f"calculation flag {fa.get('is_calculation')} -> {fb.get('is_calculation')}")
    if fa.get("calculation_text") != fb.get("calculation_text"):
        parts.append("calculation text changed")
    if bool(fa.get("has_validation")) != bool(fb.get("has_validation")):
        parts.append(f"validation {fa.get('has_validation')} -> {fb.get('has_validation')}")
    if (fa.get("validation_flags") or {}) != (fb.get("validation_flags") or {}):
        parts.append("validation rules changed")
    if fa.get("storage_index") != fb.get("storage_index"):
        parts.append(f"storage {fa.get('storage_index')} -> {fb.get('storage_index')}")
    return "; ".join(parts) if parts else "attributes changed"


def diff_summary(findings: list[dict]) -> dict:
    """Rolls up compare_snapshots() findings into the 4 badge counts shown
    on the Compare / Timeline screens (breaking / removed / modified / added),
    matching the reference tool's colored badge row.

    Heuristic (documented here since it's a judgment call, not a fact):
      added    = every "* Added" category
      removed  = structural removals that are usually safe to notice but
                 rarely break something on their own (Tables/Relationships/
                 Layouts Removed)
      breaking = removals of things other parts of the solution actively
                 call by name -- Fields Removed and Scripts Removed --
                 since a missing field/script is the classic "deploy and
                 something turns red" case
      modified = every "* Changed" category
    """
    counts = {"breaking": 0, "removed": 0, "modified": 0, "added": 0}
    breaking_categories = {"Fields Removed", "Scripts Removed"}
    removed_categories = {"Tables Removed", "Relationships Removed", "Layouts Removed"}
    for f in findings:
        cat = f.get("category", "")
        if cat in breaking_categories:
            counts["breaking"] += 1
        elif cat in removed_categories:
            counts["removed"] += 1
        elif cat.endswith("Changed"):
            counts["modified"] += 1
        elif cat.endswith("Added"):
            counts["added"] += 1
    return counts


def _finding(category: str, severity: str, location: str, description: str, suggestion: str) -> dict:
    return {
        "module": "compare",
        "category": category,
        "severity": severity,
        "location": location,
        "description": description,
        "suggestion": suggestion,
    }
