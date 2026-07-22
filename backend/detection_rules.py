"""
detection_rules.py

DAY 2 DELIVERABLE: Detection Rules (DDR)
-----------------------------------------
Goal: take the clean dict/list structure produced by `parse_ddr()`
(ddr_parser.py, Day 1) and run a set of independent Python functions
-- one per detection rule -- that each look for ONE specific problem
and return a list of "finding" dicts.

Every finding follows the exact schema from the brief, plus one extra
"category" field (Fields / Scripts / Relationships / Layouts) so the
Day 4 web UI can show DDR results as four separate sections instead of
one long mixed table:
    {
      "module": "ddr",
      "category": "Fields" | "Scripts" | "Relationships" | "Layouts",
      "severity": "Critical" | "Warning" | "Info",
      "location": "Table::Field" | "ScriptName > Step 12" | "TableA <-> TableB",
      "description": "what the problem is",
      "suggestion": "how to fix it",
    }

Severity was assigned using the brief's own definitions:
    Critical -> data loss / corruption / severe performance hit
    Warning  -> slowness or unpredictable behaviour under load
    Info     -> best-practice violation, low immediate impact

No AI calls here -- Day 2 is pure Python logic. Module 2 (Script
Reviewer) and Module 3 (SQL Reviewer) are the ones that call Claude,
and those are Day 3.

HOW EACH RULE WORKS (short version -- the long version is in each
function's own docstring):

  FIELDS
    1. always_evaluate_calc       -> AutoEnter@alwaysEvaluate == True
    2. unstored_calc_high_records -> calc field, Storage@index == "None",
                                      on a table with many records
    3. relationship_field_no_index-> a field used in a relationship join
                                      whose Storage@index == "None"
    4. key_field_no_validation    -> field name looks like a key/ID but
                                      has no NotEmpty/Unique/etc. set

  SCRIPTS
    5. long_script_no_comments    -> >100 steps, zero "# (comment)" steps
    6. loop_without_exit          -> Loop...End Loop with no Exit Loop If
                                      in between
    7. missing_error_capture      -> ODBC/import/web-request step present,
                                      but no Set Error Capture / LastError
                                      check anywhere in the script
    8. replace_container_field    -> Replace Field Contents targeting a
                                      Container field
    9. recursive_no_guard         -> script calls itself (Perform Script)
                                      with no counter/depth variable
   10. gtrr_no_layout             -> Go to Related Record with no
                                      "using layout" clause in its text

  RELATIONSHIPS
   11. cartesian_join             -> JoinPredicate type == "CartesianProduct"
                                      (no real match field defined)
   12. too_many_relationships     -> a table appears in >15 relationships
   13. relationship_unstored_calc -> a join field is an unstored calculation
   14. circular_relationships     -> a cycle in the table relationship graph

  LAYOUTS
   15. layout_too_many_objects    -> >200 objects on one layout
   16. portal_no_row_limit        -> <PortalObj> with no numOfRows set
   17. unstored_calc_merge_field  -> a layout field object points at an
                                      unstored calculation
   18. conditional_format_stack   -> >5 stacked <Condition> rules on one
                                      field's conditional formatting

That is 18 rules across all 4 categories -- comfortably above the
brief's "at least 6" success criterion.

IMPORTANT LIMITATION (being upfront about it, the way I'd flag it to
Sohaib in standup): a few checks rely on the free-text <StepText> or on
threshold numbers (100 steps, 15 relationships, 200 objects, 5 stacked
conditions) that are industry rules of thumb from the brief, not values
read from the DDR itself -- they are configurable via function
arguments so Sohaib can tune them per client database.
"""

import re
from collections import defaultdict

# ---------------------------------------------------------------------------
# Severity ordering, used to sort the final combined findings list
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"Critical": 0, "Warning": 1, "Info": 2}

# Step names that can fail silently if the script doesn't check for it
RISKY_STEPS = {
    "Insert from URL", "Perform Script on Server", "Import Records",
    "Execute SQL", "Open ODBC Connection", "Export Records",
}

KEY_NAME_PATTERN = re.compile(r"(key|id)$", re.IGNORECASE)


def _finding(category, severity, location, description, suggestion):
    return {
        "module": "ddr",
        "category": category,
        "severity": severity,
        "location": location,
        "description": description,
        "suggestion": suggestion,
    }


# ---------------------------------------------------------------------------
# Small helper indexes built once and reused by several rules
# ---------------------------------------------------------------------------

def _build_field_lookup(data):
    """
    (table_name, field_id) -> field dict, and (table_name, field_name) -> field dict.
    Relationships reference fields by id; layouts reference them by name
    (via the "Table::Field" text on the layout object) -- so we need both.
    """
    by_id, by_name = {}, {}
    for table_name, table in data["tables"].items():
        for f in table["fields"]:
            by_id[(table_name, f["id"])] = f
            by_name[(table_name, f["name"])] = f
    return by_id, by_name


# ---------------------------------------------------------------------------
# FIELD RULES
# ---------------------------------------------------------------------------

def rule_always_evaluate_calc(data):
    """
    AutoEnter@alwaysEvaluate == True means FileMaker recalculates the
    formula on EVERY access to the record, even when nothing that feeds
    the formula has changed. On a busy table this is a constant, avoidable
    CPU cost -- classic "Warning" per the brief's severity table.
    """
    findings = []
    for table_name, table in data["tables"].items():
        for f in table["fields"]:
            if f["is_calculation"] and f["always_evaluate"]:
                findings.append(_finding(
                    "Fields",
                    "Warning",
                    f"{table_name}::{f['name']}",
                    "Calculation field is set to always-evaluate, so it "
                    "recalculates on every record access instead of only "
                    "when its dependencies change.",
                    "Uncheck 'Do not evaluate if all referenced fields are "
                    "empty' / always-evaluate in the calc field options "
                    "unless the formula genuinely needs to run every time "
                    "(e.g. it depends on Get(CurrentTime))."
                ))
    return findings


def rule_unstored_calc_high_records(data, record_threshold=1000):
    """
    An unstored calculation (Storage index == "None") cannot be indexed,
    so any Find or Sort on it forces FileMaker to evaluate the formula
    for every record in the table at query time. Harmless on a 6-record
    table, expensive on a 100,000-record one -- hence the record_threshold.
    """
    findings = []
    for table_name, table in data["tables"].items():
        if table["record_count"] < record_threshold:
            continue
        for f in table["fields"]:
            if f["is_calculation"] and f["storage_index"] == "None":
                findings.append(_finding(
                    "Fields",
                    "Warning",
                    f"{table_name}::{f['name']}",
                    f"Unstored calculation on a table with "
                    f"{table['record_count']} records -- cannot be indexed, "
                    "so finds/sorts on this field scan every record.",
                    "If the formula doesn't depend on Get() functions like "
                    "Get(CurrentTime), enable indexing/storage so it can be "
                    "indexed, or replace with an auto-enter calc that IS "
                    "stored."
                ))
    return findings


def rule_relationship_field_no_index(data):
    """
    A field used as one side of a relationship join should be indexed --
    otherwise every related-record lookup through that relationship does
    a full scan of the other table.
    """
    findings = []
    field_by_id, _ = _build_field_lookup(data)
    seen = set()
    for rel in data["relationships"]:
        for pred in rel["predicates"]:
            for side in ("left_field", "right_field"):
                ref = pred[side]
                if not ref or not ref.get("table") or not ref.get("id"):
                    continue
                field = field_by_id.get((ref["table"], ref["id"]))
                if field is None:
                    continue  # field lives in a table outside this file
                if field["storage_index"] == "None":
                    key = (ref["table"], ref["id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(_finding(
                        "Fields",
                        "Warning",
                        f"{ref['table']}::{field['name']}",
                        "Field is used in a relationship match but has no "
                        "index -- related-record lookups through this "
                        "relationship will scan the whole table.",
                        "Turn on indexing for this field (Field Options > "
                        "Storage), or, if it's a calculation, make it a "
                        "stored/indexable one."
                    ))
    return findings


def rule_key_field_no_validation(data):
    """
    Any field whose name looks like a primary or foreign key (ends in
    'Key' or 'ID') but has none of NotEmpty/Unique/Existing/Strict set is
    a soft integrity gap -- FileMaker will happily let a key field be
    blank or duplicated.
    """
    findings = []
    for table_name, table in data["tables"].items():
        for f in table["fields"]:
            if KEY_NAME_PATTERN.search(f["name"] or "") and not f["has_validation"]:
                findings.append(_finding(
                    "Fields",
                    "Info",
                    f"{table_name}::{f['name']}",
                    "Field name suggests it's a primary/foreign key, but it "
                    "has no validation (not required, not unique).",
                    "Add 'Not empty' (and 'Unique' for primary keys) "
                    "validation so bad data can't slip in through "
                    "scripts or imports."
                ))
    return findings


# ---------------------------------------------------------------------------
# SCRIPT RULES
# ---------------------------------------------------------------------------

def rule_long_script_no_comments(data, step_threshold=100):
    """
    A script over the threshold with not a single '# (comment)' step is a
    maintenance risk for whoever inherits it later -- low immediate
    impact, so this is "Info" rather than "Warning".
    """
    findings = []
    for script in data["scripts"]:
        n_steps = len(script["steps"])
        if n_steps <= step_threshold:
            continue
        has_comment = any(s["name"] == "# (comment)" for s in script["steps"])
        if not has_comment:
            findings.append(_finding(
                "Scripts",
                "Info",
                f"{script['name']}",
                f"Script has {n_steps} steps and not a single comment step "
                "explaining its sections.",
                "Break the script into labelled sections with '# (comment)' "
                "steps, or split it into smaller sub-scripts called via "
                "Perform Script."
            ))
    return findings


def rule_loop_without_exit(data):
    """
    A Loop with no Exit Loop If anywhere inside it can only end if every
    single path out of the loop body (e.g. 'Go to Record/Request/Page
    [Next; Exit after last]') happens to terminate it -- easy to get
    wrong, and the classic cause of a FileMaker file hanging. Tracked
    with a simple stack since Loop/End Loop can nest.
    """
    findings = []
    for script in data["scripts"]:
        stack = []  # each entry: {"start_id": .., "has_exit": False}
        for step in script["steps"]:
            name = step["name"]
            if name == "Loop":
                stack.append({"start_id": step["position"], "has_exit": False})
            elif name == "Exit Loop If" and stack:
                stack[-1]["has_exit"] = True
            elif (
                name == "Go to Record/Request/Page"
                and "exit after last" in (step.get("text") or "").lower()
                and stack
            ):
                # This is FileMaker's standard record-walking loop exit.
                stack[-1]["has_exit"] = True
            elif name == "End Loop" and stack:
                frame = stack.pop()
                if not frame["has_exit"]:
                    findings.append(_finding(
                        "Scripts",
                        "Warning",
                        f"{script['name']} > Step {frame['start_id']} (Loop)",
                        "Loop has no visible 'Exit Loop If' or 'Go to "
                        "Record [Next; Exit after last]' step -- risk of "
                        "an infinite loop if no other guaranteed exit is "
                        "present.",
                        "Add an explicit 'Exit Loop If' or use 'Go to "
                        "Record [Next; Exit after last]' inside the loop."
                    ))
    return findings


def rule_missing_error_capture(data):
    """
    Steps like Insert from URL, Perform Script on Server, Import Records
    etc. can fail (network error, permission error, bad file) without
    stopping the script. If the script never sets error capture on and
    never checks Get(LastError), a failure here passes silently.
    """
    findings = []
    for script in data["scripts"]:
        risky_present = [s for s in script["steps"] if s["name"] in RISKY_STEPS]
        if not risky_present:
            continue
        # BUGFIX: this used to just check whether a "Set Error Capture"
        # step existed at all, regardless of whether it was actually
        # [On] or [Off]. "Set Error Capture [ Off ]" was being counted
        # as error handling, which is backwards -- it explicitly turns
        # error capture OFF. Now we only count it if the step text does
        # NOT say "Off".
        has_error_capture = any(
            s["name"] == "Set Error Capture" and "off" not in (s["text"] or "").lower()
            for s in script["steps"]
        )
        checks_last_error = any(
            "lasterror" in (s["text"] or "").lower() for s in script["steps"]
        )
        if not has_error_capture and not checks_last_error:
            names = ", ".join(sorted({s["name"] for s in risky_present}))
            findings.append(_finding(
                "Scripts",
                "Warning",
                f"{script['name']}",
                f"Script uses step(s) that can fail silently ({names}) but "
                "never sets error capture on or checks Get(LastError).",
                "Add 'Set Error Capture [On]' before the risky step and an "
                "'If [Get(LastError) ≠ 0]' check right after it to handle "
                "failures explicitly."
            ))
    return findings


def rule_replace_container_field(data):
    """
    'Replace Field Contents' overwrites every record in the found set
    with a single value/calc result -- if the target is a Container
    field, this silently destroys every stored file/image in that
    found set. Data-loss risk -> Critical.
    """
    findings = []
    field_by_id, _ = _build_field_lookup(data)
    for script in data["scripts"]:
        for step in script["steps"]:
            if step["name"] != "Replace Field Contents" or not step["field"]:
                continue
            ref = step["field"]
            field = field_by_id.get((ref["table"], ref["id"]))
            data_type = field["data_type"] if field else None
            if data_type == "Container":
                findings.append(_finding(
                    "Scripts",
                    "Critical",
                    f"{script['name']} > Step {step['position']}",
                    f"'Replace Field Contents' targets {ref['table']}::"
                    f"{ref['name']}, a Container field -- this will "
                    "overwrite/delete every container value in the found "
                    "set with no undo.",
                    "Remove this step or restrict it to a very specific "
                    "found set with an explicit confirmation dialog before "
                    "it runs; container data cannot be recovered afterwards."
                ))
    return findings


def rule_recursive_no_guard(data):
    """
    A script that calls itself (Perform Script targeting its own name)
    needs an explicit counter/depth variable to guarantee it terminates.
    Detected by scanning for a Set Variable step whose $variable name or
    text hints at a counter/depth/iteration guard anywhere in the script.
    """
    findings = []
    guard_pattern = re.compile(r"\$\$?\w*(count|depth|iteration|recursion)\w*",
                                re.IGNORECASE)
    for script in data["scripts"]:
        self_calls = [s for s in script["steps"]
                      if s["name"] == "Perform Script"
                      and s.get("target_script") == script["name"]]
        if not self_calls:
            continue
        has_guard = any(
            guard_pattern.search(s["text"] or "") for s in script["steps"]
        )
        if not has_guard:
            findings.append(_finding(
                "Scripts",
                "Warning",
                f"{script['name']} > Step {self_calls[0]['position']}",
                "Script calls itself (Perform Script) with no counter or "
                "depth variable visible anywhere in the script.",
                "Pass a recursion-depth parameter and check/increment it, "
                "exiting once it passes a safe maximum, to guarantee the "
                "recursion can't run away."
            ))
    return findings


def rule_gtrr_no_layout(data):
    """
    'Go to Related Record' without an explicit target layout leaves
    FileMaker to pick a layout on its own -- behaviour that can change
    if layouts are added/renamed later.
    """
    findings = []
    for script in data["scripts"]:
        for step in script["steps"]:
            if step["name"] != "Go to Related Record":
                continue
            text = (step["text"] or "")
            if "using layout" not in text.lower():
                findings.append(_finding(
                    "Scripts",
                    "Warning",
                    f"{script['name']} > Step {step['position']}",
                    "'Go to Related Record' has no explicit target layout "
                    "specified.",
                    "Specify an explicit 'using layout' target so the "
                    "destination is predictable regardless of the current "
                    "layout or future layout changes."
                ))
    return findings


# ---------------------------------------------------------------------------
# RELATIONSHIP RULES
# ---------------------------------------------------------------------------

def rule_cartesian_join(data):
    """
    A JoinPredicate of type "CartesianProduct" means the relationship has
    no real match field -- every row on one side relates to every row on
    the other. On any non-trivial table this returns a runaway related
    set and is usually a mistake, not a design choice -> Critical.
    """
    findings = []
    for rel in data["relationships"]:
        for pred in rel["predicates"]:
            if pred["type"] == "CartesianProduct":
                findings.append(_finding(
                    "Relationships",
                    "Critical",
                    f"{rel['left_table']} <-> {rel['right_table']}",
                    "Relationship has a Cartesian-product join (no real "
                    "match field defined) -- every record on one side "
                    "relates to every record on the other.",
                    "Define an explicit match field pair for this "
                    "relationship, or remove it if it was created by "
                    "accident (dragging table occurrences without a key)."
                ))
    return findings


def rule_too_many_relationships(data, threshold=15):
    """Tables with a very large number of relationships are a complexity/
    maintainability warning: the relationship graph gets hard to reason
    about and every extra relationship is another calc-dependency and
    another index to keep in sync."""
    findings = []
    counts = defaultdict(int)
    for rel in data["relationships"]:
        if rel["left_table"]:
            counts[rel["left_table"]] += 1
        if rel["right_table"]:
            counts[rel["right_table"]] += 1
    for table_name, count in counts.items():
        if count > threshold:
            findings.append(_finding(
                "Relationships",
                "Warning",
                table_name,
                f"Table participates in {count} relationships, above the "
                f"{threshold}-relationship complexity threshold.",
                "Review whether all these relationships are still needed; "
                "consider consolidating lookups behind fewer, well-named "
                "table occurrences."
            ))
    return findings


def rule_relationship_unstored_calc(data):
    """A join field that is itself an unstored calculation can't be
    indexed, so FileMaker can't use an index to resolve the relationship
    -- every related-record access re-evaluates the calc for the whole
    table."""
    findings = []
    field_by_id, _ = _build_field_lookup(data)
    seen = set()
    for rel in data["relationships"]:
        for pred in rel["predicates"]:
            for side in ("left_field", "right_field"):
                ref = pred[side]
                if not ref or not ref.get("table") or not ref.get("id"):
                    continue
                field = field_by_id.get((ref["table"], ref["id"]))
                if field and field["is_calculation"] and field["storage_index"] == "None":
                    key = (ref["table"], ref["id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(_finding(
                        "Relationships",
                        "Warning",
                        f"{ref['table']}::{field['name']}",
                        "Relationship is built on an unstored calculation "
                        "field -- this join cannot use an index.",
                        "Replace the calculation with a stored/indexable "
                        "field (e.g. an auto-enter calc that IS stored) if "
                        "the formula allows it."
                    ))
    return findings


def rule_circular_relationships(data):
    """
    Detects a cycle in the (undirected) table-relationship graph using a
    simple DFS. A cycle means TableA relates to TableB relates to ...
    back to TableA -- a valid FileMaker pattern sometimes, but worth
    flagging since it's a common source of "which occurrence of this
    table am I actually looking at" confusion.
    """
    graph = defaultdict(set)
    for rel in data["relationships"]:
        if rel["left_table"] and rel["right_table"]:
            graph[rel["left_table"]].add(rel["right_table"])
            graph[rel["right_table"]].add(rel["left_table"])

    visited = set()
    findings = []
    reported_cycles = set()

    def dfs(node, parent, path):
        visited.add(node)
        path.append(node)
        for neighbor in graph[node]:
            if neighbor == parent:
                continue
            if neighbor in path:
                cycle = path[path.index(neighbor):] + [neighbor]
                key = frozenset(cycle)
                if key not in reported_cycles:
                    reported_cycles.add(key)
                    findings.append(_finding(
                        "Relationships",
                        "Warning",
                        " -> ".join(cycle),
                        "Circular relationship path detected between these "
                        "tables.",
                        "Confirm this loop is intentional (e.g. a "
                        "self-join via a different table occurrence); "
                        "otherwise it usually means an extra table "
                        "occurrence was added by mistake."
                    ))
            elif neighbor not in visited:
                dfs(neighbor, node, path)
        path.pop()

    for table_name in graph:
        if table_name not in visited:
            dfs(table_name, None, [])

    return findings


# ---------------------------------------------------------------------------
# LAYOUT RULES
# ---------------------------------------------------------------------------

def rule_layout_too_many_objects(data, threshold=200):
    """A layout with an extreme object count is slow to open in Layout
    mode and slow to render -- a maintainability/performance smell, but
    low immediate impact -> Info."""
    findings = []
    for layout in data["layouts"]:
        if layout["object_count"] > threshold:
            findings.append(_finding(
                "Layouts",
                "Info",
                layout["name"],
                f"Layout has {layout['object_count']} objects, above the "
                f"{threshold}-object threshold.",
                "Split the layout into multiple tabs/panels or separate "
                "layouts, and remove any objects left over from earlier "
                "design iterations."
            ))
    return findings


def rule_portal_no_row_limit(data):
    """
    A portal with no explicit row count set (numOfRows missing from the
    DDR) will render every related record it can -- fine for a handful
    of rows, a real problem for a one-to-many relationship with
    thousands of children.

    ASSUMPTION: the DDR only reports a numOfRows value when the
    developer has explicitly set one; a missing value is treated here
    as "no limit configured". Worth spot-checking a known layout in
    FileMaker to confirm this holds for your file's FileMaker version.
    """
    findings = []
    for layout in data["layouts"]:
        for i, portal in enumerate(layout["portal_objects"]):
            if portal["num_rows"] is None:
                findings.append(_finding(
                    "Layouts",
                    "Warning",
                    f"{layout['name']} > Portal {i + 1}",
                    "Portal has no explicit row limit set in the DDR.",
                    "Set an explicit 'Show' row count on the portal so it "
                    "can't try to render an unbounded number of related "
                    "records."
                ))
    return findings


def rule_unstored_calc_merge_field(data):
    """A layout field object bound to an unstored calculation re-runs
    that calculation every time the layout renders that record --
    including in list/table view, once per visible row."""
    findings = []
    _, field_by_name = _build_field_lookup(data)
    seen = set()
    for layout in data["layouts"]:
        for fo in layout["field_objects"]:
            field = field_by_name.get((fo["table"], fo["field"]))
            if field and field["is_calculation"] and field["storage_index"] == "None":
                key = (layout["name"], fo["table"], fo["field"])
                if key in seen:
                    continue
                seen.add(key)
                findings.append(_finding(
                    "Layouts",
                    "Warning",
                    f"{layout['name']} > {fo['table']}::{fo['field']}",
                    "Layout displays an unstored calculation field -- it "
                    "re-evaluates on every render, including once per row "
                    "in list/table view.",
                    "If the field is shown in a list/table layout, "
                    "consider making the calculation stored, or caching "
                    "its result in a stored field updated by script."
                ))
    return findings


def rule_conditional_format_stack(data, depth_threshold=5):
    """More than a handful of stacked conditional-formatting rules on a
    single field object are slow to evaluate on every render and hard
    for the next developer to reason about -- Info-level smell."""
    findings = []
    for layout in data["layouts"]:
        if layout["max_conditional_format_depth"] > depth_threshold:
            findings.append(_finding(
                "Layouts",
                "Info",
                layout["name"],
                f"Layout has a field with {layout['max_conditional_format_depth']} "
                f"stacked conditional formatting rules, above the "
                f"{depth_threshold}-rule threshold.",
                "Consolidate the conditions into fewer, combined boolean "
                "expressions where possible."
            ))
    return findings


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_RULES = [
    rule_always_evaluate_calc,
    rule_unstored_calc_high_records,
    rule_relationship_field_no_index,
    rule_key_field_no_validation,
    rule_long_script_no_comments,
    rule_loop_without_exit,
    rule_missing_error_capture,
    rule_replace_container_field,
    rule_recursive_no_guard,
    rule_gtrr_no_layout,
    rule_cartesian_join,
    rule_too_many_relationships,
    rule_relationship_unstored_calc,
    rule_circular_relationships,
    rule_layout_too_many_objects,
    rule_portal_no_row_limit,
    rule_unstored_calc_merge_field,
    rule_conditional_format_stack,
]


def run_all_rules(data):
    """Run every rule function against the parsed DDR data, collect all
    findings into one flat list, and sort by severity (Critical first)."""
    findings = []
    for rule_fn in ALL_RULES:
        findings.extend(rule_fn(data))
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 99))
    return findings


def summarize_findings(findings):
    counts = {"Critical": 0, "Warning": 0, "Info": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


if __name__ == "__main__":
    import sys
    import json
    from ddr_parser import parse_ddr

    file_path = sys.argv[1] if len(sys.argv) > 1 else "sample_ddr.xml"
    data = parse_ddr(file_path)
    findings = run_all_rules(data)
    counts = summarize_findings(findings)

    print(f"Findings: {len(findings)}  "
          f"(Critical={counts['Critical']}, Warning={counts['Warning']}, Info={counts['Info']})\n")
    for f in findings:
        print(f"[{f['severity']:8s}] {f['location']}")
        print(f"           {f['description']}")
        print(f"           -> {f['suggestion']}\n")

    with open("ddr_findings.json", "w", encoding="utf-8") as out:
        json.dump({"findings": findings, "summary": counts}, out, indent=2)
    print("Saved: ddr_findings.json")
