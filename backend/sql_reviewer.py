"""
sql_reviewer.py

DAY 3 DELIVERABLE: SQL Reviewer (Module 3)
---------------------------------------------
Goal: find every "Execute SQL" step inside every script (parsed by
ddr_parser.py in Day 1), pull out the raw SQL text, and send it to an
AI model to check for things a plain-text search can't reliably catch
on its own -- SQL injection risk, missing WHERE clauses, SELECT *,
and other bad-practice patterns.

WHERE THE SQL TEXT ACTUALLY LIVES:
  ddr_parser.py stores each step's full human-readable text in
  step["text"] (from <StepText>). For an "Execute SQL" step this text
  looks like:
      Execute SQL [ Result: $result ; SQL: SELECT * FROM Employees
                     WHERE ID = " & $userInput & " ]
  So step["text"] already has everything we need -- no separate
  parsing logic needed in ddr_parser.py itself, we just filter for
  step["name"] == "Execute SQL" and hand the whole text to the AI.

WHY THIS IS A SEPARATE MODULE FROM script_reviewer.py:
  A script can contain business logic issues (script_reviewer.py's job)
  AND a bad SQL statement (this file's job) at the same time -- they
  are different kinds of problems needing a different, focused prompt.
  Splitting them also means each AI call is smaller and cheaper (a
  short SQL snippet instead of the whole script).

OUTPUT CONTRACT (same schema as Day 2 and script_reviewer.py, module
tag is "sql" so it's identifiable in the merged report):
    {
      "module": "sql",
      "severity": "Critical" | "Warning" | "Info",
      "location": "ScriptName > Step 12 (Execute SQL)",
      "description": "...",
      "suggestion": "...",
    }

SUCCESS CRITERION THIS FILE IS RESPONSIBLE FOR (same as script_reviewer.py):
    "Script and SQL modules return valid, parseable JSON every time --
     no exceptions."
  -> Same safety net: all the AI-call/JSON-safety logic lives in
     ai_client.py (call_ai_for_findings never raises). This file wraps
     its own extraction/loop logic in try/except too, so one malformed
     step can't take down the whole batch.
"""

import json
from ai_client import call_ai_for_findings

SYSTEM_PROMPT = """You are a senior database developer reviewing raw SQL statements pulled out of a FileMaker "Execute SQL" script step, during a security and performance audit.

You will be shown the step's full text, which includes the SQL statement (and sometimes FileMaker variables like $variableName mixed into it via string concatenation).

Look specifically for:
  - SELECT * instead of naming only the needed columns
  - A WHERE clause built on a field that doesn't look indexed (or no
    WHERE clause at all on a SELECT/UPDATE/DELETE) -- forces a full
    table scan, or in the UPDATE/DELETE case can accidentally affect
    every row
  - Missing or incorrect JOIN conditions -- a join with no ON/USING
    clause (or an always-true condition) creates an accidental
    Cartesian product
  - A subquery that could be rewritten as a JOIN for better performance
  - LIKE with a leading wildcard (e.g. LIKE '%value') -- cannot use an
    index, forces a full scan
  - A query with no ORDER BY where result order clearly matters --
    row order is otherwise unpredictable
  - SQL injection risk: a variable or field value concatenated directly
    into the SQL string instead of using a parameterised "?" placeholder
  - Any other clearly wrong or dangerous SQL (e.g. string-built
    DELETE/DROP, no LIMIT on a query that could return a huge result set)

If the SQL looks safe and reasonable, return an empty array -- do not invent issues just to have something to say.

Respond with ONLY a JSON array, nothing else -- no markdown fences, no explanation before or after. Each item must look exactly like this:
[
  {"severity": "Critical" | "Warning" | "Info", "location": "<short description of where in the SQL, e.g. 'WHERE clause'>", "description": "<what the issue is, one or two sentences>", "suggestion": "<how to fix it, one sentence>"}
]

Severity guide: SQL injection risk or a WHERE-less UPDATE/DELETE = Critical. SELECT *, missing WHERE index, or a Cartesian-product JOIN = Warning. Style/performance nitpicks (subquery-vs-join, leading-wildcard LIKE, missing ORDER BY) = Info.
"""


def find_sql_steps(data: dict) -> list[dict]:
    """
    Scan every script's steps and pull out just the "Execute SQL"
    ones. Returns a flat list so the caller doesn't need to know
    anything about script/step nesting.
    Output: [{"script_name": ..., "position": ..., "text": ...}, ...]
    """
    sql_steps = []
    for script in data.get("scripts", []):
        for step in script.get("steps", []):
            if step.get("name") == "Execute SQL" and step.get("text"):
                sql_steps.append({
                    "script_name": script["name"],
                    "position": step["position"],
                    "text": step["text"],
                })
    return sql_steps


def review_sql_step(sql_step: dict, provider: str | None = None) -> list[dict]:
    """
    Review ONE Execute SQL step with the AI. Never raises -- see
    ai_client.call_ai_for_findings.
    """
    user_prompt = f"Execute SQL step text:\n{sql_step['text']}"

    findings = call_ai_for_findings(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        module="sql",
        provider=provider,
    )

    base_location = f"{sql_step['script_name']} > Step {sql_step['position']} (Execute SQL)"
    for f in findings:
        if f["location"] == "Unknown" or not f["location"]:
            f["location"] = base_location
        else:
            f["location"] = f"{base_location} -- {f['location']}"

    return findings


def review_sql_text(raw_sql: str, provider: str | None = None) -> list[dict]:
    """
    DAY 4 ADAPTER: review_sql_step() above needs a sql_step dict that
    came from find_sql_steps() (parsed out of a DDR file). But the
    Day 4 web UI's SQL tab is just a plain text box -- the user pastes
    a raw SQL statement directly, no DDR file or script involved.

    Skips the "extracted from a script" requirement and sends the
    pasted SQL straight to the AI using the same system prompt as
    review_sql_step(), so both paths behave consistently. Same safety
    guarantee: never raises, always returns a valid list.
    """
    if not raw_sql or not raw_sql.strip():
        return []

    findings = call_ai_for_findings(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"SQL statement:\n{raw_sql.strip()}",
        module="sql",
        provider=provider,
    )

    for f in findings:
        if f["location"] == "Unknown" or not f["location"]:
            f["location"] = "Pasted SQL"
        else:
            f["location"] = f"Pasted SQL -- {f['location']}"

    return findings


# ---------------------------------------------------------------------------
# DAY 5: SQL rewrite (not just findings -- an actual corrected query)
# ---------------------------------------------------------------------------

REWRITE_SYSTEM_PROMPT = """You are a senior database developer. You will be shown a SQL statement (possibly with FileMaker-style string concatenation using & and $variables).

Rewrite it to be safer and cleaner:
  - Replace any concatenated value with a parameterised placeholder (?)
  - Replace SELECT * with explicit column names if the intent is obvious from context (otherwise leave the columns as-is)
  - Add a WHERE clause placeholder comment if one is clearly missing and dangerous (e.g. -- TODO: add WHERE clause)
  - Keep the rewrite as close to the original intent as possible -- do not invent a different query

Respond with ONLY a JSON object, nothing else -- no markdown fences, no explanation before or after:
{"rewritten_sql": "<the corrected query as a single string>", "explanation": "<one short sentence on what changed and why>"}

If the original SQL is already safe and well-written, return it unchanged in "rewritten_sql" and say so in "explanation".
"""


def get_sql_rewrite(raw_sql: str, provider: str | None = None) -> dict:
    """
    DAY 5: Ask the AI to produce an actual corrected/rewritten version
    of a pasted SQL statement, not just a list of problems. Used by
    the demo requirement: "a SQL paste producing a rewrite".

    Same safety guarantee as everything else in this file -- never
    raises, always returns a dict with both keys, even on failure.
    """
    if not raw_sql or not raw_sql.strip():
        return {"rewritten_sql": "", "explanation": "No SQL was provided."}

    # Reuses call_ai_for_findings' JSON-safety machinery by treating
    # the single rewrite object as a "finding" internally, then
    # unwraps it -- avoids writing a second parallel safe-call path.
    from ai_client import _call_claude, _call_gemini, _call_grok, _call_groq, _call_custom, _extract_json, get_active_provider

    provider = provider or get_active_provider()

    try:
        prompt_text = f"SQL statement:\n{raw_sql.strip()}"
        if provider == "gemini":
            raw = _call_gemini(REWRITE_SYSTEM_PROMPT, prompt_text)
        elif provider == "grok":
            raw = _call_grok(REWRITE_SYSTEM_PROMPT, prompt_text)
        elif provider == "groq":
            raw = _call_groq(REWRITE_SYSTEM_PROMPT, prompt_text)
        elif provider == "custom":
            raw = _call_custom(REWRITE_SYSTEM_PROMPT, prompt_text)
        else:
            raw = _call_claude(REWRITE_SYSTEM_PROMPT, prompt_text)

        parsed = _extract_json(raw) if raw else None

        if not isinstance(parsed, dict) or "rewritten_sql" not in parsed:
            return {
                "rewritten_sql": "",
                "explanation": "AI rewrite could not be completed (no response, or response was not valid JSON).",
            }

        return {
            "rewritten_sql": str(parsed.get("rewritten_sql", "")).strip(),
            "explanation": str(parsed.get("explanation", "")).strip(),
        }

    except Exception as e:
        return {
            "rewritten_sql": "",
            "explanation": f"AI rewrite raised an unexpected error: {e}",
        }


def review_all_sql(data: dict, provider: str | None = None,
                    max_steps: int | None = None) -> list[dict]:
    """
    Find every Execute SQL step in the whole DDR and review each one.
    max_steps caps how many get sent to the AI (useful while testing
    to avoid burning API calls/quota) -- None means review all of them.
    """
    all_findings = []
    sql_steps = find_sql_steps(data)
    if max_steps is not None:
        sql_steps = sql_steps[:max_steps]

    if not sql_steps:
        return []

    for sql_step in sql_steps:
        try:
            all_findings.extend(review_sql_step(sql_step, provider=provider))
        except Exception as e:
            # Belt-and-braces, same as script_reviewer.py -- one bad
            # step must not stop the whole batch.
            all_findings.append({
                "module": "sql",
                "severity": "Info",
                "location": f"{sql_step['script_name']} > Step {sql_step['position']} (Execute SQL)",
                "description": f"Could not complete SQL review for this step: {e}",
                "suggestion": "Re-run the SQL review for this step individually.",
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
    all_sql_steps = find_sql_steps(data)
    print(f"Found {len(all_sql_steps)} Execute SQL step(s) in the DDR.\n")

    findings = review_all_sql(data, max_steps=limit)

    print(f"Reviewed {min(limit, len(all_sql_steps))} SQL step(s), "
          f"{len(findings)} finding(s):\n")
    for f in findings:
        print(f"[{f['severity']:8s}] {f['location']}")
        print(f"           {f['description']}")
        print(f"           -> {f['suggestion']}\n")

    with open("sql_findings.json", "w", encoding="utf-8") as out:
        json.dump({"findings": findings}, out, indent=2)
    print("Saved: sql_findings.json")
