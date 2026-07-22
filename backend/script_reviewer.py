"""
script_reviewer.py

DAY 3 DELIVERABLE: Script Reviewer (Module 2)
-----------------------------------------------
Goal: take the scripts parsed by ddr_parser.py (Day 1) and send each
one to an AI model (Claude or Gemini) to catch the kind of issues that
static rules in detection_rules.py (Day 2) CAN'T reliably catch --
things that need actual reading comprehension of what the script is
trying to do, e.g.:
    - business logic that looks wrong or inconsistent
    - a script that does something risky without explaining why
    - naming that doesn't match what the script actually does
    - steps that look redundant or contradict each other
    - missing handling for an obvious edge case

NOTE: this module is standalone per the brief ("does not require a
DDR -- it works on its own"), so its prompt covers the FULL Module 2
detection list on its own (loop without exit, missing error capture,
hard-coded values, redundant Set Variable, etc.) rather than assuming
Day 2's DDR-only rules will catch the mechanical issues -- a
paste-only script never goes through Day 2 at all.

OUTPUT CONTRACT (matches Day 2's schema exactly, so both modules'
findings can be merged into one report):
    {
      "module": "script",
      "severity": "Critical" | "Warning" | "Info",
      "location": "ScriptName",
      "description": "...",
      "suggestion": "...",
    }

SUCCESS CRITERION THIS FILE IS RESPONSIBLE FOR:
    "Script and SQL modules return valid, parseable JSON every time --
     no exceptions."
  -> All the actual safety work for that lives in ai_client.py
     (call_ai_for_findings never raises, always returns a list).
     This file just needs to not undo that guarantee -- so
     review_script() and review_all_scripts() are wrapped too.
"""

import json
from ai_client import call_ai_for_findings

SYSTEM_PROMPT = """You are a senior FileMaker developer reviewing a colleague's script during a code audit.

You will be shown one FileMaker script as a numbered list of steps (each step's name and its full StepText).

IMPORTANT: this review may be the ONLY check this script ever gets -- it
is often run standalone, with no DDR file involved at all, so you must
NOT assume any other module has already caught the mechanical issues
below. Check for all of the following:

  - Loops without an Exit Loop If -- infinite loop risk
  - Set Field steps that reference a field by name without any context
    check (e.g. no verification the record/found set is what's expected
    before writing to it)
  - Hard-coded values (IDs, account names, URLs, literal file paths)
    that should instead come from a global field, variable, or
    preferences/config table
  - Redundant Set Variable steps -- a variable that is set but never
    referenced again later in the script
  - Error handling gaps -- steps that can fail silently (ODBC calls,
    imports, Insert from URL, Perform Script on Server, Execute SQL,
    Open ODBC Connection, Export Records) with no Set Error Capture /
    Get(LastError) check anywhere in the script
  - Perform Script calls with no handling of the called script's result
    (e.g. $result / Get(ScriptResult) is never checked)
  - Overly long If / Else If chains (roughly 4+ branches) that would be
    clearer and easier to maintain as a single Case-based calculation
  - Replace Field Contents targeting a container field -- this destroys
    container data silently
  - A script that calls itself recursively (Perform Script naming its
    own script) with no counter or depth-guard variable
  - Go to Related Record with no specific "using layout" clause --
    unpredictable behaviour
  - Any other judgement-based issue that requires understanding what the
    script is trying to DO: inconsistent/contradictory business logic,
    a risky or destructive step (delete, replace, commit) with no
    condition guard, dead code, a script name that doesn't match what it
    actually does, or an obvious unhandled edge case (empty found set,
    zero records, null value)

If you find nothing worth flagging, return an empty array -- do not invent issues just to have something to say.

Respond with ONLY a JSON array, nothing else -- no markdown fences, no explanation before or after. Each item must look exactly like this:
[
  {"severity": "Critical" | "Warning" | "Info", "location": "<step number or short description of where>", "description": "<what the issue is, one or two sentences>", "suggestion": "<how to fix it, one sentence>"}
]
"""


def _format_script_for_prompt(script: dict) -> str:
    """Turn a parsed script dict (from ddr_parser.py) into the plain
    numbered-step text the AI actually reads."""
    lines = [f"Script name: {script['name']}", "Steps:"]
    for step in script["steps"]:
        marker = "" if step["enabled"] else " [DISABLED]"
        text = step["text"] or step["name"]
        lines.append(f"  {step['position']}. {text}{marker}")
    return "\n".join(lines)


def review_script(script: dict, provider: str | None = None) -> list[dict]:
    """
    Review ONE script with the AI and return a safe list of findings
    (never raises -- see ai_client.call_ai_for_findings).
    Skips the AI call entirely for trivial scripts (<3 steps) since
    there's nothing meaningful to review and it just burns API calls.
    """
    if len(script.get("steps", [])) < 3:
        return []

    user_prompt = _format_script_for_prompt(script)

    findings = call_ai_for_findings(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        module="script",
        provider=provider,
    )

    # The AI doesn't know the script's name unless we stamp it on --
    # make sure every location is prefixed so it's identifiable in the
    # final merged report (matches Day 2's "ScriptName > Step 12" style).
    for f in findings:
        if not f["location"].startswith(script["name"]):
            f["location"] = f"{script['name']} > {f['location']}"

    return findings


def review_script_text(raw_text: str, script_name: str = "Pasted Script",
                        provider: str | None = None) -> list[dict]:
    """
    DAY 4 ADAPTER: review_script() above needs a parsed script dict
    (from ddr_parser.py) with a proper steps list. But the Day 4 web
    UI's Script tab is just a plain text box -- the user pastes
    whatever script text they have (copied out of FileMaker, or typed
    by hand), with no DDR file involved at all.

    This function skips the "parsed step list" requirement entirely
    and sends the raw pasted text straight to the AI using the exact
    same system prompt as review_script(), so the two code paths stay
    consistent. Same safety guarantee: never raises, always returns a
    valid list (possibly empty).
    """
    if not raw_text or not raw_text.strip():
        return []

    findings = call_ai_for_findings(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Script name: {script_name}\nSteps:\n{raw_text.strip()}",
        module="script",
        provider=provider,
    )

    for f in findings:
        if not f["location"].startswith(script_name):
            f["location"] = f"{script_name} > {f['location']}"

    return findings


def review_all_scripts(data: dict, provider: str | None = None,
                        max_scripts: int | None = None) -> list[dict]:
    """
    Run review_script() over every script in the parsed DDR data.
    max_scripts caps how many scripts get sent to the AI (useful while
    testing, so you don't burn API credits reviewing all 53 scripts
    every run) -- None means review everything.
    """
    all_findings = []
    scripts = data.get("scripts", [])
    if max_scripts is not None:
        scripts = scripts[:max_scripts]

    for script in scripts:
        try:
            all_findings.extend(review_script(script, provider=provider))
        except Exception as e:
            # Belt-and-braces: even if something outside ai_client.py's
            # own safety net goes wrong (e.g. a malformed script dict),
            # one bad script must not stop the whole batch.
            all_findings.append({
                "module": "script",
                "severity": "Info",
                "location": script.get("name", "Unknown script"),
                "description": f"Could not complete review for this script: {e}",
                "suggestion": "Re-run the review for this script individually.",
            })

    return all_findings


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from ddr_parser import parse_ddr

    file_path = sys.argv[1] if len(sys.argv) > 1 else "sample_ddr.xml"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3  # small default while testing

    data = parse_ddr(file_path)
    findings = review_all_scripts(data, max_scripts=limit)

    print(f"Reviewed {min(limit, len(data['scripts']))} script(s), "
          f"{len(findings)} finding(s):\n")
    for f in findings:
        print(f"[{f['severity']:8s}] {f['location']}")
        print(f"           {f['description']}")
        print(f"           -> {f['suggestion']}\n")

    with open("script_findings.json", "w", encoding="utf-8") as out:
        json.dump({"findings": findings}, out, indent=2)
    print("Saved: script_findings.json")
