"""
variable_audit.py

$$Global / $local Variable Tracking
------------------------------------
Inspired by the "Variables" tab on the FM Changelog reference tool.
Scans every script step's rendered text (StepText) for FileMaker
variable tokens ($$Global and $local), plus every calculation field's
formula text, to work out where each variable is SET vs GET (read).

Detection rules (best-effort, static only -- this never runs the file):
  - On a "Set Variable" step, the FIRST variable token in the step's
    text is treated as the SET target for that variable. Any other
    variable token appearing later in that same step's text (i.e.
    inside the "Value:" expression) is counted as a GET for that
    other variable.
  - Every variable token found in any other step's text, or inside a
    calculation field's formula, counts as a GET (a read/use) of
    that variable.
  - "$$Name" (double-dollar prefix) = global variable.
    "$Name" (single dollar, not immediately followed by another $)
    = local variable.

Nothing here re-parses the DDR -- it works off the same parsed_data
dict every other audit module uses (ddr_parser.parse_ddr output).
"""

import re

_VAR_TOKEN = re.compile(r'\$\$[A-Za-z_][A-Za-z0-9_]*|(?<!\$)\$[A-Za-z_][A-Za-z0-9_]*')


def _is_set_variable_step(step: dict) -> bool:
    name = (step.get("name") or "").lower().replace(" ", "")
    return name == "setvariable"


def _find_vars(text: str) -> list[str]:
    """All $$Global / $local tokens found in text, in order of appearance."""
    if not text:
        return []
    return [m.group(0) for m in _VAR_TOKEN.finditer(text)]


def build_variable_audit(data: dict) -> dict:
    """One entry per distinct variable name found anywhere in the
    solution, with set/get counts and every location it was touched."""
    entries: dict[str, dict] = {}

    def touch(name: str) -> dict:
        return entries.setdefault(name, {
            "name": name,
            "is_global": name.startswith("$$"),
            "sets": 0,
            "gets": 0,
            "set_locations": [],
            "get_locations": [],
        })

    for script in data.get("scripts", []):
        script_name = script.get("name", "Unnamed script")
        for step in script.get("steps", []):
            text = step.get("text") or ""
            tokens = _find_vars(text)
            if not tokens:
                continue
            location = {
                "script_name": script_name,
                "position": step.get("position"),
                "step_name": step.get("name"),
                "text": text,
            }
            if _is_set_variable_step(step):
                set_name = tokens[0]
                entry = touch(set_name)
                entry["sets"] += 1
                entry["set_locations"].append(location)
                seen = {set_name}
                for get_name in tokens[1:]:
                    if get_name in seen:
                        continue
                    seen.add(get_name)
                    g = touch(get_name)
                    g["gets"] += 1
                    g["get_locations"].append(location)
            else:
                seen = set()
                for get_name in tokens:
                    if get_name in seen:
                        continue
                    seen.add(get_name)
                    g = touch(get_name)
                    g["gets"] += 1
                    g["get_locations"].append(location)

    # Calculation fields can reference variables too (Let/plugin calls,
    # global variables seeded elsewhere) -- count these as GET locations.
    for table_name, table in data.get("tables", {}).items():
        for f in table.get("fields", []):
            calc = f.get("calculation_text")
            if not calc:
                continue
            tokens = set(_find_vars(calc))
            if not tokens:
                continue
            location = {
                "table_name": table_name,
                "field_name": f.get("name"),
                "text": calc,
            }
            for get_name in tokens:
                g = touch(get_name)
                g["gets"] += 1
                g["get_locations"].append(location)

    def status_for(entry: dict) -> str:
        if entry["sets"] and not entry["gets"]:
            return "Write-only (dead code?)"
        if entry["gets"] and not entry["sets"]:
            return "Read-only"
        return "OK"

    for entry in entries.values():
        entry["status"] = status_for(entry)

    globals_list = sorted((e for e in entries.values() if e["is_global"]), key=lambda e: e["name"].lower())
    locals_list = sorted((e for e in entries.values() if not e["is_global"]), key=lambda e: e["name"].lower())

    return {
        "stats": {
            "total_globals": len(globals_list),
            "total_locals": len(locals_list),
            "write_only_count": sum(1 for e in entries.values() if e["status"] == "Write-only (dead code?)"),
            "read_only_globals_count": sum(1 for e in globals_list if e["status"] == "Read-only"),
        },
        "globals": globals_list,
        "locals": locals_list,
    }


def build_variable_detail(data: dict, var_name: str) -> dict | None:
    """Full set/get location list for one variable -- the Variables
    tab's row-click detail."""
    audit = build_variable_audit(data)
    for entry in audit["globals"] + audit["locals"]:
        if entry["name"] == var_name:
            return entry
    return None
