"""Configuration dump analyser: object inventory, table definitions, SQL dependencies and create order."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from graphlib import CycleError, TopologicalSorter

from .ingest import UploadedFile, dbc_kind, decode, detect_config, read_bytes
from .models import ForeignKey, InputFile, SourceObject, TableMeta
from .td_catalog import IndexDef, column_from_dbc, keys_from_indexes, partition_columns
from .td_ddl import parse_ddl

FEATURES: dict[str, str] = {
    "SEL abbreviation": r"\bSEL\b",
    "QUALIFY": r"\bQUALIFY\b",
    "ZEROIFNULL": r"\bZEROIFNULL\s*\(",
    "NULLIFZERO": r"\bNULLIFZERO\s*\(",
    "ADD_MONTHS": r"\bADD_MONTHS\s*\(",
    "FORMAT phrase": r"\(\s*FORMAT\s+'",
    "LOCKING modifier": r"\bLOCKING\s+(ROW|TABLE)\b",
    "CSUM": r"\bCSUM\s*\(",
    "MAVG": r"\bMAVG\s*\(",
    "HASHROW/HASHBUCKET": r"\bHASH(ROW|BUCKET|AMP)\s*\(",
    "NOT CASESPECIFIC": r"\bNOT\s+CASESPECIFIC\b|\(\s*CS\s*\)|\(\s*NOT\s+CS\s*\)",
    "TOP n": r"\bTOP\s+\d+",
    "SAMPLE": r"\bSAMPLE\s+\d",
    "ACTIVITY_COUNT": r"\bACTIVITY_COUNT\b",
    "Error handlers": r"\bDECLARE\s+\w+\s+HANDLER\b",
    "Volatile tables": r"\bVOLATILE\s+TABLE\b",
    "MERGE": r"\bMERGE\s+INTO\b",
    "BTEQ control (.IF/.GOTO)": r"^\s*\.(IF|GOTO|LABEL)\b",
    "BTEQ export": r"^\s*\.EXPORT\b",
    "Date arithmetic": r"\bCURRENT_DATE\s*[-+]\s*\d",
    "Macro parameters": r"(?<![\w:]):\w+",
}

_OBJ = r'("?[\w$#]+"?)\s*\.\s*("?[\w$#]+"?)'
_VIEW_RE = re.compile(rf"^\s*(?:CREATE|REPLACE|CREATE\s+OR\s+REPLACE)\s+(?:RECURSIVE\s+)?VIEW\s+{_OBJ}", re.IGNORECASE)
_MACRO_RE = re.compile(rf"^\s*(?:CREATE|REPLACE)\s+MACRO\s+{_OBJ}", re.IGNORECASE | re.MULTILINE)
_PROC_RE = re.compile(rf"^\s*(?:CREATE|REPLACE)\s+PROCEDURE\s+{_OBJ}", re.IGNORECASE | re.MULTILINE)
_STATS_RE = re.compile(r"^\s*COLLECT\s+STAT(?:ISTICS|S)?\b(.*?)\bON\s+" + _OBJ, re.IGNORECASE | re.DOTALL)


def strip_comments(sql: str) -> str:
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n and not (sql[j] == "'" and (j + 1 >= n or sql[j + 1] != "'")):
                j += 2 if sql[j] == "'" else 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """Split on top-level semicolons (quotes and parentheses respected)."""
    sql = strip_comments(sql)
    parts, buf, depth, i = [], [], 0, 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            j = sql.find("'", i + 1)
            while j >= 0 and j + 1 < len(sql) and sql[j + 1] == "'":
                j = sql.find("'", j + 2)
            j = len(sql) - 1 if j < 0 else j
            buf.append(sql[i : j + 1])
            i = j + 1
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == ";" and depth <= 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _clean(name: str) -> str:
    return name.strip('"').upper()


def detect_features(sql: str) -> list[str]:
    body = re.sub(r"'(?:[^']|'')*'", "''", strip_comments(sql))
    return [f for f, rx in FEATURES.items() if re.search(rx, body, re.IGNORECASE | re.MULTILINE)]


def _obj(kind: str, db: str, name: str, f: UploadedFile, fmt: str, sql: str) -> SourceObject:
    return SourceObject(
        id=f"{kind}:{db}.{name}".upper() if db else f"{kind}:{name}".upper(),
        object_type=kind,  # type: ignore[arg-type]
        database=db,
        name=name,
        source_file=f.path,
        source_format=fmt,
        sql=sql.strip() + "\n",
        features=detect_features(sql) if kind != "table" else [],
    )


def _from_sql(f: UploadedFile, fmt: str, objects: list[SourceObject], stats: list[tuple[str, list[str]]]) -> list[str]:
    text = decode(read_bytes(f))
    msgs: list[str] = []
    stem = re.sub(r"\.\w+$", "", f.name).upper()
    if fmt == "bteq":
        db = re.search(r"^\s*DATABASE\s+(\w+)", text, re.IGNORECASE | re.MULTILINE)
        objects.append(_obj("bteq_script", db.group(1).upper() if db else "", stem, f, fmt, text))
        return msgs
    if m := _PROC_RE.search(text):
        objects.append(_obj("procedure", _clean(m.group(1)), _clean(m.group(2)), f, fmt, text))
        return msgs
    if m := _MACRO_RE.search(text):
        objects.append(_obj("macro", _clean(m.group(1)), _clean(m.group(2)), f, fmt, text))
        return msgs
    stmts = split_statements(text)
    if any(re.match(r"\s*CREATE\s+(SET\s+|MULTISET\s+|VOLATILE\s+|GLOBAL\s+TEMPORARY\s+)*TABLE\b", s, re.IGNORECASE) for s in stmts):
        try:
            for pt in parse_ddl(text):
                o = _obj("table", pt.meta.database.upper(), pt.meta.name.upper(), f, fmt, "")
                pt.meta.database, pt.meta.name = o.database, o.name
                o.table, o.comment = pt.meta, pt.comment
                o.sql = "\n".join(s + ";" for s in stmts if re.search(rf"\b{re.escape(o.name)}\b", s, re.IGNORECASE)) + "\n"
                objects.append(o)
        except Exception as exc:  # noqa: BLE001 - reported per object, the run continues
            name = re.search(r"TABLE\s+" + _OBJ, text, re.IGNORECASE)
            o = _obj("table", _clean(name.group(1)) if name else "", _clean(name.group(2)) if name else stem, f, fmt, text)
            o.parse_error = str(exc)
            objects.append(o)
            msgs.append(f"{f.path}: could not parse table DDL ({exc})")
    for s in stmts:
        if m := _VIEW_RE.match(s):
            objects.append(_obj("view", _clean(m.group(1)), _clean(m.group(2)), f, fmt, s + ";"))
        elif m := _STATS_RE.match(s):
            cols = re.findall(r"COLUMN\s*\(?\s*([\w\s,]+?)\s*\)?\s*(?:,|$)", m.group(1), re.IGNORECASE)
            stats.append(
                (f"{_clean(m.group(2))}.{_clean(m.group(3))}", [c.strip().upper() for c in ",".join(cols).split(",") if c.strip()])
            )
        elif re.match(r"\s*(CREATE|REPLACE)\s+(SET\s+|MULTISET\s+)?TABLE\b|\s*COMMENT\s+ON\b", s, re.IGNORECASE):
            continue
        elif re.match(r"\s*(SEL|SELECT|INS|INSERT|UPD|UPDATE|DEL|DELETE|MERGE|CALL|EXEC)\b", s, re.IGNORECASE):
            objects.append(_obj("sql_script", "", f"{stem}_{len(objects) + 1}", f, fmt, s + ";"))
        elif re.match(r"\s*(DATABASE|SET\s+QUERY_BAND|BT|ET)\b", s, re.IGNORECASE):
            continue
        else:
            kw = " ".join(s.split()[:3]).upper()
            o = _obj("other", "", f"{stem}_{len(objects) + 1}", f, fmt, s + ";")
            o.parse_error = f"Unrecognised statement: {kw}"
            objects.append(o)
    return msgs


def _rows(f: UploadedFile, fmt: str) -> list[dict]:
    text = decode(read_bytes(f)).lstrip("\ufeff")
    if fmt == "dbc_json":
        doc = json.loads(text)
        return doc if isinstance(doc, list) else next((v for v in doc.values() if isinstance(v, list)), [])
    delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",|;\t").delimiter
    # DBC DefaultValue holds SQL literals such as 'NOK'; only '"' may act as the CSV quote character.
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter, quotechar='"'))


def _from_dbc(files: list[tuple[UploadedFile, str]], objects: list[SourceObject]) -> list[str]:
    """Rebuild tables/views from DBC.TablesV / ColumnsV / IndicesV exports (files or JSON sections)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    origin: dict[str, str] = {}
    for f, fmt in files:
        if fmt == "dbc_json":
            doc = json.loads(decode(read_bytes(f)))
            sections = doc.items() if isinstance(doc, dict) else [("rows", doc)]
            for _, rows in sections:
                if isinstance(rows, list) and rows and (k := dbc_kind(set(rows[0]))):
                    groups[k] += rows
                    origin[k] = f.path
        else:
            rows = _rows(f, fmt)
            if rows and (k := dbc_kind(set(rows[0]))):
                groups[k] += rows
                origin[k] = f.path
    if not groups.get("columns"):
        return ["DBC export found but no ColumnsV data; tables cannot be rebuilt"] if groups else []

    def low(r: dict) -> dict:
        return {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}

    tables_rows = {(low(r)["databasename"].upper(), low(r)["tablename"].upper()): low(r) for r in groups.get("tables", [])}
    by_table: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in map(low, groups["columns"]):
        by_table[(r["databasename"].upper(), r["tablename"].upper())].append(r)
    idx: dict[tuple[str, str], dict[int, IndexDef]] = defaultdict(dict)
    for r in map(low, groups.get("indices", [])):
        key, num = (r["databasename"].upper(), r["tablename"].upper()), int(float(r["indexnumber"]))
        d = idx[key].setdefault(
            num, IndexDef(num, r["indextype"].upper(), (r.get("uniqueflag") or "N").upper() == "Y", [], r.get("indexname") or None)
        )
        d.columns.append(r["columnname"].upper())
    msgs = []
    for (db, name), cols in by_table.items():
        trow = tables_rows.get((db, name), {})
        if (trow.get("tablekind") or "T").upper() == "V":
            continue
        fake = UploadedFile(origin.get("columns", "dbc"), b"")
        o = _obj("table", db, name, fake, "dbc_export", "")
        try:
            columns = sorted((column_from_dbc(c) for c in cols), key=lambda c: c.ordinal)
            for i, c in enumerate(columns, 1):
                c.ordinal, c.name = i, c.name.upper()
            meta = TableMeta(database=db, name=name, columns=columns)
            ixs = list(idx[(db, name)].values())
            meta.primary_index, meta.primary_index_unique, meta.unique_keys = keys_from_indexes(ixs)
            meta.secondary_indexes = [i.columns for i in ixs if i.kind == "S"]
            meta.kind = "SET" if (trow.get("tablekind") or "").upper() == "T" and trow.get("settype", "") == "S" else "MULTISET"
            meta.partition_expression = trow.get("partitioningexpression") or None
            meta.partition_columns = partition_columns(meta.partition_expression, [c.name for c in columns])
            meta.comment = trow.get("commentstring") or None
            o.table, o.comment = meta, meta.comment
        except Exception as exc:  # noqa: BLE001
            o.parse_error = str(exc)
            msgs.append(f"DBC export: {db}.{name}: {exc}")
        objects.append(o)
    for (db, name), trow in tables_rows.items():
        if (trow.get("tablekind") or "").upper() in ("V", "M", "P") and trow.get("requesttext"):
            kind = {"V": "view", "M": "macro", "P": "procedure"}[trow["tablekind"].upper()]
            objects.append(_obj(kind, db, name, UploadedFile(origin.get("tables", "dbc"), b""), "dbc_export", trow["requesttext"]))
    return msgs


def _dependencies(objects: list[SourceObject]) -> None:
    known = {o.fqn.upper(): o.id for o in objects if o.object_type in ("table", "view", "macro", "procedure")}
    by_name = defaultdict(list)
    for fqn, oid in known.items():
        by_name[fqn.split(".")[-1]].append(oid)
    for o in objects:
        deps: list[str] = []
        if o.table:
            for fk in o.table.foreign_keys:
                deps.append(known.get(f"{fk.ref_database}.{fk.ref_table}".upper(), ""))
        if o.sql and o.object_type != "table":
            body = re.sub(r"'(?:[^']|'')*'", "''", strip_comments(o.sql))
            for db, name in re.findall(r"\b([\w$#]+)\s*\.\s*([\w$#]+)\b", body):
                deps.append(known.get(f"{db}.{name}".upper(), ""))
            for word in set(re.findall(r"\b[A-Za-z_][\w$#]*\b", body)):
                if len(by_name.get(word.upper(), [])) == 1 and o.database:
                    deps.append(by_name[word.upper()][0])
        o.dependencies = sorted({d for d in deps if d and d != o.id})


def create_order(objects: list[SourceObject]) -> list[str]:
    rank = {"table": 0, "view": 1, "macro": 2, "procedure": 3, "sql_script": 4, "bteq_script": 5, "other": 6}
    graph = TopologicalSorter({o.id: o.dependencies for o in objects})
    try:
        graph.prepare()
    except CycleError:
        return [o.id for o in sorted(objects, key=lambda o: rank[o.object_type])]
    ids = {o.id: o for o in objects}
    order: list[str] = []
    while graph.is_active():
        ready = sorted(graph.get_ready(), key=lambda i: (rank[ids[i].object_type], i) if i in ids else (9, i))
        order += [i for i in ready if i in ids]
        graph.done(*ready)
    return order


def analyse_config(files: list[UploadedFile], selected: str = "auto") -> tuple[list[InputFile], list[SourceObject], list[str], list[str]]:
    objects: list[SourceObject] = []
    stats: list[tuple[str, list[str]]] = []
    inputs, msgs, dbc = [], [], []
    for f in files:
        fmt = detect_config(f, selected if selected not in ("auto", "zip") else "auto")
        if selected in ("ddl_sql", "bteq") and fmt == "unknown":
            fmt = selected
        note = None
        if fmt in ("ddl_sql", "bteq"):
            before = len(objects)
            msgs += _from_sql(f, fmt, objects, stats)
            note = f"{len(objects) - before} object(s)"
        elif fmt in ("dbc_csv", "dbc_json"):
            dbc.append((f, fmt))
            note = "DBC dictionary export"
        else:
            note = "Skipped: not a recognised configuration format"
            msgs.append(f"{f.path}: skipped (unrecognised configuration format)")
        inputs.append(InputFile(path=f.path, size=len(f.data), kind="config", detected_format=fmt, note=note))
    msgs += _from_dbc(dbc, objects)
    seen: dict[str, SourceObject] = {}
    for o in objects:
        if o.id in seen:
            msgs.append(f"{o.fqn} defined more than once; using {o.source_file}")
        seen[o.id] = o
    objects = list(seen.values())
    tables = {o.fqn.upper(): o.table for o in objects if o.table}
    for fqn, cols in stats:
        if (t := tables.get(fqn)) and cols:
            t.statistics.append(cols)
    _dependencies(objects)
    return inputs, objects, create_order(objects), msgs


__all__ = ["ForeignKey", "analyse_config", "create_order", "detect_features", "split_statements", "strip_comments"]
