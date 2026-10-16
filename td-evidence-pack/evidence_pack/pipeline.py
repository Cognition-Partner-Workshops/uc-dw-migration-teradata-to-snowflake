"""Dual-run orchestration: legacy vs one converted candidate -> evidence results."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from dataclasses import asdict
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

import duckdb
import sqlglot

from . import __version__
from .data import as_tuples, generate
from .engines import EngineError, SnowflakeEmulator, TeradataEmulator
from .lineage import compare as compare_lineage
from .lineage import view_lineage
from .reconcile import ERROR, FAIL, PASS, WAIVED, ObjectReport, Waiver, reconcile
from .schema import compare_tables
from .sources import SourceSet

BCBS239 = [
    ("P2", "Data architecture & IT infrastructure", "Column-level lineage captured for every report column on both "
     "platforms and compared for parity."),
    ("P3", "Accuracy & integrity", "Order-independent SHA-256 fingerprints, per-column null/distinct counts and "
     "control totals reconciled for every table."),
    ("P4", "Completeness", "Row counts reconciled; every missing or unexpected row is counted by business key."),
    ("P5", "Timeliness", "Business date pinned for both runs; run timestamps and durations recorded."),
    ("P6", "Adaptability", "Fully reproducible: inputs, data seed, tool and engine versions hashed in the manifest."),
    ("P7", "Accuracy of risk reports", "Each regulatory view reconciled row-by-row plus critical-data-element "
     "control totals by reporting category."),
    ("P8", "Comprehensiveness", "Coverage statement lists every object in scope and anything excluded."),
]


def load_controls(path: Path | None) -> dict[str, Any]:
    if path is None:
        return json.loads(resources.files("evidence_pack").joinpath("controls.json").read_text())
    return json.loads(path.read_text())


def sha256(text: str | bytes) -> str:
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def _ordered(files: dict[str, str]) -> list[tuple[str, str]]:
    """Tables first, then views, so dependencies exist before views are created."""
    return sorted(files.items(), key=lambda kv: (0 if "table" in kv[0].lower() else 1, kv[0]))


def run_candidate(
    legacy_src: SourceSet,
    candidate: SourceSet,
    seed_dir: Path,
    as_of: date,
    controls: dict[str, Any],
    seed: int = 239,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    legacy, target = TeradataEmulator(as_of), SnowflakeEmulator(as_of)
    load_errors: dict[str, str] = {}

    for _rel, sql in _ordered(legacy_src.files):
        legacy.load_script(sql)
    for rel, sql in _ordered(candidate.files):
        try:
            target.load_script(sql)
        except EngineError as e:
            load_errors[rel] = str(e)

    data = generate(seed_dir, legacy.tables, as_of, seed=seed)
    for name, rows in data.items():
        cols, tuples = as_tuples(rows, legacy.tables[name])
        legacy.insert_rows(name, cols, tuples)
        if name in target.tables:
            tcols = [c.name for c in target.tables[name].columns]
            keep = [i for i, c in enumerate(cols) if c in tcols]
            target.insert_rows(name, [cols[i] for i in keep], [tuple(r[i] for i in keep) for r in tuples])

    waivers = [Waiver(**w) for w in controls.get("waivers", [])]
    reports: list[ObjectReport] = []
    schema: dict[str, list[dict[str, object]]] = {}
    lineage: dict[str, list[dict[str, object]]] = {}
    for name, obj in legacy.objects.items():
        kind = obj.kind
        if kind == "TABLE":
            schema[name] = compare_tables(legacy.tables[name], target.tables.get(name))
        if name not in target.objects:
            reports.append(ObjectReport(kind=kind, name=name, status=ERROR,
                                        error="object not produced (or failed to load) in the converted output"))
            continue
        try:
            lres = legacy.query(f"SELECT * FROM {name}")
            tres = target.query(f"SELECT * FROM {name}")
        except duckdb.Error as e:
            reports.append(ObjectReport(kind=kind, name=name, status=ERROR, error=f"query failed: {e}"))
            continue
        rep = reconcile(kind, name, lres, tres, key=controls.get("keys", {}).get(name),
                        waivers=waivers, controls=controls.get("critical_data_elements", {}).get(name))
        rep.assumptions = sorted(n for n in legacy.notes.get(name, ()) if "confirm" in n)
        if kind == "VIEW":
            try:
                lineage[name] = compare_lineage(view_lineage(obj.executed_sql),
                                                view_lineage(target.objects[name].executed_sql))
            except Exception as e:  # noqa: BLE001 - lineage failures are reported, not fatal
                lineage[name] = [{"column": "*", "legacy": [], "target": [], "match": False, "error": str(e)}]
            broken = [r["column"] for r in lineage[name] if not r["match"]]
            if broken:
                rep.findings.append(f"Lineage review needed (advisory) for {', '.join(map(str, broken))}")
        reports.append(rep)

    schema_breaks = sum(1 for cols in schema.values() for c in cols if not c["ok"])
    statuses = [r.status for r in reports]
    verdict = (FAIL if (FAIL in statuses or ERROR in statuses or load_errors) else
               WAIVED if WAIVED in statuses else PASS)
    finished = datetime.now(timezone.utc)

    inputs = {f"legacy/{k}": sha256(v) for k, v in legacy_src.files.items()}
    inputs |= {f"candidate/{k}": sha256(v) for k, v in candidate.files.items()}
    inputs |= {f"seed/{p.name}": sha256(p.read_bytes()) for p in sorted(seed_dir.glob("*.csv"))}
    outputs = {r.name: {"legacy": r.legacy_fingerprint, "target": r.target_fingerprint} for r in reports}

    result: dict[str, Any] = {
        "candidate": {"name": candidate.name, "origin": candidate.origin},
        "legacy": {"origin": legacy_src.origin},
        "verdict": verdict,
        "as_of": as_of.isoformat(),
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": finished.isoformat(timespec="seconds"),
        "duration_s": round(time.perf_counter() - t0, 2),
        "counts": {s: statuses.count(s) for s in (PASS, WAIVED, FAIL, ERROR)},
        "schema_breaks": schema_breaks,
        "objects": [asdict(r) for r in reports],
        "schema": schema,
        "lineage": lineage,
        "load_errors": load_errors,
        "waivers": [asdict(w) for w in waivers],
        "disclosures": {
            "legacy": sorted({n for ns in legacy.notes.values() for n in ns}),
            "target": sorted({n for ns in target.notes.values() for n in ns}),
        },
        "coverage": {
            "in_scope": sorted(legacy.objects),
            "out_of_scope": "Macros, stored procedures and BTEQ scripts (procedural; need execution harness).",
            "rows_loaded": {k: len(v) for k, v in data.items()},
        },
        "bcbs239": BCBS239,
        "manifest": {
            "tool": f"td-evidence-pack {__version__}",
            "engines": {"duckdb": duckdb.__version__, "sqlglot": sqlglot.__version__,
                        "python": platform.python_version()},
            "data_seed": seed,
            "inputs": inputs,
            "outputs": outputs,
        },
    }
    result["manifest"]["manifest_sha256"] = sha256(json.dumps(result["manifest"], sort_keys=True))
    return result
