"""Loading and validation of parity object specifications."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from parity import ROOT

_OBJECT_NAME = re.compile(r"[a-zA-Z0-9_-]+")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){2}")

TOP_KEYS = {
    "object",
    "title",
    "legacy_source",
    "legacy_sha256",
    "derivation",
    "seed",
    "deploy",
    "outputs",
    "waivers",
    "questions",
}
OUTPUT_KEYS = {"name", "expected", "key", "columns", "sql", "table"}
COLUMN_KEYS = {"name", "type", "plain"}
WAIVER_KEYS = {"id", "outputs", "columns", "change", "reason", "approver_role", "status"}
QUESTION_KEYS = {"id", "output", "column", "value_map", "question", "decision_owner", "status"}


def _unknown_keys(value: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{context}: unknown key(s): {', '.join(unknown)}")


def _required(value: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - set(value))
    if missing:
        raise ValueError(f"{context}: missing required key(s): {', '.join(missing)}")


def _path(value: Any, root: Path, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}: expected a non-empty repository-relative path")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"{context}: path must stay inside the repository")
    if not path.is_file():
        raise ValueError(f"{context}: file does not exist: {value}")
    return path


def validate_spec(spec: Any, root: Path = ROOT) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("Object spec must be a JSON object")
    _unknown_keys(spec, TOP_KEYS, "Object spec")
    _required(spec, TOP_KEYS, "Object spec")

    if not isinstance(spec["object"], str) or not _OBJECT_NAME.fullmatch(spec["object"]):
        raise ValueError("Object spec: object must contain only letters, digits, '_' or '-'")
    for key in ("title", "legacy_source", "derivation"):
        if not isinstance(spec[key], str) or not spec[key]:
            raise ValueError(f"Object spec: {key} must be a non-empty string")
    if not isinstance(spec["legacy_sha256"], str) or not _SHA256.fullmatch(spec["legacy_sha256"]):
        raise ValueError("Object spec: legacy_sha256 must be a 64-character SHA-256 hex digest")
    if not isinstance(spec["seed"], str) or spec["seed"] not in {"verify", "reset"}:
        raise ValueError("Object spec: seed must be 'verify' or 'reset'")
    _path(spec["legacy_source"], root, "legacy_source")
    _path(spec["derivation"], root, "derivation")

    if not isinstance(spec["deploy"], list):
        raise ValueError("Object spec: deploy must be a list of SQL paths")
    for path in spec["deploy"]:
        _path(path, root, "deploy")
    if not isinstance(spec["outputs"], list) or not spec["outputs"]:
        raise ValueError("Object spec: outputs must be a non-empty list")

    outputs: dict[str, dict[str, Any]] = {}
    for index, output in enumerate(spec["outputs"]):
        context = f"Output {index + 1}"
        if not isinstance(output, dict):
            raise ValueError(f"{context}: must be an object")
        _unknown_keys(output, OUTPUT_KEYS, context)
        _required(output, {"name", "expected", "key", "columns"}, context)
        if not isinstance(output["name"], str) or not output["name"]:
            raise ValueError(f"{context}: name must be a non-empty string")
        if output["name"] in outputs:
            raise ValueError(f"{context}: duplicate output name {output['name']}")
        if ("sql" in output) == ("table" in output):
            raise ValueError(f"{context}: specify exactly one of sql or table")
        _path(output["expected"], root, f"{context} expected")
        if "sql" in output:
            _path(output["sql"], root, f"{context} sql")
        if "table" in output and (
            not isinstance(output["table"], str) or not _TABLE_NAME.fullmatch(output["table"])
        ):
            raise ValueError(f"{context}: table must be a fully qualified three-part identifier")
        if not isinstance(output["key"], list) or any(not isinstance(item, str) for item in output["key"]):
            raise ValueError(f"{context}: key must be a list of column names")
        if not isinstance(output["columns"], list) or not output["columns"]:
            raise ValueError(f"{context}: columns must be a non-empty list")

        column_names: list[str] = []
        for column_index, column in enumerate(output["columns"]):
            column_context = f"{context} column {column_index + 1}"
            if not isinstance(column, dict):
                raise ValueError(f"{column_context}: must be an object")
            _unknown_keys(column, COLUMN_KEYS, column_context)
            _required(column, {"name", "type"}, column_context)
            if not isinstance(column["name"], str) or not column["name"]:
                raise ValueError(f"{column_context}: name must be a non-empty string")
            if not isinstance(column["type"], str) or not column["type"]:
                raise ValueError(f"{column_context}: type must be a non-empty string")
            if "plain" in column and not isinstance(column["plain"], bool):
                raise ValueError(f"{column_context}: plain must be boolean")
            if column["name"] in column_names:
                raise ValueError(f"{context}: duplicate column {column['name']}")
            column_names.append(column["name"])
        if len(set(output["key"])) != len(output["key"]):
            raise ValueError(f"{context}: key columns must be unique")
        if not set(output["key"]).issubset(column_names):
            raise ValueError(f"{context}: key columns must be present in columns")
        outputs[output["name"]] = output

    if not isinstance(spec["waivers"], list):
        raise ValueError("Object spec: waivers must be a list")
    for index, waiver in enumerate(spec["waivers"]):
        context = f"Waiver {index + 1}"
        if not isinstance(waiver, dict):
            raise ValueError(f"{context}: must be an object")
        _unknown_keys(waiver, WAIVER_KEYS, context)
        _required(waiver, {"id", "change", "reason", "approver_role"}, context)
        for key in ("id", "change", "reason", "approver_role"):
            if not isinstance(waiver[key], str) or not waiver[key]:
                raise ValueError(f"{context}: {key} must be a non-empty string")
        if "outputs" in waiver and (
            not isinstance(waiver["outputs"], list)
            or any(name not in outputs for name in waiver["outputs"])
        ):
            raise ValueError(f"{context}: outputs must refer to known output names")
        if "columns" in waiver and (
            not isinstance(waiver["columns"], list)
            or any(not isinstance(name, str) for name in waiver["columns"])
        ):
            raise ValueError(f"{context}: columns must be a list of names")

    if not isinstance(spec["questions"], list):
        raise ValueError("Object spec: questions must be a list")
    for index, question in enumerate(spec["questions"]):
        context = f"Question {index + 1}"
        if not isinstance(question, dict):
            raise ValueError(f"{context}: must be an object")
        _unknown_keys(question, QUESTION_KEYS, context)
        _required(question, QUESTION_KEYS, context)
        for key in ("id", "output", "column", "question", "decision_owner", "status"):
            if not isinstance(question[key], str) or not question[key]:
                raise ValueError(f"{context}: {key} must be a non-empty string")
        if question["output"] not in outputs:
            raise ValueError(f"{context}: output does not name a known output")
        if question["column"] not in {
            column["name"] for column in outputs[question["output"]]["columns"]
        }:
            raise ValueError(f"{context}: column does not exist in its output")
        if not isinstance(question["value_map"], dict) or any(
            not isinstance(key, str)
            or not isinstance(value, (str, int, float, bool))
            and value is not None
            for key, value in question["value_map"].items()
        ):
            raise ValueError(f"{context}: value_map must contain only scalar values")

    return spec


def load_spec(name: str, root: Path = ROOT) -> tuple[dict[str, Any], Path]:
    if not isinstance(name, str) or not _OBJECT_NAME.fullmatch(name):
        raise ValueError("Object name must contain only letters, digits, '_' or '-'")
    path = root / "parity" / "objects" / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"Object spec does not exist: parity/objects/{name}.json")
    raw = path.read_bytes()
    try:
        spec = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON in parity/objects/{name}.json") from error
    validate_spec(spec, root)
    if spec["object"] != name:
        raise ValueError(f"Object spec name mismatch: requested {name}, found {spec['object']}")
    return spec, path
