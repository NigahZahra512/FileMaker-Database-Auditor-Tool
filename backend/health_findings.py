"""
health_findings.py

Category-level findings for the Health Report tab, inspired by the
per-category grade cards on the FM Changelog reference tool's Health
screen (Structure Quality, Data Model, Broken References, Calculation
Complexity, Unused Entities -- Security and Naming Conventions are a
later phase; they need new DDR parsing this file doesn't have yet).

Each function below returns a list of finding dicts:
    {
      "severity": "critical" | "warning" | "info" | "positive",
      "title": "...",   # one-line headline, e.g. "42 very long scripts (200+ steps)"
      "detail": "...",  # one sentence of context/advice
      "tags": [...],    # example items, capped -- "and more..." appended if truncated
    }

These are pure functions over the already-parsed snapshot dict -- no
new DDR parsing. The one exception is the calculation-dependency scan,
which reuses the same TableName::FieldName regex unused_analysis.py
already uses to spot field references inside calc formula text.

HONESTY NOTE on a few of these (same spirit as unused_analysis.py's own
caveat): a handful of checks are best-effort static analysis and can
have false positives/negatives --
  - "Perform Script target not found" can't always tell a genuinely
    broken script call apart from a valid call into ANOTHER FileMaker
    file this DDR doesn't cover, so it's kept at Warning (not Critical)
    and skips anything whose step text mentions "external"/"from file".
  - "Circular calculation dependency" only sees TableName::FieldName
    text inside calc formulas -- a calc that references a field by an
    unqualified name (same table, no "Table::" prefix) won't be caught.
  - "Layout without objects" is a stand-in for FM Changelog's "layout
    without table occurrence" check -- ddr_parser.py doesn't currently
    capture a layout's own base table occurrence, only the fields
    placed on it, so a zero-object layout is the closest signal
    available without a parser change.
"""

from collections import defaultdict

from call_chain import _build_call_graph
from script_audit import _is_separator
from unused_analysis import find_unused_fields, find_unused_scripts, _QUALIFIED_FIELD_RE

_LARGE_TABLE_FIELD_THRESHOLD = 100
_LONG_SCRIPT_STEP_THRESHOLD = 200
_STUB_SCRIPT_STEP_THRESHOLD = 1
_BUSY_TABLE_RELATIONSHIP_THRESHOLD = 15


def _tags(items, cap=10):
    """Cap a tag list so one huge match doesn't blow up the card; the
    frontend shows an 'and more...' chip when this returns a truncated list."""
    items = list(items)
    shown = items[:cap]
    if len(items) > cap:
        shown.append("and more...")
    return shown


# ---------------------------------------------------------------------------
# Structure Quality
# ---------------------------------------------------------------------------

def structure_quality_findings(data):
    findings = []

    large_tables = [
        (name, len(t["fields"])) for name, t in data["tables"].items()
        if len(t["fields"]) >= _LARGE_TABLE_FIELD_THRESHOLD
    ]
    if large_tables:
        large_tables.sort(key=lambda x: -x[1])
        findings.append({
            "severity": "warning",
            "title": f"{len(large_tables)} table(s) with {_LARGE_TABLE_FIELD_THRESHOLD}+ fields",
            "detail": "Very large tables may indicate the need to normalise the data model.",
            "tags": _tags(f"{n}: {c} fields" for n, c in large_tables),
        })

    real_scripts = [s for s in data["scripts"] if not _is_separator(s)]

    stub_scripts = [s["name"] for s in real_scripts if len(s["steps"]) <= _STUB_SCRIPT_STEP_THRESHOLD]
    if stub_scripts:
        findings.append({
            "severity": "info",
            "title": f"{len(stub_scripts)} empty or near-empty script(s)",
            "detail": f"Scripts with 0-{_STUB_SCRIPT_STEP_THRESHOLD} steps may be stubs or leftovers.",
            "tags": _tags(stub_scripts),
        })

    long_scripts = [
        (s["name"], len(s["steps"])) for s in real_scripts
        if len(s["steps"]) >= _LONG_SCRIPT_STEP_THRESHOLD
    ]
    if long_scripts:
        long_scripts.sort(key=lambda x: -x[1])
        findings.append({
            "severity": "warning",
            "title": f"{len(long_scripts)} very long script(s) ({_LONG_SCRIPT_STEP_THRESHOLD}+ steps)",
            "detail": "Long scripts are hard to maintain. Consider breaking them into sub-scripts.",
            "tags": _tags(f"{n}: {c} steps" for n, c in long_scripts),
        })

    blank_layouts = [l["name"] for l in data["layouts"] if l.get("object_count", 0) == 0]
    if blank_layouts:
        findings.append({
            "severity": "info",
            "title": f"{len(blank_layouts)} layout(s) with no objects",
            "detail": "Layouts with zero objects may be unused, or a utility/navigation layout.",
            "tags": _tags(blank_layouts),
        })

    return findings


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

def data_model_findings(data, erd_summary):
    findings = []

    counts = defaultdict(int)
    for rel in data["relationships"]:
        if rel["left_table"]:
            counts[rel["left_table"]] += 1
        if rel["right_table"]:
            counts[rel["right_table"]] += 1
    busy = [(t, c) for t, c in counts.items() if c > _BUSY_TABLE_RELATIONSHIP_THRESHOLD]
    if busy:
        busy.sort(key=lambda x: -x[1])
        findings.append({
            "severity": "warning",
            "title": f"{len(busy)} table(s) in {_BUSY_TABLE_RELATIONSHIP_THRESHOLD}+ relationships",
            "detail": "A large number of relationships per table makes the graph hard to reason about.",
            "tags": _tags(f"{n}: {c} relationships" for n, c in busy),
        })

    cartesian = [
        f"{rel['left_table']} <-> {rel['right_table']}"
        for rel in data["relationships"]
        for pred in rel["predicates"]
        if pred["type"] == "CartesianProduct"
    ]
    if cartesian:
        findings.append({
            "severity": "critical",
            "title": f"{len(cartesian)} Cartesian-product join(s)",
            "detail": "No real match field defined -- every record on one side relates to every record on the other.",
            "tags": _tags(cartesian),
        })

    orphans = erd_summary["orphan_tables"]
    if orphans:
        findings.append({
            "severity": "warning",
            "title": f"{len(orphans)} orphan table(s) (no relationships)",
            "detail": "These tables have zero relationships to any other table in this file.",
            "tags": _tags(orphans),
        })

    return findings


# ---------------------------------------------------------------------------
# Broken References
# ---------------------------------------------------------------------------

def broken_reference_findings(data):
    findings = []
    known_scripts = {s["name"] for s in data["scripts"]}

    missing_targets = set()
    for script in data["scripts"]:
        for step in script["steps"]:
            target = step.get("target_script")
            if not target or target in known_scripts:
                continue
            text = (step.get("text") or "").lower()
            if "external" in text or "from file" in text:
                continue  # likely a call into another FileMaker file, not broken
            missing_targets.add(target)
    if missing_targets:
        findings.append({
            "severity": "warning",
            "title": f"{len(missing_targets)} Perform Script target(s) not found in this file",
            "detail": "May be genuinely deleted/renamed scripts, or valid calls into another file this DDR doesn't cover.",
            "tags": _tags(sorted(missing_targets)),
        })

    broken_layout_fields = set()
    for layout in data["layouts"]:
        for fo in layout.get("field_objects", []):
            table_name, field_name = fo.get("table"), fo.get("field")
            if not table_name or table_name not in data["tables"]:
                continue  # table occurrence isn't a base table in this file -- can't judge
            field_names = {f["name"] for f in data["tables"][table_name]["fields"]}
            if field_name not in field_names:
                broken_layout_fields.add(f"{layout['name']}: {table_name}::{field_name}")
    if broken_layout_fields:
        findings.append({
            "severity": "critical",
            "title": f"{len(broken_layout_fields)} layout field object(s) point at a missing field",
            "detail": "The field no longer exists on its table -- likely renamed or deleted after the layout was built.",
            "tags": _tags(sorted(broken_layout_fields)),
        })

    return findings


# ---------------------------------------------------------------------------
# Calculation Complexity
# ---------------------------------------------------------------------------

def _calc_dependency_graph(data):
    """{(table, field) -> set of (table, field) it references}, restricted
    to fields that are THEMSELVES calculations (only those can take part
    in a circular calculation)."""
    calc_fields = set()
    for table_name, table in data["tables"].items():
        for f in table["fields"]:
            if f.get("is_calculation"):
                calc_fields.add((table_name, f["name"]))

    graph = defaultdict(set)
    for table_name, table in data["tables"].items():
        for f in table["fields"]:
            if not f.get("is_calculation"):
                continue
            calc_text = f.get("calculation_text") or ""
            for tbl, fld in _QUALIFIED_FIELD_RE.findall(calc_text):
                ref = (tbl.strip(), fld.strip())
                if ref in calc_fields:
                    graph[(table_name, f["name"])].add(ref)
    return graph


def _find_calc_cycles(graph):
    """DFS cycle detection over the calc-dependency graph -- same
    approach as detection_rules.rule_circular_relationships, just over
    a directed field graph instead of an undirected table graph."""
    reported = set()
    cycles = []

    def dfs(node, path, path_set):
        for neighbor in graph.get(node, ()):
            if neighbor in path_set:
                idx = path.index(neighbor)
                cycle = path[idx:] + [neighbor]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    cycles.append(cycle)
                continue
            if neighbor in path:
                continue
            dfs(neighbor, path + [neighbor], path_set | {neighbor})

    for node in list(graph.keys()):
        dfs(node, [node], {node})
    return cycles


def calc_complexity_findings(data):
    findings = []

    graph = _calc_dependency_graph(data)
    cycles = _find_calc_cycles(graph)
    if cycles:
        tag_list = [" -> ".join(f"{t}::{f}" for t, f in cycle) for cycle in cycles]
        label = "circular calculation dependency" if len(cycles) == 1 else "circular calculation dependencies"
        findings.append({
            "severity": "critical",
            "title": f"{len(cycles)} {label}",
            "detail": "Circular references can cause evaluation errors and unpredictable results.",
            "tags": _tags(tag_list),
        })

    outgoing, _incoming = _build_call_graph(data)
    self_loop_scripts = sorted(name for name, targets in outgoing.items() if name in targets)
    if self_loop_scripts:
        findings.append({
            "severity": "warning",
            "title": f"{len(self_loop_scripts)} script(s) calling itself (self-loop)",
            "detail": "Recursive scripts are valid but must have a terminating condition.",
            "tags": _tags(self_loop_scripts),
        })

    return findings


def calc_stats(data):
    total_calcs = sum(
        1 for t in data["tables"].values() for f in t["fields"] if f.get("is_calculation")
    )
    graph = _calc_dependency_graph(data)
    cycles = _find_calc_cycles(graph)
    return {"total_calcs": total_calcs, "circular_count": len(cycles)}


# ---------------------------------------------------------------------------
# Unused Entities (repackages the existing unused-fields/scripts detection
# that already powers the Explore tab -- no new detection logic, just a
# card-shaped view of it)
# ---------------------------------------------------------------------------

def unused_entities_findings(data):
    findings = []
    total_fields = sum(len(t["fields"]) for t in data["tables"].values())
    real_scripts = [s for s in data["scripts"] if not _is_separator(s)]

    unused_field_findings = find_unused_fields(data)
    if unused_field_findings:
        pct = round(100 * len(unused_field_findings) / total_fields) if total_fields else 0
        findings.append({
            "severity": "warning",
            "title": f"{len(unused_field_findings)} unreferenced field(s) ({pct}%)",
            "detail": "Not referenced in any calculation, script, relationship, or layout visible in this DDR export.",
            "tags": _tags(f["location"] for f in unused_field_findings),
        })

    unused_script_findings = find_unused_scripts(data)
    if unused_script_findings:
        pct = round(100 * len(unused_script_findings) / len(real_scripts)) if real_scripts else 0
        findings.append({
            "severity": "warning",
            "title": f"{len(unused_script_findings)} unreferenced script(s) ({pct}%)",
            "detail": "Never called by Perform Script from another script in this file.",
            "tags": _tags(f["location"] for f in unused_script_findings),
        })

    return findings, len(unused_field_findings), len(unused_script_findings)
