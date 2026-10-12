"""Teradata view / query conversion: rule-based Teradata rewrites, then sqlglot transpilation per target."""

from __future__ import annotations

import re
from collections.abc import Callable

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
    "SELECT", "AS", "WHERE", "AND", "OR", "ON", "THEN", "ELSE", "WHEN", "IN", "BY", "FROM", "NOT", "IS",
    "BETWEEN", "CASE", "SET", "VALUES", "INTO", "USING", "HAVING", "QUALIFY", "JOIN", "RETURN", "EXISTS",
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
    s = sql
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


def transpile_query(
    sql: str, target: str, schema_map: dict[str, str], project: str = "", numeric_cols: frozenset[str] = frozenset()
) -> tuple[str, list[str]]:
    """Rewritten Teradata SELECT -> target SQL. Raises on parse failure."""
    problems: list[str] = []
    tree = sqlglot.parse_one(sql, read="teradata")
    for trim in list(tree.find_all(exp.Trim)):
        if isinstance(trim.this, exp.Column) and trim.this.name.upper() in numeric_cols:
            trim.this.replace(exp.cast(trim.this.copy(), "VARCHAR"))
            problems.append(f"TRIM({trim.this.sql('teradata')}): numeric -> explicit CAST to string (Teradata casts implicitly)")
    _retarget_tables(tree, target, schema_map, project)
    for sub in list(tree.find_all(exp.Sub)):
        if (
            isinstance(sub.this, (exp.CurrentDate, exp.Column))
            and isinstance(sub.expression, exp.Column)
            and (isinstance(sub.this, exp.CurrentDate) or re.search(r"DATE|_DT$", sub.this.name, re.IGNORECASE))
        ):
            sub.replace(exp.DateDiff(this=sub.this.copy(), expression=sub.expression.copy(), unit=exp.var("DAY")))
            problems.append(f"Date subtraction {sub.sql('teradata')} -> DATEDIFF in days (assumes DATE operands)")
    for fn in list(tree.find_all(exp.Func)):
        if fn.sql_name() == "ADD_MONTHS" or (isinstance(fn, exp.Anonymous) and fn.name.upper() == "ADD_MONTHS"):
            args = fn.expressions if isinstance(fn, exp.Anonymous) else [fn.this, fn.expression]
            if len(args) == 2:
                fn.replace(exp.DateAdd(this=args[0].copy(), expression=args[1].copy(), unit=exp.var("MONTH")))
    for fn in tree.find_all(exp.Anonymous):
        if not fn.name.upper().startswith("TD_"):
            problems.append(f"Unknown function {fn.name}() passed through unchanged")
    out = tree.sql(dialect=DIALECT[target], pretty=True, unsupported_level=sqlglot.ErrorLevel.IGNORE)
    out = render_placeholders(out, target)
    return out, problems


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
        manual = _manual_constructs(pre)
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
        out, problems = transpile_query(pre, target, schema_map, project, numeric_cols)
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
