"""Data dump analyser: file formats, delimiters, headers, table-file mapping and per-column validation."""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any

import pyarrow.parquet as pq
import yaml

from .ingest import UploadedFile, decode, detect_data, read_bytes
from .models import (
    ColumnCheck,
    ColumnMeta,
    DataFileAnalysis,
    DataOptions,
    InputFile,
    TableDataReadiness,
    TableMeta,
    TdBaseType,
)
from .td_catalog import CHAR_TYPES, INTEGER_TYPES

T = TdBaseType
_INT_RANGE = {T.BYTEINT: 2**7, T.SMALLINT: 2**15, T.INTEGER: 2**31, T.BIGINT: 2**63}
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%d/%m/%Y", "%d.%m.%Y")
_TS_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")
MAX_SAMPLES = 3


@dataclass
class ParsedFile:
    analysis: DataFileAnalysis
    rows: list[list[Any]] = field(default_factory=list)


@dataclass
class ManifestEntry:
    table: str
    file: str
    delimiter: str | None = None
    header: bool | None = None


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _stem(path: str) -> str:
    name = PurePosixPath(path).name.lower()
    name = re.sub(r"(\.gz|\.zip)$", "", name)
    name = re.sub(r"\.\w+$", "", name)
    name = re.sub(r"([_.-](part|p|chunk|file)?[_.-]?\d+|[_.-](sample|extract|export|data|full|delta|\d{8}))+$", "", name)
    return name.upper()


def parse_manifest(f: UploadedFile) -> list[ManifestEntry]:
    """CSV (table,file[,delimiter,header]) / JSON / YAML: {tables: [{table, files|file, delimiter, header}]}."""
    text = decode(read_bytes(f)).lstrip("\ufeff")
    if f.suffix in (".json", ".yaml", ".yml"):
        doc = json.loads(text) if f.suffix == ".json" else yaml.safe_load(text)
        items = doc.get("tables", doc.get("files", [])) if isinstance(doc, dict) else doc
        if isinstance(items, dict):
            items = [{"table": k, **(v if isinstance(v, dict) else {"files": v})} for k, v in items.items()]
        rows = []
        for it in items or []:
            files = it.get("files") or [it.get("file")]
            for fl in files if isinstance(files, list) else [files]:
                if isinstance(fl, dict):
                    rows.append({**{k: v for k, v in it.items() if k != "files"}, **fl})
                elif fl:
                    rows.append({**it, "file": fl})
    else:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",|;\t")
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    out = []
    for r in rows:
        r = {str(k).strip().lower(): v for k, v in r.items()}
        table = r.get("table") or r.get("table_name") or r.get("target_table")
        file = r.get("file") or r.get("file_name") or r.get("path")
        if not table or not file:
            continue
        hdr = r.get("header")
        out.append(
            ManifestEntry(
                table=str(table).strip(),
                file=str(file).strip(),
                delimiter={"\\t": "\t", "tab": "\t", "pipe": "|", "comma": ","}.get(
                    str(r.get("delimiter") or ""), r.get("delimiter") or None
                ),
                header=None if hdr in (None, "") else str(hdr).strip().lower() in ("1", "true", "yes", "y"),
            )
        )
    return out


def _sniff(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",|\t;").delimiter
    except csv.Error:
        counts = {d: sample.splitlines()[0].count(d) for d in ",|\t;"} if sample else {}
        return max(counts, key=counts.get) if counts and max(counts.values()) else ","


def read_data_file(f: UploadedFile, opts: DataOptions, table: TableMeta | None = None, entry: ManifestEntry | None = None) -> ParsedFile:
    fmt = detect_data(f, opts.data_format)
    a = DataFileAnalysis(path=f.path, format="unknown", compressed=f.name.lower().endswith(".gz"))
    if fmt == "parquet":
        tbl = pq.read_table(io.BytesIO(f.data))
        a.format, a.columns = "parquet", [c.upper() for c in tbl.column_names]
        a.row_count, a.column_count, a.has_header = tbl.num_rows, tbl.num_columns, True
        cols = [tbl.column(i).to_pylist() for i in range(tbl.num_columns)]
        rows = [list(r) for r in zip(*cols, strict=True)] if cols else []
        return ParsedFile(a, rows)
    if fmt != "delimited":
        a.issues.append(f"Unrecognised data file format ({f.suffix or 'no extension'})")
        return ParsedFile(a)
    text = decode(read_bytes(f), opts.encoding).lstrip("\ufeff")
    a.format, a.encoding = "delimited", opts.encoding
    delim = (entry.delimiter if entry and entry.delimiter else None) or (
        opts.delimiter if opts.delimiter != "auto" else _sniff(text[:8192])
    )
    a.delimiter = delim
    raw = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if r and any(x.strip() for x in r)]
    if not raw:
        a.issues.append("File is empty")
        return ParsedFile(a)
    first = [x.strip().upper() for x in raw[0]]
    if entry and entry.header is not None:
        has_header = entry.header
    elif opts.header != "auto":
        has_header = opts.header == "yes"
    elif table:
        names = {c.name for c in table.columns}
        has_header = sum(x in names for x in first) >= max(1, len(first) // 2)
    else:
        try:
            has_header = csv.Sniffer().has_header(text[:8192])
        except csv.Error:
            has_header = all(re.fullmatch(r"[A-Z_][A-Z0-9_ ]*", x) for x in first)
    a.has_header = has_header
    body = raw[1:] if has_header else raw
    width = len(raw[0])
    a.columns = first if has_header else [f"COL{i + 1}" for i in range(width)]
    a.column_count, a.row_count = width, len(body)
    a.ragged_rows = sum(len(r) != width for r in body)
    if a.ragged_rows:
        a.issues.append(f"{a.ragged_rows} row(s) have a different number of fields than the header ({width})")
    nul = opts.empty_as_null
    rows = [[(None if nul and v == "" else v) for v in r] for r in body]
    return ParsedFile(a, rows)


def match_table(path: str, columns: list[str], tables: dict[str, TableMeta]) -> tuple[str | None, str, float]:
    stem = _norm(_stem(path))
    by_name = {_norm(t.name): tid for tid, t in tables.items()}
    if stem in by_name:
        return by_name[stem], "name", 1.0
    best, score = None, 0.0
    for key, tid in by_name.items():
        r = difflib.SequenceMatcher(None, stem, key).ratio()
        if key in stem or stem in key:
            r = max(r, 0.85)
        if columns:
            overlap = len(set(columns) & {c.name for c in tables[tid].columns}) / max(len(columns), 1)
            r = max(r, overlap * 0.9) if overlap > 0.6 else r
        if r > score:
            best, score = tid, r
    return (best, "fuzzy", round(score, 2)) if score >= 0.6 else (None, "none", round(score, 2))


def _parse_value(v: Any, c: ColumnMeta) -> tuple[Any, str | None]:
    """Value -> python value of the column type, or (None, error)."""
    if isinstance(v, str):
        v = v.strip() if c.base_type not in CHAR_TYPES else v
    b = c.base_type
    try:
        if b in INTEGER_TYPES:
            n = int(Decimal(str(v)))
            if Decimal(str(v)) != n:
                return None, "not an integer"
            if not -_INT_RANGE[b] <= n < _INT_RANGE[b]:
                return None, f"out of {b.value} range"
            return n, None
        if b in (T.DECIMAL, T.NUMBER):
            d = Decimal(str(v).replace(",", "") if isinstance(v, str) else str(v))
            if c.precision is not None:
                s = c.scale or 0
                if d.as_tuple().exponent < -s and d != d.quantize(Decimal(1).scaleb(-s)):
                    return None, f"more than {s} decimal places"
                if abs(d) >= Decimal(10) ** (c.precision - s):
                    return None, f"exceeds DECIMAL({c.precision},{s})"
            return d, None
        if b == T.FLOAT:
            return float(v), None
        if b == T.DATE:
            if isinstance(v, date):
                return v if not isinstance(v, datetime) else v.date(), None
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(v, fmt).date(), None
                except ValueError:
                    pass
            return None, "not a date"
        if b in (T.TIMESTAMP, T.TIMESTAMP_TZ):
            if isinstance(v, datetime):
                return v, None
            if isinstance(v, date):
                return datetime(v.year, v.month, v.day), None
            for fmt in _TS_FORMATS:
                try:
                    return datetime.strptime(v, fmt), None
                except ValueError:
                    pass
            return None, "not a timestamp"
        if b in (T.TIME, T.TIME_TZ):
            return v if isinstance(v, time) else time.fromisoformat(v), None
        s = v if isinstance(v, str) else str(v)
        if c.length and b in CHAR_TYPES and len(s.rstrip() if b == T.CHAR else s) > c.length:
            return None, f"longer than {c.length}"
        return s, None
    except (InvalidOperation, ValueError, TypeError):
        return None, f"not a valid {b.value}"


@dataclass
class TablePlan:
    """How file columns map onto a table, and the validated rows ready to load."""

    readiness: TableDataReadiness
    load_columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)


def validate_table(tid: str, table: TableMeta, files: list[ParsedFile]) -> TablePlan:
    r = TableDataReadiness(table_id=tid, files=[p.analysis.path for p in files], status="ready")
    if not files:
        r.status = "no_data"
        return TablePlan(r)
    first = files[0].analysis
    names = [c.name for c in table.columns]
    if first.has_header:
        file_cols = first.columns
    elif first.column_count == len(names):
        file_cols = names
        r.issues.append("No header: columns mapped by position")
    else:
        file_cols = names[: first.column_count]
        r.issues.append(
            f"No header and {first.column_count} fields vs {len(names)} columns: mapped by position to the first {first.column_count}"
        )
    for p in files[1:]:
        if p.analysis.has_header and p.analysis.columns != file_cols:
            r.issues.append(f"{p.analysis.path}: header differs from {first.path}")
    pos = {c: i for i, c in enumerate(file_cols)}
    r.unmapped_file_columns = [c for c in file_cols if c not in names]
    checks: list[ColumnCheck] = []
    load_cols: list[tuple[ColumnMeta, int]] = []
    for c in table.columns:
        if c.name in pos:
            checks.append(ColumnCheck(column=c.name, source="file", file_column=c.name))
            load_cols.append((c, pos[c.name]))
        elif c.identity:
            checks.append(ColumnCheck(column=c.name, source="identity"))
        elif c.default is not None:
            checks.append(ColumnCheck(column=c.name, source="default"))
        elif c.nullable:
            checks.append(ColumnCheck(column=c.name, source="null"))
        else:
            checks.append(ColumnCheck(column=c.name, source="missing"))
    missing = [ch.column for ch in checks if ch.source == "missing"]
    if missing:
        r.issues.append(f"NOT NULL column(s) without default missing from file: {', '.join(missing)}")
    if r.unmapped_file_columns:
        r.issues.append(f"File column(s) not in table (ignored): {', '.join(r.unmapped_file_columns)}")
    by_name = {ch.column: ch for ch in checks}
    good_rows: list[list[Any]] = []
    seen: set[tuple] = set()
    for p in files:
        for raw in p.rows:
            r.total_rows += 1
            out, bad = [], bool(missing)
            for c, i in load_cols:
                v = raw[i] if i < len(raw) else None
                ch = by_name[c.name]
                if v is None:
                    if not c.nullable and c.default is None:
                        ch.null_violations += 1
                        bad = True
                    out.append(None)
                    continue
                val, err = _parse_value(v, c)
                if err:
                    bad = True
                    if "longer" in err:
                        ch.length_violations += 1
                    else:
                        ch.parse_errors += 1
                    if len(ch.samples) < MAX_SAMPLES:
                        ch.samples.append(f"{str(v)[:40]!r}: {err}")
                out.append(val)
            if bad:
                r.rejected_rows += 1
                continue
            if table.kind == "SET":
                key = tuple(out)
                if key in seen:
                    r.duplicate_rows += 1
                    continue
                seen.add(key)
            good_rows.append(out)
    r.columns = checks
    for ch in checks:
        if ch.parse_errors or ch.null_violations or ch.length_violations:
            r.issues.append(
                f"{ch.column}: {ch.parse_errors} parse error(s), {ch.null_violations} NULL in NOT NULL, {ch.length_violations} too long"
            )
    if r.duplicate_rows:
        r.issues.append(f"{r.duplicate_rows} duplicate row(s) removed (SET table semantics)")
    if missing or (r.total_rows and r.rejected_rows == r.total_rows):
        r.status = "blocked"
    elif r.issues:
        r.status = "ready_with_warnings"
    return TablePlan(r, [c.name for c, _ in load_cols], good_rows)


def analyse_data(
    files: list[UploadedFile], tables: dict[str, TableMeta], opts: DataOptions, overrides: dict[str, str] | None = None
) -> tuple[list[InputFile], list[DataFileAnalysis], dict[str, TablePlan], str | None, list[str]]:
    overrides = overrides or {}
    msgs: list[str] = []
    inputs: list[InputFile] = []
    manifest: list[ManifestEntry] = []
    manifest_path = None
    data_files: list[UploadedFile] = []
    for f in files:
        fmt = detect_data(f, opts.data_format)
        if fmt == "manifest":
            try:
                manifest += parse_manifest(f)
                manifest_path = f.path
                inputs.append(
                    InputFile(path=f.path, size=len(f.data), kind="data", detected_format="manifest", note=f"{len(manifest)} mapping(s)")
                )
            except Exception as exc:  # noqa: BLE001
                msgs.append(f"{f.path}: manifest could not be read ({exc})")
                inputs.append(InputFile(path=f.path, size=len(f.data), kind="data", detected_format="unknown", note=str(exc)))
            continue
        data_files.append(f)
        inputs.append(
            InputFile(path=f.path, size=len(f.data), kind="data", detected_format=fmt, note=None if fmt != "unknown" else "Skipped")
        )
    lookup = {_norm(t.name): tid for tid, t in tables.items()} | {_norm(t.fqn): tid for tid, t in tables.items()}
    by_file = {PurePosixPath(e.file).name.lower(): e for e in manifest}
    parsed: list[ParsedFile] = []
    for f in data_files:
        entry = by_file.get(f.name.lower())
        tid, method, conf = None, "none", 0.0
        if f.path in overrides:
            tid, method, conf = (overrides[f.path] or None), "manual", 1.0
        elif entry:
            tid = lookup.get(_norm(entry.table))
            method, conf = ("manifest", 1.0) if tid else ("none", 0.0)
            if not tid:
                msgs.append(f"Manifest maps {f.name} to unknown table {entry.table}")
        p = read_data_file(f, opts, tables.get(tid) if tid else None, entry)
        if method == "none" and not entry:
            tid, method, conf = match_table(f.path, p.analysis.columns, tables)
            if tid and p.analysis.format == "delimited" and opts.header == "auto":
                p = read_data_file(f, opts, tables[tid], None)
        p.analysis.table_id, p.analysis.match_method, p.analysis.match_confidence = tid, method, conf  # type: ignore[assignment]
        if not tid and p.analysis.format != "unknown":
            p.analysis.issues.append("Not mapped to any table: choose a destination table")
        elif tid and conf < 0.9:
            p.analysis.issues.append(f"Low-confidence match ({conf:.0%}); please confirm")
        parsed.append(p)
    for e in manifest:
        if not any(PurePosixPath(p.analysis.path).name.lower() == PurePosixPath(e.file).name.lower() for p in parsed):
            msgs.append(f"Manifest lists {e.file} for {e.table} but the file was not uploaded")
    plans = {tid: validate_table(tid, t, [p for p in parsed if p.analysis.table_id == tid]) for tid, t in tables.items()}
    return inputs, [p.analysis for p in parsed], plans, manifest_path, msgs
