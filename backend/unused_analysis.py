"""
unused_analysis.py

GROUP A FEATURE: Unused Fields / Unused Scripts
-------------------------------------------------
Inspired by the "Unused Fields" / "Unused Scripts" counters seen on the
FM Changelog reference tool's Explore tab. Takes the same parsed DDR
dict that detection_rules.py already works with (from ddr_parser.py's
parse_ddr()) and flags fields/scripts that are never referenced
anywhere else visible in the DDR export.

Output uses the exact same finding shape as detection_rules.py, so
these slot straight into the same findings list / same UI table --
no frontend rewrite needed for the table itself, only two new category
labels ("Unused Fields", "Unused Scripts") for the DDR results to
group under:
    {
      "module": "ddr",
      "category": "Unused Fields" | "Unused Scripts",
      "severity": "Info",
      "location": "Table::Field" | "ScriptName",
      "description": "...",
      "suggestion": "...",
    }

IMPORTANT LIMITATION (worth being upfront about, same as FM Changelog
itself prints on its own Deep Audit screen): this is STATIC analysis
of one DDR export. A field/script can look "unused" here and still be
in active use through something the DDR doesn't show us:
  - fields read/written by an external system (API client, webhook,
    data export, ODBC/JDBC, a script running on FileMaker Server)
  - scripts triggered by a button, a custom menu, a script trigger
    (OnLayoutLoad, OnRecordCommit, etc.), or a Server schedule --
    ddr_parser.py only captures script-calls-script via "Perform
    Script" steps, not any of those
  - fields/scripts referenced only inside ExecuteSQL text (a raw SQL
    string, not a structured field/script reference)
So: treat these as CANDIDATES to double-check by hand, never as an
auto-delete list. That caveat is baked into every finding's own
"suggestion" text below, not just this docstring.
"""

import re

# ---------------------------------------------------------------------------
# Field usage scan
# ---------------------------------------------------------------------------

# Matches "TableName::FieldName" wherever it shows up in free text (calc
# formulas, StepText). FileMaker table/field names can contain spaces,
# letters, digits, underscores -- this pattern is deliberately loose.
_QUALIFIED_FIELD_RE = re.compile(r"([A-Za-z0-9_ ]+)::([A-Za-z0-9_ ]+)")


def _all_known_fields(data):
    """Returns {(table_name, field_name): field_dict} for every field
    defined anywhere in the DDR."""
    known = {}
    for table_name, table in data["tables"].items():
        for f in table["fields"]:
            known[(table_name, f["name"])] = f
    return known


def _collect_field_references(data):
    """
    Walks every place a field COULD be referenced and returns a set of
    (table_name, field_name) tuples that were actually seen.
    Sources checked:
      1. Every field's own calculation_text (a calc can reference other
         fields, including fields on other tables via TableName::Field)
      2. Every script step's structured "field" ref (Set Field, etc.)
      3. Every script step's free-text "text" (StepText) -- catches
         Table::Field mentions inside calc dialogs pasted into steps
      4. Relationship predicates (left_field / right_field)
      5. Layout field objects (Table::Field placed on a layout)
    """
    referenced = set()

    # 1. calc formulas on fields themselves
    for table_name, table in data["tables"].items():
        for f in table["fields"]:
            calc = f.get("calculation_text")
            if calc:
                for tbl, fld in _QUALIFIED_FIELD_RE.findall(calc):
                    referenced.add((tbl.strip(), fld.strip()))

    # 2 & 3. script steps
    for script in data["scripts"]:
        for step in script["steps"]:
            field_ref = step.get("field")
            if field_ref and field_ref.get("table") and field_ref.get("name"):
                referenced.add((field_ref["table"], field_ref["name"]))
            text = step.get("text")
            if text:
                for tbl, fld in _QUALIFIED_FIELD_RE.findall(text):
                    referenced.add((tbl.strip(), fld.strip()))

    # 4. relationships
    for rel in data["relationships"]:
        for pred in rel["predicates"]:
            for side in ("left_field", "right_field"):
                ref = pred.get(side)
                if ref and ref.get("table") and ref.get("name"):
                    referenced.add((ref["table"], ref["name"]))

    # 5. layouts
    for layout in data["layouts"]:
        for fo in layout["field_objects"]:
            if fo.get("table") and fo.get("field"):
                referenced.add((fo["table"], fo["field"]))

    return referenced


def find_unused_fields(data):
    """A field is flagged if its (table, name) never shows up in
    _collect_field_references()."""
    findings = []
    known = _all_known_fields(data)
    referenced = _collect_field_references(data)

    for (table_name, field_name), _f in known.items():
        if (table_name, field_name) in referenced:
            continue
        findings.append({
            "module": "ddr",
            "category": "Unused Fields",
            "severity": "Info",
            "location": f"{table_name}::{field_name}",
            "description": (
                "No reference to this field was found in any calculation, "
                "script step, relationship, or layout in this DDR export."
            ),
            "suggestion": (
                "Likely unused, but static analysis can't see external "
                "consumers (APIs, ODBC, exports, ExecuteSQL text, Server "
                "schedules). Confirm with the client/team before removing."
            ),
        })
    return findings


# ---------------------------------------------------------------------------
# Script usage scan
# ---------------------------------------------------------------------------

def _collect_called_script_names(data):
    """Every script name that appears as the target of a 'Perform Script'
    step anywhere in the file."""
    called = set()
    for script in data["scripts"]:
        for step in script["steps"]:
            target = step.get("target_script")
            if target:
                called.add(target)
    return called


def find_unused_scripts(data):
    """A script is flagged if no OTHER script's 'Perform Script' step
    ever names it. This only sees script-calls-script -- it cannot see
    button triggers, custom menu items, layout script triggers, or
    Server schedules, since ddr_parser.py doesn't capture those."""
    findings = []
    called = _collect_called_script_names(data)

    for script in data["scripts"]:
        name = script["name"]
        if name in called:
            continue
        findings.append({
            "module": "ddr",
            "category": "Unused Scripts",
            "severity": "Info",
            "location": name,
            "description": (
                "No other script in this DDR export calls this script via "
                "Perform Script."
            ),
            "suggestion": (
                "May still be wired to a button, custom menu, layout "
                "trigger, or Server schedule -- none of which show up in "
                "this scan. Confirm before removing."
            ),
        })
    return findings


def run_unused_rules(data):
    """Convenience wrapper -- same call shape as detection_rules.run_all_rules,
    so main.py can chain the two lists together."""
    return find_unused_fields(data) + find_unused_scripts(data)
