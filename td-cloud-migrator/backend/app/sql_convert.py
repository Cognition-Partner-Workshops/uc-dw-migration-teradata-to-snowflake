"""Teradata view / query conversion: rule-based Teradata rewrites, then sqlglot transpilation per target."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from .config_analyser import strip_comments
from .ddl_render import target_schema
from .models import Conversion, SourceObject, TargetId

DIALECT = {"bigquery": "bigquery", "redshift": "redshift", "synapse": "tsql", "duckdb": "duckdb"}

# Constructs with no safe automatic equivalent: the object is drafted and routed to manual review.
MANUAL_CONSTRUCTS = {
    "CSUM": r"\bCSUM\s*\(",
    "MAVG": r"\bMAVG\s*\(",
    "MSUM": r"\bMSUM\s*\(",
    "HASHROW/HASHBUCKET": r"\bHASH(ROW|BUCKET|AMP)\s*\(",
    "SAMPLE": r"\bSAMPLE\s+\d",
    "Macro parameters": r"(?<![\w:]):[A-Za-z_]\w*",
}


def _find_call(sql: str, name: str, start: int = 0) -> tuple[int, int, list[str]] | None:
    """Locate NAME( ... ) at or after `start`; return (begin, end, top-level args)."""
    m = re.compile(rf"\b{name}\s*\(", re.IGNORECASE).search(sql, start)
    if not m:
        return None
    depth, i, args, cur, in_str = 1, m.end(), [], [], False
    while i < len(sql) and depth:
        ch = sql[i]
        if ch == "'":
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                args.append("".join(cur).strip())
                cur = []
                i += 1
                continue
        cur.append(ch)
        i += 1
    args.append("".join(cur).strip())
    return m.start(), i + 1, args


def _rewrite_calls(sql: str, name: str, fn: Callable[[list[str]], str]) -> tuple[str, int]:
    count, pos = 0, 0
    while hit := _find_call(sql, name, pos):
        b, e, args = hit
        new = fn(args)
        sql = sql[:b] + new + sql[e:]
        pos = b + len(new)
        count += 1
    return sql, count


def _strip_format(sql: str) -> tuple[str, int]:
    """Drop Teradata FORMAT phrases: `expr (FORMAT 'x')`, `(DATE, FORMAT 'x')`, `(CHAR(n))` stays."""
    n = 0
    sql, k = re.subn(r"\(\s*FORMAT\s+'(?:[^']|'')*'\s*\)", "", sql, flags=re.IGNORECASE)
    n += k
    sql, k = re.subn(
        r"\(\s*(\w+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)\s*,\s*FORMAT\s+'(?:[^']|'')*'\s*\)", r"(\1)", sql, flags=re.IGNORECASE
    )
    return sql, n + k


_KEYWORDS = {
    "SELECT",
    "AS",
    "WHERE",
    "AND",
    "OR",
    "ON",
    "THEN",
    "ELSE",
    "WHEN",
    "IN",
    "BY",
    "FROM",
    "NOT",
    "IS",
    "BETWEEN",
    "CASE",
    "SET",
    "VALUES",
    "INTO",
    "USING",
    "HAVING",
    "QUALIFY",
    "JOIN",
    "RETURN",
    "EXISTS",
}
_TD_TYPES = r"BYTEINT|SMALLINT|INTEGER|INT|BIGINT|DECIMAL|NUMERIC|NUMBER|FLOAT|REAL|CHARACTER|CHAR|VARCHAR|DATE|TIME|TIMESTAMP"
_TD_CAST = re.compile(
    rf"\(\s*(?:(?P<type>(?:{_TD_TYPES})(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)\s*(?:,\s*FORMAT\s*'[^']*')?|FORMAT\s*'(?P<fmt>[^']*)')\s*\)",
    re.IGNORECASE,
)


def _matching_open(s: str, close: int) -> int:
    depth, i = 0, close
    while i >= 0:
        if s[i] == "'":
            i = s.rfind("'", 0, i)
        elif s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return -1


def _operand_start(s: str, end: int) -> int | None:
    """Start index of the expression ending just before `end` (identifier chain, literal, call or parenthesised group)."""
    j = end
    while j > 0 and s[j - 1].isspace():
        j -= 1
    if j == 0:
        return None
    if s[j - 1] == ")":
        k = _matching_open(s, j - 1)
        if k < 0:
            return None
        m = re.search(r"[\w.]+\s*$", s[:k])
        if m and m.group(0).strip().upper() not in _KEYWORDS:
            return m.start()
        return k
    if s[j - 1] == "'":
        k = s.rfind("'", 0, j - 1)
        return k if k >= 0 else None
    m = re.search(r"[\w.$#]+$", s[:j])
    if not m or m.group(0).upper() in _KEYWORDS:
        return None
    return m.start()


def td_casts(sql: str) -> tuple[str, list[str], list[str]]:
    """Teradata `expr (TYPE)` / `expr (FORMAT '...')` phrases -> ANSI CAST, plus a few Teradata date/time idioms."""
    rules: list[str] = []
    warnings: list[str] = []
    s = re.sub(r"\b(TIMESTAMP|DATE)\s+('[0-9: .-]+')", r"CAST(\2 AS \1)", sql, flags=re.IGNORECASE)
    s, k = re.subn(
        r"\bCAST\s*\(\s*CAST\s*\(\s*([\w.]+)\s+AS\s+DATE\s+FORMAT\s+'YYYYMMDD'\s*\)\s+AS\s+INT(?:EGER)?\s*\)",
        r"TD_YYYYMMDD(\1)",
        s,
        flags=re.IGNORECASE,
    )
    if k:
        rules.append("CAST(CAST(d AS DATE FORMAT 'YYYYMMDD') AS INTEGER) -> integer date key YYYYMMDD")
        warnings.append("Date key cast read as YYYYMMDD; confirm it matches the Teradata value for your DATEFORM setting")
    for m in reversed(list(re.finditer(r"\bCAST\s*\(", s, re.IGNORECASE))):
        e = _find_call(s, "CAST", m.start())
        if e and e[0] == m.start() and len(e[2]) == 1:
            inner = re.match(r"(?is)^(.*)\s+AS\s+DATE\s+FORMAT\s+'YYYY-MM-DD'\s*$", e[2][0])
            if inner:
                s = s[: e[0]] + f"CAST({inner.group(1)} AS DATE)" + s[e[1] :]
    casts = trims = 0
    for m in reversed(list(_TD_CAST.finditer(s))):
        start = _operand_start(s, m.start())
        if start is None:
            continue
        op = s[start : m.start()].rstrip()
        if m.group("type"):
            new = f"CAST({op} AS {m.group('type').upper()})"
            casts += 1
        elif re.search(r"\bTRIM\s*\(\s*$", s[:start], re.IGNORECASE) and s[m.end() :].lstrip().startswith(")"):
            fmt = m.group("fmt")
            n = len(fmt)
            new = f"TD_LPAD0(CAST({op} AS VARCHAR({n})), {n})" if n > 1 and set(fmt) == {"9"} else f"CAST({op} AS VARCHAR(64))"
            trims += 1
        else:
            continue
        s = s[:start] + new + s[m.end() :]
    if casts:
        rules.append(f"Teradata cast phrase x (TYPE) -> CAST(x AS TYPE) ({casts}x)")
    if trims:
        rules.append(f"TRIM(x (FORMAT ...)) -> CAST to string, zero-padded for 9-digit formats ({trims}x)")
    s, k = re.subn(
        r"\bCAST\s*\(\s*([\w.]+)\s+AS\s+TIMESTAMP(?:\s*\(\s*\d\s*\))?\s*\)\s*\+\s*\(\s*([\w.]+)\s*-\s*TIME\s*'00:00:00'\s*HOUR\s+TO\s+SECOND\s*\)",
        r"TD_DATE_TIME_TS(\1, \2)",
        s,
        flags=re.IGNORECASE,
    )
    if k:
        rules.append("DATE (TIMESTAMP) + (TIME - TIME '00:00:00' HOUR TO SECOND) -> combined date + time timestamp")
    s, k = re.subn(
        r"\(\s*(CURRENT_TIMESTAMP(?:\s*\(\s*\d\s*\))?|[\w.]+)\s*-\s*([\w.]+)\s*\)\s*SECOND(?:\s*\(\s*\d+\s*\))?",
        r"TD_SECONDS_BETWEEN(\2, \1)",
        s,
        flags=re.IGNORECASE,
    )
    if k:
        rules.append("(ts1 - ts2) SECOND -> seconds between timestamps")
    return s, rules, warnings


_PLACEHOLDERS: dict[str, dict[str, Callable[[list[str]], str]]] = {
    "TD_LPAD0": {
        "synapse": lambda a: f"RIGHT(REPLICATE('0', {a[1]}) + {a[0]}, {a[1]})",
        "*": lambda a: f"LPAD({a[0]}, {a[1]}, '0')",
    },
    "TD_DATE_TIME_TS": {
        "bigquery": lambda a: f"DATETIME({a[0]}, {a[1]})",
        "synapse": lambda a: f"DATEADD(SECOND, DATEDIFF(SECOND, 0, CAST({a[1]} AS DATETIME)), CAST({a[0]} AS DATETIME2))",
        "*": lambda a: f"({a[0]} + {a[1]})",
    },
    "TD_SECONDS_BETWEEN": {
        "bigquery": lambda a: f"DATETIME_DIFF({a[1]}, {a[0]}, SECOND)",
        "duckdb": lambda a: f"DATE_DIFF('second', {a[0]}, {a[1]})",
        "*": lambda a: f"DATEDIFF(SECOND, {a[0]}, {a[1]})",
    },
    "TD_YYYYMMDD": {
        "bigquery": lambda a: f"CAST(FORMAT_DATE('%Y%m%d', {a[0]}) AS INT64)",
        "redshift": lambda a: f"CAST(TO_CHAR({a[0]}, 'YYYYMMDD') AS INTEGER)",
        "synapse": lambda a: f"CAST(CONVERT(VARCHAR(8), {a[0]}, 112) AS INT)",
        "*": lambda a: f"CAST(STRFTIME({a[0]}, '%Y%m%d') AS INTEGER)",
    },
}


def render_placeholders(sql: str, target: str) -> str:
    for name, by_target in _PLACEHOLDERS.items():
        sql, _ = _rewrite_calls(sql, name, by_target.get(target, by_target["*"]))
    return sql


def preprocess(sql: str) -> tuple[str, list[str], list[str]]:
    """Apply Teradata-specific rewrites sqlglot doesn't handle. Returns (sql, rules, warnings)."""
    rules: list[str] = []
    warnings: list[str] = []
    s = strip_comments(sql)
    s, k = re.subn(r"\bLOCKING\s+(ROW|TABLE\s+[\w.]+|DATABASE\s+\w+)\s+FOR\s+ACCESS\b", "", s, flags=re.IGNORECASE)
    if k:
        rules.append("LOCKING ROW FOR ACCESS removed (targets use MVCC / snapshot reads)")
    s, k = re.subn(r"\bSEL\b", "SELECT", s, flags=re.IGNORECASE)
    if k:
        rules.append("SEL -> SELECT")
    s, r2, w2 = td_casts(s)
    rules += r2
    warnings += w2
    s, k = _strip_format(s)
    if k:
        rules.append(f"FORMAT phrase removed ({k}x); presentation must move to the BI layer")
    s, k = _rewrite_calls(s, "ZEROIFNULL", lambda a: f"COALESCE({a[0]}, 0)")
    if k:
        rules.append("ZEROIFNULL(x) -> COALESCE(x, 0)")
    s, k = _rewrite_calls(s, "NULLIFZERO", lambda a: f"NULLIF({a[0]}, 0)")
    if k:
        rules.append("NULLIFZERO(x) -> NULLIF(x, 0)")
    s, k = re.subn(r"\(\s*NOT\s+CASESPECIFIC\s*\)|\(\s*NOT\s+CS\s*\)|\(\s*CASESPECIFIC\s*\)|\(\s*CS\s*\)", "", s, flags=re.IGNORECASE)
    if k:
        rules.append("CASESPECIFIC casts removed")
        warnings.append("NOT CASESPECIFIC comparisons: confirm target collation (BigQuery/Redshift compare case-sensitively)")
    s, k = re.subn(r"\bCURRENT_DATE\s*([-+])\s*(\d+)\b", r"CURRENT_DATE \1 INTERVAL '\2' DAY", s, flags=re.IGNORECASE)
    if k:
        rules.append("DATE +/- n -> DATE +/- INTERVAL 'n' DAY")
    s = re.sub(r"\bINTERVAL\s*'(\d+)'\s*(DAY|MONTH|YEAR)\b", r"INTERVAL '\1' \2", s, flags=re.IGNORECASE)
    return s.strip().rstrip(";"), rules, warnings


def _manual_constructs(sql: str) -> list[str]:
    body = re.sub(r"'(?:[^']|'')*'", "''", strip_comments(sql))
    return [k for k, rx in MANUAL_CONSTRUCTS.items() if re.search(rx, body, re.IGNORECASE)]


def _retarget_tables(tree: exp.Expression, target: str, schema_map: dict[str, str], project: str) -> None:
    for t in tree.find_all(exp.Table):
        db = t.args.get("db")
        if db is not None:
            schema = target_schema(db.name.upper(), schema_map)
            t.set("db", exp.to_identifier(schema))
            if target == "bigquery" and project:
                t.set("catalog", exp.to_identifier(project, quoted=True))
        if target == "redshift":
            t.set("this", exp.to_identifier(t.name.lower()))


@dataclass
class Transpiled:
    sql: str
    rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)


_TIME_COL = re.compile(r"DATE|MONTH|YEAR|QUARTER|WEEK|DAY|PERIOD|TIME|_TS$|_DT$", re.IGNORECASE)
_INT_TYPES = ("BYTEINT", "SMALLINT", "INTEGER", "INT", "BIGINT")


def _var_kind(var_types: dict[str, str], col: exp.Expression) -> str | None:
    if not isinstance(col, exp.Column) or col.table:
        return None
    t = var_types.get(col.name.upper(), "").upper()
    if not t:
        return None
    if t.startswith("TIMESTAMP"):
        return "ts"
    if t.startswith("DATE"):
        return "date"
    if t.split("(")[0].strip() in _INT_TYPES:
        return "int"
    return "other"


def _is_date(e: exp.Expression, vt: dict[str, str]) -> bool:
    e = e.unnest()
    if isinstance(e, (exp.CurrentDate, exp.DateAdd, exp.DateSub)):
        return True
    if isinstance(e, exp.Cast):
        return e.to.this == exp.DataType.Type.DATE
    if isinstance(e, exp.Coalesce):
        return _is_date(e.this, vt)
    if isinstance(e, exp.Column):
        k = _var_kind(vt, e)
        return k == "date" if k else bool(re.search(r"DATE$|_DT$", e.name, re.IGNORECASE))
    return False


def _is_int(e: exp.Expression, vt: dict[str, str]) -> bool:
    e = e.unnest()
    if isinstance(e, exp.Neg):
        return _is_int(e.this, vt)
    if isinstance(e, exp.Literal):
        return not e.is_string and e.this.lstrip("-").isdigit()
    return _var_kind(vt, e) == "int"


def _hash_sql(args: list[str], target: str) -> str:
    if target == "bigquery":
        return "FARM_FINGERPRINT(CONCAT(" + ", '|', ".join(f"COALESCE(CAST({a} AS STRING), '')" for a in args) + "))"
    if target == "redshift":
        out = f"FNV_HASH({args[0]})"
        for a in args[1:]:
            out = f"FNV_HASH({a}, {out})"
        return out
    if target == "synapse":
        return "HASHBYTES('SHA2_256', CONCAT_WS('|', " + ", ".join(args) + "))"
    return "HASH(" + ", ".join(args) + ")"


_HASH_LABEL = {
    "bigquery": "FARM_FINGERPRINT",
    "redshift": "FNV_HASH",
    "synapse": "HASHBYTES('SHA2_256', ...)",
    "duckdb": "HASH",
}


def _olap(tree: exp.Expression, out: Transpiled) -> None:
    for fn in list(tree.find_all(exp.Anonymous)):
        name = fn.name.upper()
        if name not in ("CSUM", "MAVG", "MSUM"):
            continue
        args = fn.expressions
        width = None
        if name != "CSUM":
            if len(args) < 3 or not (isinstance(args[1], exp.Literal) and args[1].this.isdigit()):
                out.manual.append(f"{name} without a constant window width")
                continue
            width = int(args[1].this)
        value, sort = args[0], args[1:] if name == "CSUM" else args[2:]
        if not sort:
            out.manual.append(f"{name} without a sort expression")
            continue
        sel = fn.find_ancestor(exp.Select)
        group = sel.args.get("group") if sel else None
        part: list[exp.Expression] = []
        if group:
            if not value.find(exp.AggFunc):
                out.manual.append(f"{name} over a GROUP BY query without an aggregate argument (Teradata reset semantics)")
                continue
            sort_sql = {s.sql("teradata") for s in sort}
            part = [
                g
                for g in group.expressions
                if g.sql("teradata") not in sort_sql and not (isinstance(g, exp.Column) and _TIME_COL.search(g.name))
            ]
        agg = "AVG" if name == "MAVG" else "SUM"
        frame = "ROWS UNBOUNDED PRECEDING" if width is None else f"ROWS BETWEEN {max(width - 1, 0)} PRECEDING AND CURRENT ROW"
        part_sql = ", ".join(p.sql("teradata") for p in part)
        order_sql = ", ".join(s.sql("teradata") for s in sort)
        over = (f"PARTITION BY {part_sql} " if part else "") + f"ORDER BY {order_sql} {frame}"
        fn.replace(sqlglot.parse_one(f"{agg}({value.sql('teradata')}) OVER ({over})", read="teradata"))
        out.rules.append(f"{name} -> {agg}(...) OVER ({over})")
        if part:
            out.warnings.append(
                f"{name}: running window restarts for each {part_sql} (the non-time GROUP BY columns); "
                "confirm this matches the Teradata result"
            )


def _hashes(tree: exp.Expression, target: str, out: Transpiled) -> None:
    for fn in list(tree.find_all(exp.Anonymous)):
        name = fn.name.upper()
        if name in ("HASHBUCKET", "HASHAMP"):
            out.manual.append(f"{name} (AMP / bucket distribution has no target equivalent)")
        if name != "HASHROW":
            continue
        if fn.find_ancestor(exp.Where, exp.Join, exp.Group, exp.Order, exp.Having):
            out.manual.append("HASHROW used in a filter, join or grouping (hash values differ on the target)")
            continue
        dialect = DIALECT[target]
        args = [a.sql(dialect) for a in fn.expressions]
        fn.replace(sqlglot.parse_one(_hash_sql(args, target), read=dialect))
        out.rules.append(f"HASHROW(...) -> {_HASH_LABEL[target]}(...)")
        out.warnings.append("Row hash values differ from Teradata HASHROW; do not compare or join them with hashes made on Teradata")


def transpile_ex(
    sql: str,
    target: str,
    schema_map: dict[str, str],
    project: str = "",
    numeric_cols: frozenset[str] = frozenset(),
    var_types: dict[str, str] | None = None,
) -> Transpiled:
    """Rewritten Teradata SQL -> target SQL with rules applied. Raises on parse failure."""
    vt = var_types or {}
    res = Transpiled(sql="")
    tree = sqlglot.parse_one(sql, read="teradata")
    for fn in tree.find_all(exp.Anonymous):
        if not re.match(r"TD_|CSUM$|MAVG$|MSUM$|HASH(ROW|BUCKET|AMP)$", fn.name.upper()):
            res.warnings.append(f"Unknown function {fn.name}() passed through unchanged")
    for trim in list(tree.find_all(exp.Trim)):
        if isinstance(trim.this, exp.Column) and (trim.this.name.upper() in numeric_cols or _var_kind(vt, trim.this) == "int"):
            trim.this.replace(exp.cast(trim.this.copy(), "VARCHAR"))
            res.warnings.append(f"TRIM({trim.this.sql('teradata')}): numeric -> explicit CAST to string (Teradata casts implicitly)")
    _retarget_tables(tree, target, schema_map, project)
    for fn in list(tree.find_all(exp.Func)):
        if fn.sql_name() == "ADD_MONTHS" or (isinstance(fn, exp.Anonymous) and fn.name.upper() == "ADD_MONTHS"):
            args = fn.expressions if isinstance(fn, exp.Anonymous) else [fn.this, fn.expression]
            if len(args) == 2:
                fn.replace(exp.DateAdd(this=args[0].copy(), expression=args[1].copy(), unit=exp.var("MONTH")))
    for node in reversed(list(tree.find_all(exp.Add, exp.Sub))):
        left, right = node.this, node.expression
        if _is_date(left, vt) and _is_int(right, vt):
            amount = right.copy() if isinstance(node, exp.Add) else exp.Neg(this=right.copy())
            node.replace(exp.DateAdd(this=left.copy(), expression=amount, unit=exp.var("DAY")))
            res.rules.append("DATE +/- n -> date add of n days")
        elif isinstance(node, exp.Sub) and _is_date(left, vt) and _is_date(right, vt):
            res.warnings.append(f"Date subtraction {node.sql('teradata')} -> DATEDIFF in days (assumes DATE operands)")
            node.replace(exp.DateDiff(this=left.copy(), expression=right.copy(), unit=exp.var("DAY")))
    _olap(tree, res)
    _hashes(tree, target, res)
    if target == "synapse":
        for sel in tree.find_all(exp.Select):
            if sel.args.get("qualify"):
                for i, e in enumerate(list(sel.expressions), 1):
                    if not isinstance(e, (exp.Alias, exp.Column, exp.Star)):
                        e.replace(exp.alias_(e.copy(), f"col_{i}"))
    out = tree.sql(dialect=DIALECT[target], pretty=True, unsupported_level=sqlglot.ErrorLevel.IGNORE)
    res.sql = render_placeholders(out, target)
    res.rules = list(dict.fromkeys(res.rules))
    res.warnings = list(dict.fromkeys(res.warnings))
    return res


def transpile_query(
    sql: str, target: str, schema_map: dict[str, str], project: str = "", numeric_cols: frozenset[str] = frozenset()
) -> tuple[str, list[str]]:
    """Rewritten Teradata SELECT -> target SQL. Raises on parse failure."""
    res = transpile_ex(sql, target, schema_map, project, numeric_cols)
    return res.sql, res.warnings


_VIEW_HEAD = re.compile(
    r"^\s*(?:CREATE\s+OR\s+REPLACE|CREATE|REPLACE)\s+(?:RECURSIVE\s+)?VIEW\s+([\w$#\".]+)\s*(\([^)]*\))?\s*AS\s+", re.IGNORECASE
)


def split_view(sql: str) -> tuple[str, str | None, str]:
    s = strip_comments(sql).strip()
    m = _VIEW_HEAD.match(s)
    if not m:
        raise ValueError("not a CREATE/REPLACE VIEW statement")
    return m.group(1), m.group(2), s[m.end() :].rstrip().rstrip(";")


def view_ddl(obj: SourceObject, target: str, body_sql: str, schema_map: dict[str, str], project: str) -> str:
    schema = target_schema(obj.database, schema_map)
    if target == "bigquery":
        name = f"`{project + '.' if project else ''}{schema}.{obj.name}`"
        return f"CREATE OR REPLACE VIEW {name} AS\n{body_sql};"
    if target == "redshift":
        return f"CREATE OR REPLACE VIEW {schema}.{obj.name.lower()} AS\n{body_sql};"
    if target == "synapse":
        return f"CREATE OR ALTER VIEW [{schema}].[{obj.name}] AS\n{body_sql};"
    return f'CREATE OR REPLACE VIEW "{schema}"."{obj.name}" AS\n{body_sql};'


def convert_view(
    obj: SourceObject, target: TargetId, schema_map: dict[str, str], project: str = "", numeric_cols: frozenset[str] = frozenset()
) -> Conversion:
    rules: list[str] = []
    warnings: list[str] = []
    header = f"-- Source: {obj.fqn} (view) from {obj.source_file}\n"
    try:
        _, cols, body = split_view(obj.sql)
        pre, rules, warnings = preprocess(body)
        if cols:
            warnings.append("View column list given separately; verify column aliases")
        manual = [m for m in _manual_constructs(pre) if m in ("SAMPLE", "Macro parameters")]
        res = None if manual else transpile_ex(pre, target, schema_map, project, numeric_cols)
        if res is not None and res.manual:
            manual = res.manual
        if manual:
            draft, _ = _draft(pre, target, schema_map, project, numeric_cols)
            return Conversion(
                object_id=obj.id,
                target=target,
                status="manual_review",
                sql=header
                + f"-- MANUAL REVIEW: {', '.join(manual)} require rewrite\n"
                + view_ddl(obj, target, draft, schema_map, project)
                + "\n",
                rules=rules + [_HINTS[m] for m in manual if m in _HINTS],
                warnings=warnings,
                reason=f"Uses {', '.join(manual)} (no automatic equivalent)",
            )
        assert res is not None
        out, problems = res.sql, res.warnings
        rules += res.rules
        if re.search(r"\bQUALIFY\b", body, re.IGNORECASE):
            rules.append("QUALIFY " + ("kept (native)" if target in ("bigquery", "redshift") else "-> derived table + WHERE"))
        if re.search(r"\bADD_MONTHS\b", body, re.IGNORECASE):
            rules.append(
                "ADD_MONTHS -> "
                + {"bigquery": "DATE_ADD(..., INTERVAL n MONTH)", "redshift": "ADD_MONTHS", "synapse": "DATEADD(MONTH, n, ...)"}[target]
            )
        warnings += problems
        return Conversion(
            object_id=obj.id,
            target=target,
            status="converted_with_warnings" if warnings else "converted",
            sql=header + view_ddl(obj, target, out, schema_map, project) + "\n",
            rules=list(dict.fromkeys(rules)),
            warnings=list(dict.fromkeys(warnings)),
        )
    except Exception as exc:  # noqa: BLE001
        return Conversion(
            object_id=obj.id,
            target=target,
            status="unsupported",
            sql=header + "-- Could not convert\n" + obj.sql,
            rules=rules,
            warnings=warnings,
            reason=f"Parse/convert error: {exc}",
        )


_HINTS = {
    "CSUM": "CSUM(x, o) -> SUM(x) OVER (ORDER BY o ROWS UNBOUNDED PRECEDING)",
    "MAVG": "MAVG(x, n, o) -> AVG(x) OVER (ORDER BY o ROWS n-1 PRECEDING)",
    "MSUM": "MSUM(x, n, o) -> SUM(x) OVER (ORDER BY o ROWS n-1 PRECEDING)",
    "HASHROW/HASHBUCKET": "HASHROW -> FARM_FINGERPRINT / FNV_HASH / HASHBYTES (values differ from Teradata)",
    "SAMPLE": "SAMPLE n -> TABLESAMPLE / ORDER BY RAND() LIMIT n",
    "Macro parameters": ":param -> procedure / parameterised query arguments",
}


def _draft(sql: str, target: str, schema_map: dict[str, str], project: str, numeric_cols: frozenset[str] = frozenset()) -> tuple[str, bool]:
    """Best-effort draft: rewrite CSUM/MAVG/MSUM to window functions and transpile; fall back to the rewritten text."""
    s = sql
    s, _ = _rewrite_calls(s, "CSUM", lambda a: f"SUM({a[0]}) OVER (ORDER BY {a[1] if len(a) > 1 else '1'} ROWS UNBOUNDED PRECEDING)")
    s, _ = _rewrite_calls(
        s,
        "MAVG",
        lambda a: (
            f"AVG({a[0]}) OVER (ORDER BY {a[2] if len(a) > 2 else '1'} ROWS {max(int(a[1]) - 1, 0) if len(a) > 1 and a[1].isdigit() else 0} PRECEDING)"
        ),
    )
    s, _ = _rewrite_calls(
        s,
        "MSUM",
        lambda a: (
            f"SUM({a[0]}) OVER (ORDER BY {a[2] if len(a) > 2 else '1'} ROWS {max(int(a[1]) - 1, 0) if len(a) > 1 and a[1].isdigit() else 0} PRECEDING)"
        ),
    )
    s, _ = _rewrite_calls(s, "HASHROW", lambda a: "MD5(" + " || '|' || ".join(f"CAST({x} AS VARCHAR(200))" for x in a) + ")")
    try:
        out, _ = transpile_query(s, target, schema_map, project, numeric_cols)
        return out, True
    except Exception:  # noqa: BLE001
        return s, False


def draft_routine(obj: SourceObject, target: TargetId, schema_map: dict[str, str], project: str = "") -> Conversion:
    """Macros, procedures, BTEQ and loose scripts: translate each embedded DML statement as a draft."""
    from .config_analyser import split_statements

    kind = {
        "macro": "macro",
        "procedure": "stored procedure",
        "bteq_script": "BTEQ script",
        "sql_script": "SQL script",
        "other": "statement",
    }[obj.object_type]
    text = obj.sql
    if obj.object_type == "bteq_script":
        text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("."))
    if obj.object_type == "macro" and (m := re.search(r"\bAS\s*\((.*)\)\s*;?\s*$", strip_comments(text), re.IGNORECASE | re.DOTALL)):
        text = m.group(1)
    translated, failed = [], 0
    for stmt in split_statements(text):
        pre, _, _ = preprocess(stmt)
        if not re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH)\b", pre, re.IGNORECASE):
            continue
        pre = re.sub(r"(?<![\w:]):([A-Za-z_]\w*)", r"@\1" if target == "synapse" else r"p_\1", pre)
        out, ok = _draft(pre, target, schema_map, project)
        failed += not ok
        translated.append(out + ";")
    native = {
        "bigquery": "BigQuery scripting procedure (CREATE PROCEDURE ... BEGIN ... END)",
        "redshift": "PL/pgSQL stored procedure",
        "synapse": "T-SQL stored procedure",
    }[target]
    header = (
        f"-- Source: {obj.fqn} ({kind}) from {obj.source_file}\n"
        f"-- MANUAL REVIEW: re-implement as a {native}"
        + (" or orchestrate from Airflow / Step Functions / Data Factory" if obj.object_type == "bteq_script" else "")
        + f"\n-- Teradata features used: {', '.join(obj.features) or 'none detected'}\n"
        f"-- Draft translation of {len(translated)} embedded statement(s){f' ({failed} not parsed)' if failed else ''}:\n\n"
    )
    status = "manual_review" if translated or obj.object_type != "other" else "unsupported"
    return Conversion(
        object_id=obj.id,
        target=target,
        status=status,  # type: ignore[arg-type]
        sql=header + "\n\n".join(translated) + "\n",
        rules=["Embedded DML drafted with the view/query rules"] if translated else [],
        warnings=[f"{len(translated)} statement(s) drafted; control flow, parameters and error handling need manual work"],
        reason=obj.parse_error or f"{kind.capitalize()} logic cannot be converted automatically",
    )
