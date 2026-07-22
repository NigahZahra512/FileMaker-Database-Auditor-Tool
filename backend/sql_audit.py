"""Saved-DDR ExecuteSQL Audit.

FileMaker solutions often place ExecuteSQL expressions inside script steps.
This module discovers those steps from a saved DDR snapshot and performs
safe, best-effort static checks.  It never executes a query or connects to
the FileMaker file; dynamic expressions are labelled clearly instead of
pretending they can be fully verified.
"""

import re


SQL_START = re.compile(r"\b(select|insert|update|delete)\b", re.IGNORECASE)


def _is_execute_sql_step(step: dict) -> bool:
    name = (step.get("name") or "").lower().replace(" ", "")
    text = step.get("text") or ""
    return name in {"executesql", "executesqlquery"} or "executesql" in text.lower()


def _issues_for_expression(expression: str) -> list[dict]:
    lower = expression.lower()
    issues = []
    if not SQL_START.search(expression):
        return [{
            "severity": "Info", "label": "Dynamic SQL expression",
            "detail": "No complete static SQL statement was visible. Review runtime values before relying on this audit.",
        }]
    if re.search(r"\bselect\s+\*\b", lower):
        issues.append({"severity": "Warning", "label": "SELECT *",
                       "detail": "Fetch only the fields needed by the script to reduce work and avoid fragile column-order dependencies."})
    if lower.lstrip().startswith("select") and " where " not in f" {lower} ":
        issues.append({"severity": "Warning", "label": "No WHERE clause",
                       "detail": "This SELECT may read every matching record. Confirm a full-table query is intentional."})
    if "&" in expression:
        issues.append({"severity": "Warning", "label": "Concatenated SQL",
                       "detail": "The query expression is assembled with FileMaker concatenation. Validate values and prefer ExecuteSQL arguments where possible."})
    if re.search(r"\b(delete|update)\b", lower) and " where " not in f" {lower} ":
        issues.append({"severity": "Critical", "label": "Write query without WHERE",
                       "detail": "A DELETE or UPDATE without WHERE can affect every row. Verify this is intentional before use."})
    if not issues:
        issues.append({"severity": "Info", "label": "No static flags",
                       "detail": "A static SQL statement was found; runtime data, permissions, and FileMaker SQL support still require testing."})
    return issues


def build_sql_audit(data: dict) -> list[dict]:
    """Return one audited row per ExecuteSQL-related saved DDR step."""
    rows = []
    for script in data.get("scripts", []):
        script_name = script.get("name", "Unnamed script")
        for step in script.get("steps", []):
            if not _is_execute_sql_step(step):
                continue
            expression = step.get("text") or ""
            issues = _issues_for_expression(expression)
            rows.append({
                "script_name": script_name,
                "position": step.get("position"),
                "step_name": step.get("name", "ExecuteSQL"),
                "expression": expression,
                "issues": issues,
                "critical_count": sum(issue["severity"] == "Critical" for issue in issues),
                "warning_count": sum(issue["severity"] == "Warning" for issue in issues),
            })
    return sorted(rows, key=lambda row: (-row["critical_count"], -row["warning_count"], row["script_name"].lower(), row["position"] or 0))
