"""
combine_reports.py

DAY 4 - STEP 1: Combine all three modules' findings into one file
--------------------------------------------------------------------
By this point we have THREE separate JSON files sitting in the
project folder, one per module:
    ddr_findings.json     (from detection_rules.py     - Day 2)
    script_findings.json  (from script_reviewer.py      - Day 3)
    sql_findings.json     (from sql_reviewer.py          - Day 3)

Each one already uses the exact same finding shape:
    {"module": ..., "severity": ..., "location": ..., "description": ..., "suggestion": ...}

That's the whole point of keeping the schema identical across Day 2
and Day 3 -- combining them is just "read 3 files, add their lists
together". No conversion or reformatting needed.

WHAT THIS SCRIPT DOES, STEP BY STEP:
    1. Reads each of the 3 JSON files (safely -- a missing file just
       means "that module hasn't been run yet", not a crash)
    2. Puts all their findings into one big list
    3. Sorts that list so Critical findings show up first, then
       Warning, then Info (easier to read top-to-bottom)
    4. Recalculates the summary counts (Critical/Warning/Info totals)
       across the combined set
    5. Saves everything into one file: combined_findings.json

This combined file is what the HTML report (the next step) will
actually read from -- the report script won't need to know anything
about ddr/script/sql being separate at all.
"""

import json
import os

SEVERITY_ORDER = {"Critical": 0, "Warning": 1, "Info": 2}

SOURCE_FILES = [
    "ddr_findings.json",
    "script_findings.json",
    "sql_findings.json",
]


def load_findings(file_path: str) -> list[dict]:
    """
    Reads one findings JSON file and returns its list of findings.
    Never raises -- if the file is missing or broken, it just prints
    a note and returns an empty list, so combining can still continue
    with whatever files ARE present.
    """
    if not os.path.exists(file_path):
        print(f"  - {file_path} not found, skipping (module not run yet?)")
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        findings = data.get("findings", [])
        print(f"  - {file_path}: {len(findings)} finding(s)")
        return findings
    except (json.JSONDecodeError, OSError) as e:
        print(f"  - {file_path} could not be read ({e}), skipping")
        return []


def combine_findings(source_files: list[str] = SOURCE_FILES) -> dict:
    """
    Reads all source files, merges + sorts their findings, and builds
    the final combined report dict (same shape as the individual
    files, so nothing downstream needs to change).
    """
    print("Reading findings from each module:")
    all_findings = []
    for file_path in source_files:
        all_findings.extend(load_findings(file_path))

    # Sort: Critical first, then Warning, then Info. Findings with an
    # unrecognised severity go last instead of crashing the sort.
    all_findings.sort(key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 99))

    summary = {"critical": 0, "warning": 0, "info": 0}
    for f in all_findings:
        sev = f.get("severity")
        if sev in SEVERITY_ORDER:
            summary[sev.lower()] += 1

    return {
        "summary": summary,
        "findings": all_findings,
    }


if __name__ == "__main__":
    combined = combine_findings()

    with open("combined_findings.json", "w", encoding="utf-8") as out:
        json.dump(combined, out, indent=2)

    total = len(combined["findings"])
    s = combined["summary"]
    print(f"\nCombined total: {total} finding(s) "
          f"(Critical={s['critical']}, Warning={s['warning']}, Info={s['info']})")
    print("Saved: combined_findings.json")
