"""
ddr_parser.py

DAY 1 DELIVERABLE: DDR Parser
------------------------------
Goal: turn a FileMaker DDR XML export into clean, plain Python data
structures (dicts/lists) -- NO detection rules here, NO AI calls.
That is Day 2's job (detection_rules.py). Today we ONLY parse.

REVISION NOTE (important, read before touching Day 2):
The first draft of this file was written from the brief's hints alone,
before I had a real DDR to look at. Once Sohaib's Practice_fmp12.xml
came through, I ran explore_ddr_structure.py against it and several of
my original guesses turned out wrong:

  - BaseTable's record-count attribute is `records`, not `recordCount`.
  - `alwaysEvaluate` lives on <AutoEnter>, not on <Calculation>.
    <Calculation> only carries the calc's `table` attribute and the
    formula text (often inside CDATA).
  - Storage's index attribute is `index` (values "None" / "Minimal" /
    "All"), not `indexing`.
  - Validation is NOT a single flag -- <Validation> has an attribute
    `type` and four boolean child tags (<NotEmpty value="..."/>,
    <Unique>, <Existing>, <StrictValidation>). "Has validation" only
    means something once you check whether any of those are "True".
  - Relationships are NOT <Relationship><TableReference/><FieldReference/>
    -- the real shape is:
      <Relationship id="..">
        <LeftTable name=".."/> <RightTable name=".."/>
        <JoinPredicateList>
          <JoinPredicate type="Equal|CartesianProduct|...">
            <LeftField><Field table=".." id=".." name=".."/></LeftField>
            <RightField><Field table=".." id=".." name=".."/></RightField>
  - Scripts live under <ScriptCatalog><Script><StepList><Step>. Step
    itself only has id/enable/name -- ALL of the useful detail (target
    field, calculation text, layout name, etc.) is in <StepText>
    (a full human-readable rendering of the step) and, for some step
    types, a structured <Field table=".." id=".." name=".."/> child.
  - There is no indentation/depth attribute on <Step> -- If/Loop
    nesting has to be inferred from the sequence of step names
    (Loop ... Exit Loop If ... End Loop, If ... Else If ... Else ...
    End If). Day 2 does that bookkeeping, not this parser.
  - Layout field objects are <Object type="Field"><FieldObj><Name>
    Table::Field</Name>...<DDRInfo><Field table=".." id=".."/>.
    Portals are <Object type="Portal"><PortalObj numOfRows=".."/>.

This file reflects what the real file actually looks like. Keep
explore_ddr_structure.py around -- if a future DDR export (different
FileMaker version) uses different tag names, re-run it before assuming
this parser still applies.

Why iterparse instead of ET.parse()?
  ET.parse() loads the ENTIRE XML tree into memory at once. A production
  DDR file can be 50MB+. iterparse() streams the file element by element
  and lets us discard ("clear") elements we're done with, so memory stays
  flat no matter how big the file is.
"""

import os
import xml.etree.ElementTree as ET


def strip_ns(tag: str) -> str:
    """Remove XML namespace prefix like {http://...}Tag -> Tag"""
    return tag.split("}")[-1] if "}" in tag else tag


def _bool(val, default=False):
    if val is None:
        return default
    return str(val).strip().lower() == "true"


# ---------------------------------------------------------------------------
# Core parse function
# ---------------------------------------------------------------------------

def parse_ddr(file_path: str) -> dict:
    """
    Parse a FileMaker DDR XML file into a structured dict.
    Uses iterparse so it stays memory-safe on large (50MB+) files.

    Output shape:
    {
      "tables": {
          "Practice": {
              "id": "129",
              "record_count": 6,
              "fields": [
                  {
                    "name": "PrimaryKey", "id": "1", "data_type": "Text",
                    "field_type": "Normal",
                    "is_calculation": True, "always_evaluate": False,
                    "calculation_text": "Get( UUID )",
                    "is_global": False, "storage_index": "Minimal",
                    "has_validation": True,
                    "validation_flags": {"not_empty": True, "unique": True,
                                          "existing": False, "strict": True},
                  }, ...
              ]
          }, ...
      },
      "relationships": [
          {
            "id": "6",
            "left_table": "Practice", "right_table": "Showroom Data",
            "predicates": [
                {"type": "CartesianProduct",
                 "left_field": {"table": "Practice", "id": "1", "name": "PrimaryKey"},
                 "right_field": {"table": "Showroom Data", "id": "1072", "name": ""}},
            ],
          }, ...
      ],
      "layouts": [
          {
            "name": "Practice", "id": "1", "object_count": 12,
            "field_objects": [{"table": "Main", "field": "gUser"}, ...],
            "portal_objects": [{"num_rows": 14}, ...],
            "max_conditional_format_depth": 0,
          }, ...
      ],
      "scripts": [
          {
            "name": "Set Date [Calendar]", "id": "32",
            "steps": [
                {"id": "86", "name": "Set Error Capture", "enabled": True,
                 "text": "Set Error Capture [ On ]",
                 "field": None, "target_script": None},
                {"id": "76", "name": "Set Field", "enabled": True,
                 "text": "Set Field [ Practice::date; $date ]",
                 "field": {"table": "Practice", "id": "11", "name": "date"},
                 "target_script": None},
                ...
            ],
          }, ...
      ],
    }
    """
    result = {
        "tables": {},
        "relationships": [],
        "layouts": [],
        "scripts": [],
    }

    # --- context state while streaming ---
    current_table = None
    current_field = None
    current_validation = None

    current_relationship = None
    current_predicate = None
    in_left_field = False
    in_right_field = False

    current_layout = None
    current_object_type = None   # "Field" / "Portal" / etc, for the Object we're inside
    current_conditions_depth = 0

    current_script = None
    current_step = None
    in_field_catalog = False     # guards against Field tags that appear elsewhere (layouts, steps)
    field_depth = 0               # tracks Field nesting -- a <Field> can appear nested
                                   # inside another field's own <Lookup> (master-field ref);
                                   # only depth==1 is a real field DEFINITION
    in_script_catalog = False    # guards against bare <Script id=".." name=".."/> refs (e.g. button triggers)
    in_layout_catalog = False    # guards against bare <Layout/> refs (e.g. "Go to Layout" step targets)

    context = ET.iterparse(file_path, events=("start", "end"))

    for event, elem in context:
        tag = strip_ns(elem.tag)

        # ================= TABLES / FIELDS =================
        if event == "start" and tag == "BaseTable":
            current_table = {
                "id": elem.attrib.get("id"),
                "record_count": int(elem.attrib.get("records", 0) or 0),
                "fields": [],
            }
            result["tables"][elem.attrib.get("name", "UNKNOWN_TABLE")] = current_table

        elif event == "start" and tag == "FieldCatalog":
            in_field_catalog = True

        elif event == "end" and tag == "FieldCatalog":
            in_field_catalog = False
            field_depth = 0

        elif event == "start" and tag == "Field" and in_field_catalog and current_table is not None:
            field_depth += 1
            if field_depth == 1:
                current_field = {
                    "name": elem.attrib.get("name"),
                    "id": elem.attrib.get("id"),
                    "data_type": elem.attrib.get("dataType"),
                    "field_type": elem.attrib.get("fieldType"),
                    "is_calculation": False,
                    "always_evaluate": False,
                    "calculation_text": None,
                    "is_global": False,
                    "storage_index": None,     # "None" | "Minimal" | "All" | None-not-seen
                    "has_validation": False,
                    "validation_flags": {},
                }

        elif event == "start" and tag == "AutoEnter" and current_field is not None:
            current_field["is_calculation"] = _bool(elem.attrib.get("calculation"))
            current_field["always_evaluate"] = _bool(elem.attrib.get("alwaysEvaluate"))

        elif event == "start" and tag == "Calculation" and current_field is not None \
                and current_validation is None:
            # Calculation text for the field's auto-enter formula (skip the
            # one nested inside <Validation>, handled separately below).
            if elem.text:
                current_field["calculation_text"] = elem.text.strip()

        elif event == "start" and tag == "Validation" and current_field is not None:
            current_validation = {"not_empty": False, "unique": False,
                                   "existing": False, "strict": False}

        elif event == "start" and tag == "NotEmpty" and current_validation is not None:
            current_validation["not_empty"] = _bool(elem.attrib.get("value"))
        elif event == "start" and tag == "Unique" and current_validation is not None:
            current_validation["unique"] = _bool(elem.attrib.get("value"))
        elif event == "start" and tag == "Existing" and current_validation is not None:
            current_validation["existing"] = _bool(elem.attrib.get("value"))
        elif event == "start" and tag == "StrictValidation" and current_validation is not None:
            current_validation["strict"] = _bool(elem.attrib.get("value"))

        elif event == "end" and tag == "Validation" and current_field is not None:
            current_field["validation_flags"] = current_validation
            current_field["has_validation"] = any(current_validation.values())
            current_validation = None

        elif event == "start" and tag == "Storage" and current_field is not None:
            current_field["storage_index"] = elem.attrib.get("index")
            current_field["is_global"] = _bool(elem.attrib.get("global"))

        elif event == "end" and tag == "Field" and in_field_catalog and current_table is not None:
            field_depth -= 1
            if field_depth == 0:
                if current_field is not None:
                    current_table["fields"].append(current_field)
                current_field = None

        elif event == "end" and tag == "BaseTable":
            current_table = None

        # ================= RELATIONSHIPS =================
        elif event == "start" and tag == "Relationship":
            current_relationship = {
                "id": elem.attrib.get("id"),
                "left_table": None,
                "right_table": None,
                "predicates": [],
            }

        elif event == "start" and tag == "LeftTable" and current_relationship is not None:
            current_relationship["left_table"] = elem.attrib.get("name")
        elif event == "start" and tag == "RightTable" and current_relationship is not None:
            current_relationship["right_table"] = elem.attrib.get("name")

        elif event == "start" and tag == "JoinPredicate" and current_relationship is not None:
            current_predicate = {"type": elem.attrib.get("type"),
                                  "left_field": None, "right_field": None}
        elif event == "start" and tag == "LeftField" and current_predicate is not None:
            in_left_field = True
        elif event == "end" and tag == "LeftField":
            in_left_field = False
        elif event == "start" and tag == "RightField" and current_predicate is not None:
            in_right_field = True
        elif event == "end" and tag == "RightField":
            in_right_field = False
        elif event == "start" and tag == "Field" and (in_left_field or in_right_field) \
                and current_predicate is not None:
            ref = {"table": elem.attrib.get("table"), "id": elem.attrib.get("id"),
                   "name": elem.attrib.get("name")}
            if in_left_field:
                current_predicate["left_field"] = ref
            else:
                current_predicate["right_field"] = ref

        elif event == "end" and tag == "JoinPredicate" and current_relationship is not None:
            current_relationship["predicates"].append(current_predicate)
            current_predicate = None

        elif event == "end" and tag == "Relationship":
            if current_relationship is not None:
                result["relationships"].append(current_relationship)
            current_relationship = None

        # ================= LAYOUTS =================
        elif event == "start" and tag == "LayoutCatalog":
            in_layout_catalog = True
        elif event == "end" and tag == "LayoutCatalog":
            in_layout_catalog = False

        elif event == "start" and tag == "Layout" and in_layout_catalog and current_layout is None:
            current_layout = {
                "name": elem.attrib.get("name"),
                "id": elem.attrib.get("id"),
                "object_count": 0,
                "field_objects": [],
                "portal_objects": [],
                "max_conditional_format_depth": 0,
            }

        elif event == "start" and tag == "Object" and current_layout is not None:
            current_layout["object_count"] += 1
            current_object_type = elem.attrib.get("type")

        elif event == "start" and tag == "Name" and current_object_type == "Field" \
                and current_layout is not None and elem.text:
            # <FieldObj><Name>Table::Field</Name> -- simplest reliable source
            if "::" in elem.text:
                table, _, field = elem.text.partition("::")
                current_layout["field_objects"].append({"table": table, "field": field})

        elif event == "start" and tag == "PortalObj" and current_layout is not None:
            num_rows = elem.attrib.get("numOfRows")
            current_layout["portal_objects"].append({
                "num_rows": int(num_rows) if num_rows and num_rows.isdigit() else None,
            })

        elif event == "start" and tag == "Conditions" and current_layout is not None:
            current_conditions_depth = 0
        elif event == "start" and tag == "Condition" and current_layout is not None:
            current_conditions_depth += 1
        elif event == "end" and tag == "Conditions" and current_layout is not None:
            current_layout["max_conditional_format_depth"] = max(
                current_layout["max_conditional_format_depth"], current_conditions_depth)
            current_conditions_depth = 0

        elif event == "end" and tag == "Object" and current_layout is not None:
            current_object_type = None

        elif event == "end" and tag == "Layout" and current_layout is not None:
            result["layouts"].append(current_layout)
            current_layout = None

        # ================= SCRIPTS =================
        elif event == "start" and tag == "ScriptCatalog":
            in_script_catalog = True
        elif event == "end" and tag == "ScriptCatalog":
            in_script_catalog = False

        elif event == "start" and tag == "Script" and in_script_catalog and current_script is None:
            # NOTE: <Script id=".." name=".."/> also appears as a bare
            # *reference* elsewhere (e.g. inside a "Perform Script" step,
            # or a button's script trigger). We only start a NEW script
            # definition here if we are not already inside one (a
            # "Perform Script" step's nested <Script> ref would otherwise
            # be mistaken for a new top-level script).
            current_script = {
                "id": elem.attrib.get("id"),
                "name": elem.attrib.get("name"),
                "steps": [],
            }

        elif event == "start" and tag == "Step" and current_script is not None:
            current_step = {
                "id": elem.attrib.get("id"),
                # NOTE: FileMaker's Step@id is a FIXED id per step *type*
                # (every "Loop" step in the whole file has the same id) --
                # it does NOT identify a specific instance. "position" is
                # the 1-based order of this step within its own script,
                # which is what detection_rules.py uses to point at a
                # specific step (e.g. "Data HTML > Step 42").
                "position": len(current_script["steps"]) + 1,
                "name": elem.attrib.get("name"),
                "enabled": _bool(elem.attrib.get("enable"), default=True),
                "text": None,
                "field": None,
                "target_script": None,
            }

        elif event == "start" and tag == "StepText" and current_step is not None and elem.text:
            current_step["text"] = elem.text.strip()

        elif event == "start" and tag == "Field" and current_step is not None \
                and current_step["name"] != "Perform Script":
            # Structured field reference for steps like "Set Field",
            # "Replace Field Contents", "Insert from URL", etc.
            current_step["field"] = {"table": elem.attrib.get("table"),
                                      "id": elem.attrib.get("id"),
                                      "name": elem.attrib.get("name")}

        elif event == "start" and tag == "Script" and current_step is not None \
                and current_step["name"] == "Perform Script":
            # This is the nested <Script id=".." name=".."/> reference
            # naming which script a "Perform Script" step calls.
            current_step["target_script"] = elem.attrib.get("name")

        elif event == "end" and tag == "Step" and current_script is not None:
            if current_step is not None:
                current_script["steps"].append(current_step)
            current_step = None

        elif event == "end" and tag == "Script" and current_step is None:
            # Only close a script definition on the matching top-level end
            # (current_step is None means we're not inside a nested ref).
            if current_script is not None:
                script_name = (current_script.get("name") or "").strip()
                if script_name and script_name != "-":
                    result["scripts"].append(current_script)
            current_script = None

        # ---------------- Memory cleanup ----------------
        if event == "end":
            elem.clear()

    return result


# ---------------------------------------------------------------------------
# Quick manual test / CLI entry point
# ---------------------------------------------------------------------------

def summarize(data: dict) -> None:
    """Print a short human-readable summary of parsed DDR data."""
    n_fields = sum(len(t["fields"]) for t in data["tables"].values())
    n_steps = sum(len(s["steps"]) for s in data["scripts"])
    print(f"Tables:          {len(data['tables'])}")
    print(f"Fields total:    {n_fields}")
    print(f"Relationships:   {len(data['relationships'])}")
    print(f"Layouts:         {len(data['layouts'])}")
    print(f"Scripts:         {len(data['scripts'])}")
    print(f"Steps total:     {n_steps}")

    print("\n--- Tables ---")
    for name, t in data["tables"].items():
        print(f"  {name} (id={t['id']}, records={t['record_count']}) — {len(t['fields'])} fields")

    print("\n--- Relationships ---")
    for r in data["relationships"]:
        print(f"  {r['left_table']} <-> {r['right_table']}  "
              f"({', '.join(p['type'] for p in r['predicates'])})")

    print("\n--- Layouts ---")
    for l in data["layouts"]:
        print(f"  {l['name']} — {l['object_count']} objects, {len(l['portal_objects'])} portals")

    print("\n--- Scripts ---")
    for s in data["scripts"]:
        print(f"  {s['name']} — {len(s['steps'])} steps")


if __name__ == "__main__":
    import sys

    file_path = sys.argv[1] if len(sys.argv) > 1 else "sample_ddr.xml"
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)

    parsed = parse_ddr(file_path)
    summarize(parsed)
