"""Snowflake execution and evidence orchestration for parity runs."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from bank_model import AS_OF, ROOT
import load_seed
from parity import compare
from parity.report import write_object_report, write_smoke_report
from parity.spec import load_spec

_LABEL = re.compile(r"[a-zA-Z0-9_-]+")


class AsOfError(ValueError):
    """Requested business date differs from the frozen comparison date."""


def validate_label(label: str) -> None:
    if not _LABEL.fullmatch(label):
        raise ValueError("Invalid evidence label; use letters, digits, '_' or '-'")


def _validate_as_of(as_of: str, manifest: dict[str, Any]) -> None:
    try:
        requested = date.fromisoformat(as_of)
    except ValueError as error:
        raise AsOfError(f"Invalid --as-of; expected {AS_OF.isoformat()}") from error
    if requested != AS_OF or manifest.get("as_of_date") != AS_OF.isoformat() or as_of != AS_OF.isoformat():
        raise AsOfError(
            f"Invalid --as-of {as_of}; bank_model and the frozen manifest require {AS_OF.isoformat()}"
        )


def _commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _error(error: Exception) -> dict[str, Any]:
    return {
        "type": type(error).__name__,
        "errno": getattr(error, "errno", None),
        "sfqid": getattr(error, "sfqid", None),
    }


def _query_id(cursor: Any) -> str | None:
    return getattr(cursor, "sfqid", None)


def _configure(connection: Any, as_of: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("USE WAREHOUSE WH_TD_BANKING")
        cursor.execute("USE SCHEMA BANKING_DW.BANKING_DW")
        cursor.execute(f"SET AS_OF_DATE = '{as_of}'::DATE")


def _seed_summary(seed_report: dict[str, Any], good: bool) -> dict[str, Any]:
    tables = {}
    for name, result in seed_report.get("tables", {}).items():
        tables[name] = {
            "status": result.get("status", "red"),
            "L1": result.get("L1"),
            "L2": {"match": result.get("L2", {}).get("match", False)},
            "L3": {
                "keys": result.get("L3", {}).get("keys"),
                "matching": result.get("L3", {}).get("matching"),
                "match_percent": result.get("L3", {}).get("match_percent"),
                "vacuous": result.get("L3", {}).get("match_percent") == 100.0
                and result.get("L1", {}).get("expected") == 0
                and result.get("L1", {}).get("actual") == 0,
            },
            "query_id": result.get("select_query_id"),
        }
    return {
        "status": "green" if good else "red",
        "manifest_sha256": seed_report.get("manifest_sha256"),
        "supplied_role_verified": seed_report.get("supplied_role_verified"),
        "schema_contract_errors": seed_report.get("schema_contract_errors", []),
        "documented_count_gate": seed_report.get("documented_count_gate", {}),
        "tables": tables,
        "views": {
            name: {
                "rows": view.get("rows"),
                "query_id": view.get("query_id"),
                "semantic_parity": "read only, semantic parity not certified",
            }
            for name, view in seed_report.get("views", {}).items()
        },
    }


def _open_question(question: dict[str, Any]) -> bool:
    return question["status"].casefold() in {"open", "pending", "unresolved"}


def _question_result(question: dict[str, Any], status: str, residual: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "id": question["id"],
        "output": question["output"],
        "column": question["column"],
        "value_map": question["value_map"],
        "question": question["question"],
        "decision_owner": question["decision_owner"],
        "spec_status": question["status"],
        "status": status,
    }
    if residual is not None:
        result["residual"] = residual
    return result


def _schema_failure(expected_count: int, actual_count: int, actual_columns: list[str]) -> dict[str, Any]:
    return {
        "status": "red",
        "schema_error": f"Expected columns in spec order; received: {actual_columns}",
        "L1": {
            "expected": expected_count,
            "actual": actual_count,
            "match": expected_count == actual_count,
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


def _column_names(description: Any) -> list[str]:
    names = []
    for column in description or []:
        name = getattr(column, "name", None)
        if name is None:
            name = column[0]
        names.append(str(name).upper())
    return names


def _run_output(connection: Any, output: dict[str, Any], root: Path) -> dict[str, Any]:
    expected_rows = compare.read_expected(root / output["expected"], output["columns"])
    query = (
        (root / output["sql"]).read_text(encoding="utf-8")
        if "sql" in output
        else f"SELECT * FROM {output['table']}"
    )
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        query_id = _query_id(cursor)
        names = _column_names(cursor.description)
        rows = cursor.fetchall()
        expected_names = [column["name"] for column in output["columns"]]
        if names != expected_names:
            result = _schema_failure(len(expected_rows), len(rows), names)
            result["query_id"] = query_id
            return result
        actual_rows = [
            dict(zip(expected_names, values))
            for values in rows
        ]
        result = compare.compare_rows(expected_rows, actual_rows, output["columns"], output["key"])
        result["query_id"] = query_id
        applicable = [q for q in output.get("questions", []) if _open_question(q)]
        if result["status"] == "green":
            result["questions"] = [
                _question_result(question, "not observed")
                for question in output.get("questions", [])
            ]
        elif applicable:
            residual_expected = compare.apply_value_maps(expected_rows, output["columns"], applicable)
            residual = compare.compare_rows(residual_expected, actual_rows, output["columns"], output["key"])
            result["residual"] = residual
            if residual["status"] == "green":
                result["status"] = "amber"
                result["questions"] = [
                    _question_result(question, "explains residual", residual)
                    for question in applicable
                ]
            else:
                result["questions"] = [
                    _question_result(question, "does not explain residual")
                    for question in applicable
                ]
        else:
            result["questions"] = []
        return result
    finally:
        cursor.close()


def run_object(
    object_name: str,
    as_of: str,
    label: str = "run",
    reset_seed: bool = False,
    root: Path = ROOT,
) -> tuple[dict[str, Any], int]:
    logging.disable(logging.CRITICAL)
    validate_label(label)
    spec, spec_path = load_spec(object_name, root)
    spec_digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    report: dict[str, Any] = {
        "spec": spec,
        "spec_sha256": spec_digest,
        "label": label,
        "as_of": as_of,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(),
        "legacy_sha256": {},
        "precheck": None,
        "deploy_errors": [],
        "outputs": [],
        "reset_seed": reset_seed or spec["seed"] == "reset",
    }
    manifest = load_seed.verify_manifest()
    _validate_as_of(as_of, manifest)
    legacy_digest = hashlib.sha256((root / spec["legacy_source"]).read_bytes()).hexdigest()
    report["legacy_sha256"] = {
        "expected": spec["legacy_sha256"],
        "actual": legacy_digest,
        "match": legacy_digest == spec["legacy_sha256"].lower(),
    }

    connection = None
    try:
        os.environ.setdefault("DEVIN_SESSION_URL", os.environ.get("DEVIN_SESSION_URL", ""))
        connection = load_seed.connect()
        try:
            _configure(connection, as_of)
        except Exception as error:
            report["session_error"] = _error(error)

        reset_error = None
        if report["reset_seed"]:
            try:
                load_seed.reset(connection, manifest)
                _configure(connection, as_of)
            except Exception as error:
                reset_error = _error(error)

        try:
            seed_report, seed_good = load_seed.verify(connection, manifest)
            report["precheck"] = _seed_summary(seed_report, seed_good)
            if reset_error:
                report["precheck"]["status"] = "red"
                report["precheck"]["reset_error"] = reset_error
        except Exception as error:
            report["precheck"] = {"status": "red", "error": _error(error)}
            if reset_error:
                report["precheck"]["reset_error"] = reset_error

        for path in spec["deploy"]:
            try:
                load_seed.execute_ddl(connection, root / path)
            except Exception as error:
                report["deploy_errors"].append({"path": path, "error": _error(error)})

        for output in spec["outputs"]:
            entry: dict[str, Any] = {"name": output["name"], "key": output["key"]}
            try:
                output_questions = [
                    question for question in spec["questions"] if question["output"] == output["name"]
                ]
                result = _run_output(connection, dict(output, questions=output_questions), root)
                entry.update(result)
                entry["status"] = result["status"]
            except Exception as error:
                safe_error = _error(error)
                entry.update(
                    {
                        "status": "red",
                        "error": safe_error,
                        "query_id": safe_error["sfqid"],
                        "L1": {"expected": None, "actual": None, "match": False},
                        "L2": {"match": False, "mismatching_columns": []},
                        "L3": {"match_percent": 0.0, "match": False, "vacuous": False},
                        "L4": [],
                        "questions": [],
                    }
                )
            report["outputs"].append(entry)
    except Exception as error:
        report["run_error"] = _error(error)
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    red = (
        report.get("run_error") is not None
        or report.get("session_error") is not None
        or report.get("legacy_sha256", {}).get("match") is False
        or (report.get("precheck") or {}).get("status") != "green"
        or bool(report["deploy_errors"])
        or any(output["status"] == "red" for output in report["outputs"])
    )
    amber = any(output["status"] == "amber" for output in report["outputs"])
    report["status"] = "red" if red else "amber" if amber else "green"
    write_object_report(root, report)
    errors = [
        failure_info
        for failure_info in (
            report.get("run_error"),
            report.get("session_error"),
            *(output.get("error") for output in report["outputs"]),
        )
        if failure_info
    ]
    if errors:
        failure_info = errors[0]
        print(
            f"Parity run failed: {failure_info['type']}; errno={failure_info['errno']}; "
            f"query_id={failure_info['sfqid']}. No credentials or raw errors logged."
        )
    return report, {"green": 0, "amber": 2, "red": 1}[report["status"]]


def smoke(as_of: str, label: str = "smoke") -> tuple[dict[str, Any], int]:
    logging.disable(logging.CRITICAL)
    validate_label(label)
    report: dict[str, Any] = {
        "label": label,
        "as_of": as_of,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(),
        "precheck": None,
    }
    connection = None
    try:
        manifest = load_seed.verify_manifest()
        _validate_as_of(as_of, manifest)
        os.environ.setdefault("DEVIN_SESSION_URL", os.environ.get("DEVIN_SESSION_URL", ""))
        connection = load_seed.connect()
        _configure(connection, as_of)
        seed_report, good = load_seed.verify(connection, manifest)
        report["precheck"] = _seed_summary(seed_report, good)
        report["status"] = "green" if good else "red"
    except AsOfError:
        raise
    except Exception as error:
        report["error"] = _error(error)
        report["status"] = "red"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    if report.get("error"):
        failure_info = report["error"]
        print(
            f"Parity smoke failed: {failure_info['type']}; errno={failure_info['errno']}; "
            f"query_id={failure_info['sfqid']}. No credentials or raw errors logged."
        )
    write_smoke_report(ROOT, report)
    return report, 0 if report["status"] == "green" else 1
