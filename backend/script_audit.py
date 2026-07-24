"""Saved-DDR Script Audit.

FileMaker scripts are not reliably available as a clean copy/paste export.
The DDR already contains their names and steps, so this module builds a
professional script inventory directly from a saved snapshot instead.
"""

from call_chain import _build_call_graph, _is_in_cycle


def _is_separator(script: dict) -> bool:
    """FileMaker's Manage Scripts list lets you insert visual
    separator lines between scripts. The DDR still exports these as
    a real <Script> element -- typically named "-" (or blank) with
    zero steps. They are not actual scripts and must not show up as
    rows in the audit table or count toward Scripts / Unused Scripts."""
    name = (script.get("name") or "").strip()
    steps = script.get("steps") or []
    if steps:
        return False
    return name == "" or set(name) <= {"-"}


RISKY_STEPS = {
    "Insert from URL", "Perform Script on Server", "Import Records",
    "Execute SQL", "Open ODBC Connection", "Export Records",
}
DESTRUCTIVE_STEPS = {"Replace Field Contents", "Delete Record/Request", "Delete All Records"}


def _loop_summary(steps: list[dict]) -> tuple[int, int]:
    """Return (total_loops, loops_without_a_visible_exit).

    FileMaker loops can validly terminate either through ``Exit Loop If`` or
    through Go to Record/Request/Page [Next; Exit after last].  The latter
    is the common record-walking pattern and must not be treated as an
    infinite-loop warning.
    """
    stack = []
    loop_count = unsafe_count = 0
    for step in steps:
        name = step.get("name", "")
        if name == "Loop":
            loop_count += 1
            stack.append(False)
        elif stack and (
            name == "Exit Loop If" or
            (name == "Go to Record/Request/Page" and "exit after last" in (step.get("text") or "").lower())
        ):
            stack[-1] = True
        elif name == "End Loop" and stack:
            if not stack.pop():
                unsafe_count += 1
    # A malformed script/DDR with an unclosed Loop is still worth flagging.
    unsafe_count += sum(not has_exit for has_exit in stack)
    return loop_count, unsafe_count


def _issues_for_script(script: dict, outgoing: dict) -> list[dict]:
    steps = script.get("steps", [])
    names = [step.get("name", "") for step in steps]
    text = "\n".join(step.get("text") or "" for step in steps).lower()
    issues = []

    risky = sorted(set(names) & RISKY_STEPS)
    error_capture_on = any(
        step.get("name") == "Set Error Capture" and "off" not in (step.get("text") or "").lower()
        for step in steps
    )
    if risky and not error_capture_on and "lasterror" not in text:
        issues.append({"severity": "Warning", "label": "Missing error handling",
                       "detail": "Uses failure-prone steps without visible error capture or Get(LastError)."})
    loop_count, unsafe_loops = _loop_summary(steps)
    if unsafe_loops:
        issues.append({"severity": "Warning", "label": "Loop without explicit exit",
                       "detail": f"{unsafe_loops} loop(s) have no visible Exit Loop If or Next; Exit after last step."})
    repeated_record_scans = sum(step.get("name") == "Show All Records" for step in steps)
    if repeated_record_scans >= 5:
        issues.append({"severity": "Info", "label": "Repeated record scans",
                       "detail": f"This script runs Show All Records {repeated_record_scans} times across {loop_count} loops. Consider building each output row in one record-walking loop for better performance."})
    if outgoing.get(script.get("name")) and _is_in_cycle(script.get("name"), outgoing):
        issues.append({"severity": "Warning", "label": "Call cycle",
                       "detail": "This script is part of a direct or indirect Perform Script cycle."})
    destructive = sorted(set(names) & DESTRUCTIVE_STEPS)
    if destructive:
        issues.append({"severity": "Critical", "label": "Destructive data step",
                       "detail": "Uses " + ", ".join(destructive) + "; verify found-set safety and confirmation."})
    if len(steps) > 100 and "# (comment)" not in names:
        issues.append({"severity": "Info", "label": "Long script without comments",
                       "detail": f"Contains {len(steps)} steps and no comment steps."})
    return issues


def build_script_summary(data: dict) -> list[dict]:
    """Compact, searchable script inventory for a snapshot."""
    scripts = data.get("scripts", [])
    outgoing, incoming = _build_call_graph({"scripts": scripts})
    result = []
    for script in scripts:
        if _is_separator(script):
            continue
        name = script.get("name") or "Unnamed script"
        steps = script.get("steps", [])
        issues = _issues_for_script(script, outgoing)
        result.append({
            "script_name": name,
            "step_count": len(steps),
            "comment_count": sum(step.get("name") == "# (comment)" for step in steps),
            "calls": sorted(outgoing.get(name, ())),
            "called_by": sorted(incoming.get(name, ())),
            "issues": issues,
            "critical_count": sum(issue["severity"] == "Critical" for issue in issues),
            "warning_count": sum(issue["severity"] == "Warning" for issue in issues),
        })
    return sorted(result, key=lambda row: (-row["critical_count"], -row["warning_count"], row["script_name"].lower()))


def build_script_detail(data: dict, script_name: str) -> dict | None:
    """Full steps plus call relationships and audit issues for one script."""
    scripts = data.get("scripts", [])
    outgoing, incoming = _build_call_graph({"scripts": scripts})
    script = next((item for item in scripts if item.get("name") == script_name), None)
    if script is None:
        return None
    return {
        "script_name": script_name,
        "steps": [
            {"position": step.get("position"), "name": step.get("name", ""),
             "text": step.get("text") or "", "target_script": step.get("target_script")}
            for step in script.get("steps", [])
        ],
        "calls": sorted(outgoing.get(script_name, ())),
        "called_by": sorted(incoming.get(script_name, ())),
        "issues": _issues_for_script(script, outgoing),
    }
