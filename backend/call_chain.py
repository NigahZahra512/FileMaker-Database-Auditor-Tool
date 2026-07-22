"""
call_chain.py

GROUP A FEATURE: Call Chain
------------------------------
Inspired by the "Call Chain" tab on the FM Changelog reference tool --
for every script, show which scripts it calls (outgoing) and which
scripts call it (incoming), built purely from "Perform Script" steps
already captured by ddr_parser.py.

This is informational, not a rule that flags a problem -- so every
row is severity "Info". It reuses the exact same finding shape as
detection_rules.py / unused_analysis.py so it slots into the same
findings list and the same UI table, under its own "Call Chain"
category:
    {
      "module": "ddr",
      "category": "Call Chain",
      "severity": "Info",
      "location": "ScriptName",
      "description": "Calls: A, B, C" | "Does not call any other script.",
      "suggestion": "Called by: X, Y" | "Not called by any script in
                     this file (may still be wired to a button, custom
                     menu, layout trigger, or Server schedule).",
    }

One extra check is layered on top for free: if a script's own name
appears anywhere in its own outgoing-call chain (directly, or through
a few hops), that's a genuine cycle -- those get bumped to "Warning"
since an unguarded cycle can infinite-loop at runtime. This does NOT
duplicate detection_rules.py's rule_recursive_no_guard (that rule only
catches DIRECT self-calls, A calling A); this one also catches
A -> B -> A indirect cycles.
"""

SEVERITY_INFO = "Info"
SEVERITY_WARNING = "Warning"

# How many hops to follow when checking for indirect cycles (A -> B -> C
# -> A). Kept small and fixed since call chains rarely run deeper than
# this in practice, and it keeps the check O(scripts) instead of a full
# unbounded graph traversal.
_MAX_CYCLE_DEPTH = 10


def _build_call_graph(data):
    """Returns (outgoing, incoming): two dicts of {script_name: set(...)}."""
    outgoing = {s["name"]: set() for s in data["scripts"]}
    incoming = {s["name"]: set() for s in data["scripts"]}

    for script in data["scripts"]:
        caller = script["name"]
        for step in script["steps"]:
            target = step.get("target_script")
            if not target:
                continue
            outgoing.setdefault(caller, set()).add(target)
            incoming.setdefault(target, set()).add(caller)

    return outgoing, incoming


def _is_in_cycle(start, outgoing, max_depth=_MAX_CYCLE_DEPTH):
    """True if, starting from `start` and following outgoing calls, we
    can get back to `start` within max_depth hops."""
    visited = set()
    frontier = list(outgoing.get(start, ()))
    depth = 0
    while frontier and depth < max_depth:
        next_frontier = []
        for name in frontier:
            if name == start:
                return True
            if name in visited:
                continue
            visited.add(name)
            next_frontier.extend(outgoing.get(name, ()))
        frontier = next_frontier
        depth += 1
    return False


def build_call_chain(data):
    """One finding per script, describing its outgoing and incoming
    calls. Scripts that sit in a call cycle (direct or indirect) are
    flagged as Warning instead of Info."""
    outgoing, incoming = _build_call_graph(data)
    findings = []

    for script in data["scripts"]:
        name = script["name"]
        calls_out = sorted(outgoing.get(name, ()))
        calls_in = sorted(incoming.get(name, ()))

        description = (
            f"Calls: {', '.join(calls_out)}" if calls_out
            else "Does not call any other script."
        )
        suggestion = (
            f"Called by: {', '.join(calls_in)}" if calls_in
            else "Not called by any script in this file (may still be "
                 "wired to a button, custom menu, layout trigger, or "
                 "Server schedule)."
        )

        severity = SEVERITY_INFO
        if calls_out and _is_in_cycle(name, outgoing):
            severity = SEVERITY_WARNING
            suggestion += (
                " NOTE: this script is part of a call cycle (directly or "
                "through other scripts) -- make sure there's a guard "
                "(counter/condition) to prevent an infinite loop."
            )

        findings.append({
            "module": "ddr",
            "category": "Call Chain",
            "severity": severity,
            "location": name,
            "description": description,
            "suggestion": suggestion,
        })

    return findings
