"""Reviewer checklist: what a person must verify, complete, test and prepare for each converted object."""

from __future__ import annotations

import re

from .models import ChecklistItem, Conversion, SourceObject

TARGET = {"bigquery": "BigQuery", "redshift": "Redshift", "synapse": "Synapse"}


def needs_review(conv: Conversion) -> bool:
    return conv.status != "converted"


def build_checklist(obj: SourceObject, conv: Conversion) -> list[ChecklistItem]:
    if not needs_review(conv):
        return []
    tgt = TARGET.get(conv.target, conv.target)
    items: list[tuple[str, str]] = []
    rules = " ".join(conv.rules)
    sql = conv.sql

    for m in re.findall(r"^-- MANUAL REVIEW: (.+)$", sql, re.MULTILINE):
        items.append(("complete", f"Finish by hand: {m}"))
    if conv.status == "unsupported" and conv.reason:
        items.append(("complete", f"Rewrite this object by hand: {conv.reason}"))
    if "TODO (manual)" in sql:
        items.append(("complete", "Replace every '-- TODO (manual)' block in the generated SQL"))

    for w in conv.warnings:
        if not w.startswith("Uses objects that are not in the configuration dump"):
            items.append(("verify", f"Accept or fix: {w}"))
    if conv.rules:
        items.append(("verify", f"Confirm the {len(conv.rules)} automatic rewrite(s) listed under Rules applied are right for {tgt}"))

    if "CSUM" in rules or "MAVG" in rules or "MSUM" in rules:
        items += [
            ("verify", "Running totals / moving averages: confirm PARTITION BY matches the Teradata GROUP BY reset"),
            ("verify", "Running totals / moving averages: confirm the ORDER BY column and the window frame (ROWS BETWEEN ...)"),
        ]
    if "HASHROW" in rules:
        items.append(("verify", "Hash values differ from Teradata: confirm nothing compares them with Teradata-generated hashes"))
    if obj.object_type == "macro":
        items += [
            ("verify", "Parameters: confirm the defaults (pass NULL to use them) and the invocation in the Usage line"),
            ("verify", "Result sets: confirm callers read every result set in the same order and shape"),
        ]
        if "SAMPLE" in rules:
            items.append(("verify", "SAMPLE became LIMIT: confirm a deterministic subset is acceptable instead of a random one"))
    if obj.object_type == "procedure":
        items += [
            ("verify", "IN/OUT parameters: confirm types and that OUT values (row counts, return code) reach the caller"),
            ("verify", "Error handling: confirm the exception block logs and returns the same way as the Teradata EXIT HANDLER"),
        ]
        if "temporary table" in rules:
            items.append(("verify", "Temporary tables: confirm their lifetime and that names do not clash between sessions"))
        if "COLLECT STATISTICS" in rules:
            items.append(("verify", f"Statistics: confirm the {tgt} statistics statement (or its removal) is acceptable"))
        items.append(("verify", "Transactions: Teradata committed each statement; confirm the target commit / rollback behaviour"))
    if obj.object_type == "bteq_script":
        items += [
            ("complete", "Schedule the generated procedure in your orchestrator, with the same run order and retries"),
            ("verify", "Branching: confirm each .IF / .GOTO / .LABEL path does the same steps as the BTEQ script"),
            ("verify", "Exit codes: map the old .QUIT codes (0 / 4 / 8) to orchestrator success / warning / failure"),
        ]
        if ".EXPORT" in rules:
            items.append(("complete", "Exports: set the bucket / storage placeholders and confirm file names, delimiter and headers"))
        if "CALL" in rules or "EXEC" in rules:
            items.append(("verify", "Called procedures / macros: deploy them first and confirm the argument order"))

    missing = next((w for w in conv.warnings if w.startswith("Uses objects that are not in the configuration dump")), None)
    if missing:
        objs = missing.split(": ", 1)[1].split(";")[0]
        items.append(("deploy", f"Create or map the objects that are not in the dump: {objs}"))
    if obj.object_type in ("macro", "procedure", "bteq_script"):
        items.append(("deploy", "Credentials and connections are configured in the target / orchestrator, not in the SQL"))

    if obj.object_type in ("macro", "procedure", "bteq_script"):
        items.append(("test", f"Run it on {tgt} with the same inputs as on Teradata and compare row counts and output values"))
    else:
        items.append(("test", f"Run the SQL on {tgt} and compare row counts and a sample of rows with Teradata"))
    if obj.object_type == "table":
        items.append(("test", "Load a sample and check nulls, dates, decimals and text lengths survived the type mapping"))

    seen: set[str] = set()
    out = []
    for cat, text in items:
        if text not in seen:
            seen.add(text)
            out.append(ChecklistItem(category=cat, text=text))  # type: ignore[arg-type]
    rank = {"complete": 0, "verify": 1, "deploy": 2, "test": 3}
    return sorted(out, key=lambda i: rank[i.category])


def checklist_header(items: list[ChecklistItem]) -> str:
    if not items:
        return ""
    return "-- REVIEW REQUIRED - what to check before running:\n" + "".join(f"--   [ ] {i.category.upper()}: {i.text}\n" for i in items)
