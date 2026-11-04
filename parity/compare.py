"""Offline typed comparison and evidence fingerprint helpers."""

from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from bank_model import Column, canonical, cast, digest


def is_text(column: dict[str, Any]) -> bool:
    return column["type"].split("(")[0].upper() in {
        "CHAR",
        "VARCHAR",
        "TEXT",
        "STRING",
        "NCHAR",
        "NVARCHAR",
    }


def read_expected(path: Path, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = [column["name"] for column in columns]
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream, delimiter="|")
        header = next(reader, None)
        if header != names:
            raise ValueError(f"Expected CSV header mismatch in {path}")
        rows = []
        for line_number, values in enumerate(reader, start=2):
            if len(values) != len(columns):
                raise ValueError(f"Expected CSV field count mismatch in {path} at line {line_number}")
            rows.append(
                {
                    column["name"]: cast(value, column["type"])
                    for column, value in zip(columns, values)
                }
            )
    return rows


def _canonical(value: Any, column: dict[str, Any]) -> str | None:
    return canonical(value, Column(column["name"], column["type"], True))


def _profile(rows: list[dict[str, Any]], columns: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for column in columns:
        name = column["name"]
        declared_type = column["type"]
        values = [row[name] for row in rows if row[name] is not None]
        normalized = [_canonical(value, column) for value in values]
        numeric = declared_type.split("(")[0].upper() in {
            "INTEGER",
            "BIGINT",
            "SMALLINT",
            "BYTEINT",
            "DECIMAL",
        }
        text_is_private = is_text(column) and not column.get("plain", False)

        def extreme(fn: Any) -> str | None:
            if not values:
                return None
            value = _canonical(fn(values), column)
            return digest(value) if text_is_private and value is not None else value

        total: str | None = None
        if numeric:
            total = _canonical(sum(values, Decimal(0)), column)
        profiles[name] = {
            "count": len(values),
            "nulls": len(rows) - len(values),
            "distinct": len(set(normalized)),
            "min": extreme(min),
            "max": extreme(max),
            "sum": total,
            "max_length": max((len(value) for value in normalized if value is not None), default=0),
        }
    return profiles


def _keys_and_hashes(
    rows: list[dict[str, Any]], columns: list[dict[str, Any]], key: list[str], side: str
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    by_name = {column["name"]: column for column in columns}
    hashes: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        values = [_canonical(row[name], by_name[name]) for name in key]
        key_json = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        if key_json in hashes:
            raise ValueError(f"Duplicate comparison key in {side}")
        hashes[key_json] = digest([_canonical(row[column["name"]], column) for column in columns])
        records[key_json] = row
    return hashes, records


def _safe_value(value: Any, column: dict[str, Any]) -> str | None:
    canonical_value = _canonical(value, column)
    if canonical_value is not None and is_text(column) and not column.get("plain", False):
        return digest(canonical_value)
    return canonical_value


def _comparison(
    expected_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    key: list[str],
) -> dict[str, Any]:
    expected_profiles = _profile(expected_rows, columns)
    actual_profiles = _profile(actual_rows, columns)
    expected_hashes, expected_records = _keys_and_hashes(expected_rows, columns, key, "expected")
    actual_hashes, actual_records = _keys_and_hashes(actual_rows, columns, key, "actual")

    all_keys = set(expected_hashes) | set(actual_hashes)
    mismatches = sorted(
        item
        for item in all_keys
        if expected_hashes.get(item) != actual_hashes.get(item)
    )
    columns_differ = [
        column["name"]
        for column in columns
        if expected_profiles[column["name"]] != actual_profiles[column["name"]]
    ]
    matching = len(all_keys) - len(mismatches)
    key_columns = {column["name"]: column for column in columns}
    key_is_plain = all(not is_text(key_columns[name]) or key_columns[name].get("plain", False) for name in key)
    l4 = []
    for key_json in mismatches[:20]:
        before = expected_records.get(key_json)
        after = actual_records.get(key_json)
        differences = {}
        for column in columns:
            name = column["name"]
            old = before.get(name) if before is not None else None
            new = after.get(name) if after is not None else None
            if _canonical(old, column) != _canonical(new, column):
                differences[name] = {
                    "expected": _safe_value(old, column),
                    "actual": _safe_value(new, column),
                    "representation": "canonical"
                    if not is_text(column) or column.get("plain", False)
                    else "sha256",
                }
        sample: dict[str, Any] = {
            "expected_row_sha256": expected_hashes.get(key_json),
            "actual_row_sha256": actual_hashes.get(key_json),
            "columns": differences,
        }
        if key_is_plain:
            sample["key"] = json.loads(key_json)
        else:
            sample["key_sha256"] = hashlib.sha256(key_json.encode("utf-8")).hexdigest()
        l4.append(sample)

    l1_match = len(expected_rows) == len(actual_rows)
    l2_match = not columns_differ
    l3_percent = round(100 * matching / len(all_keys), 6) if all_keys else 100.0
    l3_match = not mismatches
    green = l1_match and l2_match and l3_match
    return {
        "status": "green" if green else "red",
        "L1": {"expected": len(expected_rows), "actual": len(actual_rows), "match": l1_match},
        "L2": {
            "match": l2_match,
            "mismatching_columns": columns_differ,
            "expected": expected_profiles,
            "actual": actual_profiles,
        },
        "L3": {
            "keys": len(all_keys),
            "matching": matching,
            "match_percent": l3_percent,
            "vacuous": not all_keys,
            "match": l3_match,
            "expected_sha256": digest(sorted(expected_hashes.items())),
            "actual_sha256": digest(sorted(actual_hashes.items())),
        },
        "L4": l4,
    }


def compare_rows(
    expected_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    key: list[str],
) -> dict[str, Any]:
    try:
        return _comparison(expected_rows, actual_rows, columns, key)
    except ValueError as error:
        message = str(error)
        if not message.startswith("Duplicate comparison key in "):
            message = "Comparison failed: ValueError"
        return {
            "status": "red",
            "error": message,
            "L1": {
                "expected": len(expected_rows),
                "actual": len(actual_rows),
                "match": len(expected_rows) == len(actual_rows),
            },
            "L2": {"match": False, "mismatching_columns": [], "expected": {}, "actual": {}},
            "L3": {
                "keys": 0,
                "matching": 0,
                "match_percent": 0.0,
                "vacuous": False,
                "match": False,
                "expected_sha256": None,
                "actual_sha256": None,
            },
            "L4": [],
        }


def apply_value_maps(
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name = {column["name"]: column for column in columns}
    result = [dict(row) for row in rows]
    for question in questions:
        column = by_name[question["column"]]
        mapping = {}
        for expected_value, actual_value in question["value_map"].items():
            before = cast(expected_value, column["type"])
            after = None if actual_value is None else cast(str(actual_value), column["type"])
            mapping[_canonical(before, column)] = after
        for row in result:
            before_canonical = _canonical(row[column["name"]], column)
            if before_canonical in mapping:
                row[column["name"]] = mapping[before_canonical]
    return result
