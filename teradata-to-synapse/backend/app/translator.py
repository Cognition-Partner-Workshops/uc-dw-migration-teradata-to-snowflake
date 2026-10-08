"""Rule-based Teradata -> Azure Synapse (dedicated SQL pool) T-SQL translator."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .sqltext import (
    collapse_ws,
    depth_map,
    finditer_code,
    mask,
    matching_paren,
    split_statements,
    split_top_level,
    strip_block_comments,
    strip_line_comments,
    sub_code,
)

TABLE, VIEW, MACRO, PROCEDURE, SCRIPT = "table", "view", "macro", "stored_procedure", "script"
OBJECT_TYPES = (TABLE, VIEW, MACRO, PROCEDURE, SCRIPT)
AUTO_CONVERTIBLE = (TABLE, VIEW)

CONVERTED = "converted"
CONVERTED_WITH_WARNINGS = "converted_with_warnings"
MANUAL_REVIEW = "manual_review"
FAILED = "failed"

_IDENT = r'(?:"[^"]+"|[A-Za-z_$#][\w$#]*)'
_QNAME = rf"{_IDENT}(?:\s*\.\s*{_IDENT})?"


@dataclass
class TranslationResult:
    sql: str
    status: str
    rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_reason: str | None = None

    def rule(self, msg: str) -> None:
        if msg not in self.rules:
            self.rules.append(msg)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify(rel_path: str, text: str) -> tuple[str, str]:
    """Return (object_type, object_name) for a Teradata source file."""
    code = mask(text)
    stem = rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if rel_path.lower().endswith((".bteq", ".btq")) or re.search(
        r"^\s*\.(LOGON|RUN|EXPORT|IMPORT)\b", code, re.I | re.M
    ):
        return SCRIPT, stem
    patterns = (
        (MACRO, rf"\b(?:CREATE|REPLACE)\s+MACRO\s+({_QNAME})"),
        (PROCEDURE, rf"\b(?:CREATE|REPLACE)\s+PROCEDURE\s+({_QNAME})"),
        (VIEW, rf"\b(?:CREATE|REPLACE)\s+(?:OR\s+REPLACE\s+)?(?:RECURSIVE\s+)?VIEW\s+({_QNAME})"),
        (TABLE, rf"\bCREATE\s+(?:(?:SET|MULTISET)\s+)?(?:(?:GLOBAL\s+TEMPORARY|VOLATILE)\s+)?TABLE\s+({_QNAME})"),
    )
    for obj_type, pat in patterns:
        m = re.search(pat, code, re.I)
        if m:
            return obj_type, collapse_ws(text[m.start(1) : m.end(1)]).replace(" ", "")
    return SCRIPT, stem


# --------------------------------------------------------------------------- #
# Data types and column definitions
# --------------------------------------------------------------------------- #

_TYPE_RE = re.compile(
    r"""^(?P<base>
        LONG\s+VARCHAR | DOUBLE\s+PRECISION | CHARACTER\s+VARYING | CHAR\s+VARYING
        | TIMESTAMP | TIME | INTERVAL\s+\w+(?:\s+TO\s+\w+)? | [A-Z_]+
    )
    (?P<args>\s*\([^)]*\))?
    (?P<tz>\s+WITH\s+TIME\s+ZONE)?""",
    re.I | re.X,
)


def map_type(base: str, args: str | None, tz: str | None, res: TranslationResult) -> str:
    b = collapse_ws(base).upper()
    a = (args or "").replace(" ", "")
    if b == "BYTEINT":
        res.rule("BYTEINT -> SMALLINT")
        return "SMALLINT"
    if b in ("INTEGER", "INT"):
        return "INT"
    if b == "TIMESTAMP":
        if tz:
            res.rule("TIMESTAMP WITH TIME ZONE -> DATETIMEOFFSET")
            return f"DATETIMEOFFSET{a}"
        res.rule("TIMESTAMP(n) -> DATETIME2(n)")
        return f"DATETIME2{a}"
    if b == "TIME":
        return f"TIME{a}"
    if b in ("CHARACTER", "CHAR"):
        return f"CHAR{a}"
    if b in ("VARCHAR", "CHARACTER VARYING", "CHAR VARYING"):
        return f"VARCHAR{a}"
    if b == "LONG VARCHAR":
        res.rule("LONG VARCHAR -> VARCHAR(8000)")
        return "VARCHAR(8000)"
    if b == "CLOB":
        res.rule("CLOB -> VARCHAR(MAX)")
        return "VARCHAR(MAX)"
    if b == "BLOB":
        res.rule("BLOB -> VARBINARY(MAX)")
        return "VARBINARY(MAX)"
    if b == "BYTE":
        return f"BINARY{a}"
    if b == "VARBYTE":
        return f"VARBINARY{a}"
    if b in ("NUMBER", "NUMERIC", "DECIMAL", "DEC"):
        if b == "NUMBER":
            res.rule("NUMBER -> DECIMAL")
            return f"DECIMAL{a}" if a and a != "(*)" else "DECIMAL(38,10)"
        return f"DECIMAL{a}"
    if b in ("FLOAT", "REAL", "DOUBLE PRECISION"):
        return "FLOAT"
    if b.startswith("INTERVAL") or b in ("PERIOD", "JSON", "XML", "ST_GEOMETRY"):
        res.warn(f"Data type {b} has no direct Synapse equivalent; mapped to VARCHAR(100) - review.")
        return "VARCHAR(100)"
    return f"{b}{a}"


_COLUMN_ATTR_DROPS = (
    (r"\bCHARACTER\s+SET\s+\w+", "CHARACTER SET clauses dropped"),
    (
        r"\bNOT\s+CASESPECIFIC\b|\bCASESPECIFIC\b|\bNOT\s+CS\b",
        "CASESPECIFIC / NOT CASESPECIFIC dropped (use a CI/CS collation if needed)",
    ),
    (r"\bUPPERCASE\b", "UPPERCASE attribute dropped"),
    (r"\bFORMAT\s+'[^']*'", "Column FORMAT clauses dropped"),
    (r"\bTITLE\s+'[^']*'", "Column TITLE clauses dropped"),
    (
        r"\bCOMPRESS\s*\([^)]*\)|\bCOMPRESS\s+'[^']*'|\bCOMPRESS\s+-?[\d.]+|\bCOMPRESS\s+NULL\b|\bCOMPRESS\b",
        "COMPRESS value lists dropped (clustered columnstore compresses automatically)",
    ),
)

_NON_CONSTANT_DEFAULTS = (
    r"CURRENT_TIMESTAMP(?:\s*\(\s*\d\s*\))?|CURRENT_DATE|CURRENT_TIME(?:\s*\(\s*\d\s*\))?|DATE|TIME|USER"
)


@dataclass
class Column:
    name: str
    sql: str
    is_identity: bool
    comments: list[str]


def translate_column(text: str, res: TranslationResult) -> Column | None:
    body, comments = strip_line_comments(text)
    body = collapse_ws(body)
    if not body:
        return None
    m = re.match(rf"^({_IDENT})\s+(.*)$", body, re.S)
    if not m:
        res.warn(f"Could not parse column definition: {body}")
        return Column(body, body, False, comments)
    name, rest = m.group(1), m.group(2)
    tm = _TYPE_RE.match(rest)
    if not tm:
        res.warn(f"Could not parse data type for column {name}")
        return Column(name, body, False, comments)
    col_type = map_type(tm.group("base"), tm.group("args"), tm.group("tz"), res)
    attrs = rest[tm.end() :]

    for pat, rule in _COLUMN_ATTR_DROPS:
        attrs, n = sub_code(pat, attrs, " ")
        if n:
            res.rule(rule)

    identity = ""
    im = re.search(r"\bGENERATED\s+(ALWAYS|BY\s+DEFAULT)\s+AS\s+IDENTITY\s*(\((?P<opts>[^)]*)\))?", attrs, re.I)
    if im:
        opts = im.group("opts") or ""
        start = re.search(r"START\s+WITH\s+(-?\d+)", opts, re.I)
        inc = re.search(r"INCREMENT\s+BY\s+(-?\d+)", opts, re.I)
        identity = f"IDENTITY({start.group(1) if start else 1},{inc.group(1) if inc else 1})"
        attrs = attrs[: im.start()] + " " + attrs[im.end() :]
        res.rule("GENERATED ... AS IDENTITY -> IDENTITY(seed,increment)")

    default = ""
    dm = re.search(
        r"\bDEFAULT\s+(?P<val>'(?:[^']|'')*'|-?[\d.]+|NULL\b|(?:TIMESTAMP|DATE|TIME)\s+'[^']*'|"
        + _NON_CONSTANT_DEFAULTS
        + ")",
        attrs,
        re.I,
    )
    if dm:
        val = dm.group("val")
        attrs = attrs[: dm.start()] + " " + attrs[dm.end() :]
        lit = re.match(r"(?:TIMESTAMP|DATE|TIME)\s+('[^']*')", val, re.I)
        if lit:
            default = f"DEFAULT {lit.group(1)}"
            res.rule("Typed literal defaults (TIMESTAMP '...') -> string literal defaults")
        elif re.fullmatch(_NON_CONSTANT_DEFAULTS, val, re.I):
            res.warn(
                f"Column {name}: DEFAULT {collapse_ws(val)} removed - Synapse dedicated SQL pool only "
                "allows constant DEFAULT expressions; populate it in the load (e.g. GETDATE())."
            )
        else:
            default = f"DEFAULT {val}"

    not_null = ""
    attrs, n = sub_code(r"\bNOT\s+NULL\b", attrs, " ")
    if n or identity:
        not_null = "NOT NULL"
    attrs, _ = sub_code(r"\bNULL\b", attrs, " ")

    leftover = collapse_ws(attrs)
    if re.search(r"\b(PRIMARY\s+KEY|UNIQUE|REFERENCES)\b", leftover, re.I):
        res.warn(f"Column {name}: inline constraint '{leftover}' dropped - Synapse constraints must be NOT ENFORCED.")
        leftover = ""
    if leftover:
        res.warn(f"Column {name}: unrecognised attributes kept as comment: {leftover}")
        comments = comments + [f"TD attr: {leftover}"]

    parts = [col_type]
    if identity:
        parts.append(identity)
    if not_null:
        parts.append(not_null)
    if default:
        parts.append(default)
    return Column(name, f"{name:<28}{' '.join(parts)}", bool(identity), comments)


# --------------------------------------------------------------------------- #
# CREATE TABLE
# --------------------------------------------------------------------------- #


def _add_interval(d: date, n: int, unit: str) -> date:
    unit = unit.upper()
    if unit == "DAY":
        return date.fromordinal(d.toordinal() + n)
    months = n * (12 if unit == "YEAR" else 1)
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, d.day)


def translate_partition(clause: str, res: TranslationResult) -> str | None:
    m = re.search(
        rf"RANGE_N\s*\(\s*({_IDENT})\s+BETWEEN\s+(?:DATE\s+)?'(\d{{4}}-\d{{2}}-\d{{2}})'\s+AND\s+(?:DATE\s+)?"
        rf"'(\d{{4}}-\d{{2}}-\d{{2}})'\s+EACH\s+INTERVAL\s+'(\d+)'\s+(DAY|MONTH|YEAR)",
        clause,
        re.I,
    )
    if m:
        col, start, end, step, unit = m.groups()
        cur, stop, bounds = date.fromisoformat(start), date.fromisoformat(end), []
        while cur <= stop and len(bounds) < 15000:
            bounds.append(f"'{cur.isoformat()}'")
            cur = _add_interval(cur, int(step), unit)
        res.rule("PARTITION BY RANGE_N(...) -> PARTITION (col RANGE RIGHT FOR VALUES (...))")
        if len(bounds) > 60:
            res.warn(
                f"{len(bounds)} partitions generated from RANGE_N on {col}. Synapse spreads every partition across 60 "
                "distributions; consider coarser (e.g. yearly) partitions so each holds >= 1M rows per distribution."
            )
        lines = [", ".join(bounds[i : i + 6]) for i in range(0, len(bounds), 6)]
        values = (",\n" + " " * 12).join(lines)
        return f"PARTITION ( {col} RANGE RIGHT FOR VALUES (\n            {values}\n        ))"
    m = re.search(rf"RANGE_N\s*\(\s*({_IDENT})\s+BETWEEN\s+(-?\d+)\s+AND\s+(-?\d+)\s+EACH\s+(\d+)", clause, re.I)
    if m:
        col, lo, hi, step = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        bounds = [str(v) for v in range(lo, hi + 1, step)][:15000]
        res.rule("PARTITION BY RANGE_N(...) -> PARTITION (col RANGE RIGHT FOR VALUES (...))")
        return f"PARTITION ( {col} RANGE RIGHT FOR VALUES ({', '.join(bounds)}) )"
    res.warn(f"Partitioning clause not auto-converted: {collapse_ws(clause)}")
    return None


def _cols(s: str) -> list[str]:
    return [c.strip() for c in s.split(",") if c.strip()]


def translate_create_table(stmt: str, res: TranslationResult) -> str:
    code = mask(stmt)
    hm = re.search(
        rf"\bCREATE\s+(?P<kind>(?:SET|MULTISET)\s+)?(?P<temp>(?:GLOBAL\s+TEMPORARY|VOLATILE)\s+)?TABLE\s+(?P<name>{_QNAME})",
        code,
        re.I,
    )
    assert hm
    name = collapse_ws(stmt[hm.start("name") : hm.end("name")]).replace(" ", "")
    if hm.group("kind"):
        res.rule("SET / MULTISET table kind dropped")
        if hm.group("kind").strip().upper() == "SET":
            res.warn(f"{name} was a SET table: Synapse does not reject duplicate rows - deduplicate during load.")
    if hm.group("temp"):
        res.warn("VOLATILE / GLOBAL TEMPORARY table: create as a #temp table in the session instead.")
    open_idx = code.find("(", hm.end())
    options = code[hm.end() : open_idx]
    if re.search(r"\bAS\s*$", options, re.I) or re.search(r"\bAS\b", options, re.I):
        raise ValueError("CREATE TABLE ... AS (CTAS) statements are not auto-converted")
    if re.search(r"FALLBACK", options, re.I):
        res.rule("FALLBACK / NO FALLBACK clause dropped")
    if re.search(r"JOURNAL", options, re.I):
        res.rule("JOURNAL clauses dropped")
    if re.search(r"CHECKSUM", options, re.I):
        res.rule("CHECKSUM clause dropped")
    if re.search(r"MERGEBLOCKRATIO|DATABLOCKSIZE|FREESPACE|BLOCKCOMPRESSION|\bMAP\s*=", options, re.I):
        res.rule("Physical storage options (MERGEBLOCKRATIO, DATABLOCKSIZE, ...) dropped")

    close_idx = matching_paren(code, open_idx)
    body = stmt[open_idx + 1 : close_idx]
    tail = stmt[close_idx + 1 :]

    columns: list[Column] = []
    for element in split_top_level(body):
        # A '-- comment' right after the previous comma belongs to the previous column.
        first_line, _, remainder = element.partition("\n")
        if columns and first_line.strip().startswith("--"):
            columns[-1].comments.append(first_line.strip()[2:].strip())
            element = remainder
        if re.match(r"^\s*(CONSTRAINT|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK)\b", mask(element), re.I):
            res.warn(f"Table constraint dropped (Synapse requires NOT ENFORCED constraints): {collapse_ws(element)}")
            continue
        col = translate_column(element, res)
        if col:
            columns.append(col)

    tcode = mask(tail)
    pi_cols: list[str] = []
    pi_unique = False
    no_pi = bool(re.search(r"\bNO\s+PRIMARY\s+INDEX\b", tcode, re.I))
    pim = re.search(rf"\b(UNIQUE\s+)?PRIMARY\s+INDEX\s*(?:{_IDENT}\s*)?\(([^)]*)\)", tcode, re.I)
    if pim:
        pi_cols = _cols(tail[pim.start(2) : pim.end(2)])
        pi_unique = bool(pim.group(1))
    secondary: list[list[str]] = []
    for sm in re.finditer(rf"\b(UNIQUE\s+)?INDEX\s*(?:{_IDENT}\s*)?\(([^)]*)\)", tcode, re.I):
        if pim and pim.start() <= sm.start() < pim.end():
            continue
        secondary.append(_cols(tail[sm.start(2) : sm.end(2)]))
    if secondary:
        res.rule("Secondary INDEX definitions dropped (columnstore + statistics replace NUSIs)")

    partition = None
    ppm = re.search(r"\bPARTITION\s+BY\b", tcode, re.I)
    if ppm:
        partition = translate_partition(tail[ppm.end() :], res)

    identity_cols = {c.name.upper() for c in columns if c.is_identity}
    if pi_cols:
        dist_col = pi_cols[0]
        if len(pi_cols) > 1:
            res.warn(
                f"Multi-column primary index ({', '.join(pi_cols)}): hash-distributed on the first column {dist_col}."
            )
        if dist_col.upper() in identity_cols:
            alt = next((s[0] for s in secondary if len(s) == 1 and s[0].upper() not in identity_cols), None)
            msg = f"Primary index column {dist_col} is an IDENTITY column, which Synapse cannot hash-distribute on; "
            if alt:
                res.warn(msg + f"distributed on secondary index column {alt} instead.")
                dist = f"HASH({alt})"
            else:
                res.warn(msg + "falling back to ROUND_ROBIN.")
                dist = "ROUND_ROBIN"
        else:
            dist = f"HASH({dist_col})"
        res.rule("PRIMARY INDEX (col) -> WITH (DISTRIBUTION = HASH(col), CLUSTERED COLUMNSTORE INDEX)")
        if pi_unique:
            res.warn(
                f"UNIQUE PRIMARY INDEX on {', '.join(pi_cols)} is not enforced in Synapse - "
                "add PRIMARY KEY NONCLUSTERED ... NOT ENFORCED if the optimizer should know about it."
            )
    else:
        dist = "ROUND_ROBIN"
        res.rule("NO PRIMARY INDEX -> DISTRIBUTION = ROUND_ROBIN")
        if not no_pi:
            res.warn("No primary index declared (Teradata would default one); using ROUND_ROBIN distribution.")

    lines = []
    for i, c in enumerate(columns):
        sep = "," if i < len(columns) - 1 else ""
        comment = f"  -- {'; '.join(c.comments)}" if c.comments else ""
        lines.append(f"    {c.sql}{sep}{comment}")
    with_parts = [f"DISTRIBUTION = {dist}", "CLUSTERED COLUMNSTORE INDEX"]
    if partition:
        with_parts.append(partition)
    with_sql = ",\n".join(f"    {p}" for p in with_parts)
    return f"CREATE TABLE {name}\n(\n" + "\n".join(lines) + f"\n)\nWITH\n(\n{with_sql}\n);"


def translate_collect_stats(stmt: str, res: TranslationResult) -> str | None:
    s = collapse_ws(strip_line_comments(strip_block_comments(stmt))[0])
    m = re.search(
        rf"COLLECT\s+STAT(?:ISTICS|S)?\s+(?:USING\s+.*?\s+)?COLUMN\s*\(([^)]*)\)\s+ON\s+({_QNAME})", s, re.I
    ) or re.search(rf"COLLECT\s+STAT(?:ISTICS|S)?\s+ON\s+({_QNAME})\s+COLUMN\s*\(([^)]*)\)", s, re.I)
    if not m:
        res.warn(f"COLLECT STATISTICS not converted: {s}")
        return None
    if m.re.pattern.startswith("COLLECT") and "ON\\s+(" in m.re.pattern[:60]:
        table, cols = m.group(1), m.group(2)
    else:
        cols, table = m.group(1), m.group(2)
    cols_l = _cols(cols)
    if any(c.upper() == "PARTITION" for c in cols_l):
        res.rule("COLLECT STATISTICS on PARTITION dropped (no equivalent)")
        return None
    res.rule("COLLECT STATISTICS -> CREATE STATISTICS")
    tname = table.split(".")[-1].strip('"')
    stat_name = f"stat_{tname}_{'_'.join(c.strip(chr(34)) for c in cols_l)}"
    return f"CREATE STATISTICS {stat_name} ON {table} ({', '.join(cols_l)});"


def translate_comment(stmt: str, res: TranslationResult) -> str:
    res.rule("COMMENT ON ... preserved as SQL comments")
    s = collapse_ws(strip_block_comments(stmt))
    return f"-- {s}"


# --------------------------------------------------------------------------- #
# Query-level rewrites (views and manual-review drafts)
# --------------------------------------------------------------------------- #


def _block_select(code: str, depths: list[int], pos: int) -> int | None:
    """Position of the SELECT keyword that starts the query block containing ``pos``."""
    d = depths[pos]
    i = pos
    while i > 0:
        i -= 1
        if depths[i] < d:
            break
        if (
            depths[i] == d
            and code[i] in "Ss"
            and re.match(r"SELECT\b", code[i:], re.I)
            and (i == 0 or not re.match(r"[\w$#.]", code[i - 1]))
        ):
            return i
    return None


def _top_level_kw(code: str, depths: list[int], start: int, end: int, kw: str) -> int | None:
    d = depths[start]
    for m in re.finditer(rf"\b{kw}\b", code[start:end], re.I):
        p = start + m.start()
        if depths[p] == d:
            return p
    return None


def _item_name(item: str) -> str | None:
    s = collapse_ws(strip_line_comments(item)[0])
    m = re.search(rf"\bAS\s+({_IDENT})$", s, re.I)
    if m:
        return m.group(1)
    m = re.fullmatch(rf"(?:{_IDENT}\s*\.\s*)*({_IDENT})", s)
    if m:
        return m.group(1) if s != "*" else None
    m = re.search(rf"\)\s+({_IDENT})$", s)
    if m and m.group(1).upper() not in ("END",):
        return m.group(1)
    m = re.search(rf"\bEND\s+({_IDENT})$", s, re.I)
    if m:
        return m.group(1)
    return None


def _item_expr(item: str) -> str:
    s = item.strip()
    m = re.search(rf"\s+AS\s+{_IDENT}\s*$", mask(s), re.I)
    if m:
        return s[: m.start()].strip()
    m = re.search(rf"(\)|\bEND)\s+{_IDENT}\s*$", mask(s), re.I)
    if m:
        return s[: m.start() + len(m.group(1))].strip()
    return s


def rewrite_group_by_ordinals(sql: str, res: TranslationResult) -> str:
    while True:
        code = mask(sql)
        depths = depth_map(code)
        m = None
        for cand in re.finditer(r"\bGROUP\s+BY\s+(\d+(?:\s*,\s*\d+)*)\b(?!\s*[.\w(])", code, re.I):
            m = cand
            break
        if not m:
            return sql
        sel = _block_select(code, depths, m.start())
        frm = _top_level_kw(code, depths, sel, m.start(), "FROM") if sel is not None else None
        if sel is None or frm is None:
            res.warn("GROUP BY ordinal could not be resolved; rewrite manually.")
            return sql
        items = split_top_level(sql[sel + 6 : frm])
        exprs = []
        for num in _cols(m.group(1)):
            idx = int(num) - 1
            if idx >= len(items):
                res.warn(f"GROUP BY ordinal {num} out of range; rewrite manually.")
                return sql
            exprs.append(collapse_ws(_item_expr(items[idx])))
        res.rule("GROUP BY <ordinal> -> GROUP BY <expression> (T-SQL has no positional GROUP BY)")
        sql = sql[: m.start(1)] + ", ".join(exprs) + sql[m.end(1) :]


def _find_window_calls(expr: str) -> list[tuple[int, int]]:
    code = mask(expr)
    spans = []
    for m in re.finditer(r"\b\w+\s*\(", code):
        if spans and m.start() < spans[-1][1]:
            continue
        try:
            close = matching_paren(code, m.end() - 1)
        except ValueError:
            continue
        om = re.match(r"\s*OVER\s*\(", code[close + 1 :], re.I)
        if not om:
            continue
        over_open = close + 1 + om.end() - 1
        over_close = matching_paren(code, over_open)
        spans.append((m.start(), over_close + 1))
    return spans


def rewrite_qualify(sql: str, res: TranslationResult) -> str:
    """QUALIFY <window predicate>  ->  ROW_NUMBER()/window column in a derived table + outer WHERE."""
    counter = 0
    while True:
        code = mask(sql)
        depths = depth_map(code)
        quals = [m for m in re.finditer(r"\bQUALIFY\b", code, re.I)]
        if not quals:
            return sql
        q = max(quals, key=lambda m: depths[m.start()])  # innermost first
        qpos, d = q.start(), depths[q.start()]
        sel = _block_select(code, depths, qpos)
        if sel is None:
            res.warn("QUALIFY without a resolvable SELECT block; rewrite manually.")
            return sql
        frm = _top_level_kw(code, depths, sel, qpos, "FROM")
        # End of the QUALIFY predicate: close of enclosing paren, ';', or ORDER BY / UNION at same depth.
        end = len(sql)
        for i in range(q.end(), len(code)):
            if depths[i] < d or (code[i] == ")" and depths[i] == d):
                end = i
                break
            if depths[i] == d and (
                code[i] == ";" or re.match(r"(ORDER\s+BY|UNION|EXCEPT|INTERSECT|MINUS)\b", code[i:], re.I)
            ):
                if i == 0 or not re.match(r"\w", code[i - 1]):
                    end = i
                    break
        qexpr = sql[q.end() : end].strip()
        tail_kw = sql[end:]
        order_tail = ""
        if re.match(r"ORDER\s+BY", mask(tail_kw), re.I):
            # ORDER BY at the end of the block moves to the outer query.
            stop = len(tail_kw)
            tcode = mask(tail_kw)
            td = depth_map(tcode)
            for i, ch in enumerate(tcode):
                if td[i] < 0 or (ch == ")" and td[i] == 0) or (ch == ";" and td[i] == 0):
                    stop = i
                    break
            order_tail = tail_kw[:stop]
            end += stop
            res.warn(
                "ORDER BY moved to the outer query of a QUALIFY rewrite; verify column references use the 'q.' alias."
            )
        # Teradata allows GROUP BY / HAVING after QUALIFY: those belong to the inner query.
        inner_extra = ""
        qcode = mask(qexpr)
        qdepths = depth_map(qcode)
        gm = next((m for m in re.finditer(r"\b(GROUP\s+BY|HAVING)\b", qcode, re.I) if qdepths[m.start()] == 0), None)
        if gm:
            inner_extra = qexpr[gm.start() :].strip()
            qexpr = qexpr[: gm.start()].strip()
        if frm is None:
            res.warn("QUALIFY block without FROM; rewrite manually.")
            return sql
        select_kw_end = sel + 6
        mod = re.match(r"\s+(DISTINCT\s+|TOP\s+\d+\s+(?:WITH\s+TIES\s+)?)", code[select_kw_end:frm], re.I)
        modifier = ""
        list_start = select_kw_end
        if mod:
            modifier = collapse_ws(mod.group(1)) + " "
            list_start = select_kw_end + mod.end()
        select_list = sql[list_start:frm].rstrip()
        from_rest = sql[frm:qpos].rstrip()
        items = split_top_level(select_list)
        names = [_item_name(i) for i in items]

        spans = _find_window_calls(qexpr)
        if not spans:
            res.warn(f"QUALIFY predicate without a window function: {collapse_ws(qexpr)}; rewrite manually.")
            return sql
        new_cols, pred, last = [], [], 0
        for s, e in spans:
            counter += 1
            alias = "qualify_rn" if len(spans) == 1 and counter == 1 else f"qualify_rn{counter}"
            new_cols.append(f"{collapse_ws(qexpr[s:e])} AS {alias}")
            pred.append(qexpr[last:s] + f"q.{alias}")
            last = e
        pred.append(qexpr[last:])
        predicate = collapse_ws("".join(pred))

        line_start = sql.rfind("\n", 0, sel) + 1
        indent = re.match(r"[ \t]*", sql[line_start:sel]).group(0)
        inner_indent = indent + "    "
        if all(names) and len({n.upper() for n in names}) == len(names):
            outer_cols = (",\n" + indent + "       ").join(f"q.{n}" for n in names)
        else:
            outer_cols = "q.*"
            res.warn(
                "QUALIFY rewrite: select list has unnamed/duplicate expressions, outer query uses q.* "
                "(exposes the helper qualify_rn column) - alias every column and rewrite."
            )
        base = sql[line_start:sel]
        if "\n" in select_list:
            item_lead = re.search(r"\n([ \t]*)\S", select_list).group(1)
            col_indent = _rebase_indent(item_lead, base, inner_indent)
            inner = _rebase(f"SELECT{select_list}", base, inner_indent)
            inner += "".join(f",\n{col_indent}{c}" for c in new_cols)
        else:
            inner = f"SELECT {select_list.strip()}, " + ", ".join(new_cols)
        from_block = _rebase(from_rest.strip(), base, inner_indent)
        if inner_extra:
            from_block += f"\n{inner_indent}{inner_extra}"
        rewritten = (
            f"SELECT {modifier}{outer_cols}\n{indent}FROM (\n{inner_indent}{inner}\n{inner_indent}{from_block}\n"
            f"{indent}) AS q\n{indent}WHERE {predicate}"
        )
        if order_tail:
            known = {n.upper(): n for n in names if n}
            order_tail = re.sub(
                rf"(?:{_IDENT}\s*\.\s*)+({_IDENT})",
                lambda m, known=known: f"q.{known[m.group(1).upper()]}" if m.group(1).upper() in known else m.group(0),
                order_tail,
            )
            rewritten += f"\n{indent}{order_tail.strip()}"
        res.rule("QUALIFY -> ROW_NUMBER()/window column in a derived table filtered by an outer WHERE")
        trailing = "" if sql[end : end + 1] in (")", ";", "") else "\n"
        sql = sql[:sel] + rewritten + trailing + sql[end:].lstrip(" \t")


def _rebase_indent(line_indent: str, old_base: str, new_base: str) -> str:
    """Re-express an indentation relative to ``old_base`` on top of ``new_base``."""
    rel = len(line_indent) - len(old_base) if len(line_indent) >= len(old_base) else 0
    return new_base + " " * rel


def _rebase(text: str, old_base: str, new_base: str) -> str:
    """Shift every continuation line of ``text`` from ``old_base`` indentation to ``new_base``."""
    lines = text.split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        lead = re.match(r"[ \t]*", line).group(0)
        out.append(_rebase_indent(lead, old_base, new_base) + line[len(lead) :] if line.strip() else "")
    return "\n".join(out)


def _rewrite_call(sql: str, fname: str, builder, res: TranslationResult, rule: str) -> str:
    """Rewrite FNAME(args) using builder(list_of_args) -> str, innermost-safe left-to-right."""
    guard = 0
    while guard < 500:
        guard += 1
        code = mask(sql)
        m = re.search(rf"(?<![\w.$#]){fname}\s*\(", code, re.I)
        if not m:
            return sql
        close = matching_paren(code, m.end() - 1)
        args = [a.strip() for a in split_top_level(sql[m.end() : close])]
        new = builder(args)
        if new is None:
            res.warn(f"{fname}() call could not be rewritten automatically: {collapse_ws(sql[m.start():close + 1])}")
            new = "/*TODO*/" + sql[m.start() : close + 1].replace(fname, fname.lower(), 1)
        else:
            res.rule(rule)
        sql = sql[: m.start()] + new + sql[close + 1 :]
    return sql


def expand_shorthand(sql: str, res: TranslationResult) -> str:
    for short, full in (("SEL", "SELECT"), ("INS", "INSERT"), ("UPD", "UPDATE"), ("DEL", "DELETE")):
        sql, n = sub_code(rf"(?<![\w.$#]){short}(?![\w.$#])", sql, full)
        if n:
            res.rule(f"{short} shorthand -> {full}")
    return sql


def translate_query(sql: str, res: TranslationResult) -> str:
    """Apply the expression/query rewrite rules to a SQL body."""
    sql = expand_shorthand(sql, res)

    sql, n = sub_code(r"\bLOCK(?:ING)?\s+(?:ROW|TABLE\s+\S+|DATABASE\s+\S+|VIEW\s+\S+)?\s*FOR\s+ACCESS\b\s*", sql, "")
    if n:
        res.rule(
            "LOCKING ROW FOR ACCESS dropped (Synapse readers do not block writers; use READ UNCOMMITTED if needed)"
        )

    sql, n = sub_code(
        r"\s*\(\s*(?:FORMAT\s+'[^']*'|TITLE\s+'[^']*'|NOT\s+CASESPECIFIC|CASESPECIFIC|NAMED\s+\w+)\s*\)", sql, ""
    )
    if n:
        res.rule("Inline (FORMAT '...') / (NOT CASESPECIFIC) attributes dropped - format in the presentation layer")
    sql, n = sub_code(r"\s+FORMAT\s+'[^']*'(?=\s*\))", sql, "")
    if n:
        res.rule("CAST(... FORMAT '...') format phrases dropped")

    sql = _rewrite_call(
        sql, "ZEROIFNULL", lambda a: f"ISNULL({a[0]}, 0)" if len(a) == 1 else None, res, "ZEROIFNULL(x) -> ISNULL(x, 0)"
    )
    sql = _rewrite_call(
        sql, "NULLIFZERO", lambda a: f"NULLIF({a[0]}, 0)" if len(a) == 1 else None, res, "NULLIFZERO(x) -> NULLIF(x, 0)"
    )
    sql = _rewrite_call(
        sql,
        "ADD_MONTHS",
        lambda a: f"DATEADD(MONTH, {a[1]}, {a[0]})" if len(a) == 2 else None,
        res,
        "ADD_MONTHS(d, n) -> DATEADD(MONTH, n, d)",
    )

    has_group_by = any(True for _ in finditer_code(r"\bGROUP\s+BY\b", sql))

    def csum(a: list[str]) -> str | None:
        if len(a) < 2:
            return None
        return f"SUM({a[0]}) OVER (ORDER BY {', '.join(a[1:])} ROWS UNBOUNDED PRECEDING)"

    def mavg(a: list[str]) -> str | None:
        if len(a) < 3 or not a[1].isdigit():
            return None
        return f"AVG({a[0]}) OVER (ORDER BY {', '.join(a[2:])} ROWS BETWEEN {int(a[1]) - 1} PRECEDING AND CURRENT ROW)"

    before = sql
    sql = _rewrite_call(sql, "CSUM", csum, res, "CSUM(x, o) -> SUM(x) OVER (ORDER BY o ROWS UNBOUNDED PRECEDING)")
    sql = _rewrite_call(
        sql, "MAVG", mavg, res, "MAVG(x, n, o) -> AVG(x) OVER (ORDER BY o ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW)"
    )
    if sql != before and has_group_by:
        res.warn(
            "Teradata CSUM/MAVG combined with GROUP BY treat the GROUP BY columns as reset (partition) keys; "
            "verify the generated OVER (...) clauses need a PARTITION BY."
        )

    def hashrow(args: list[str]) -> str:
        parts = ", '|', ".join(args) if len(args) > 1 else f"{args[0]}, ''"
        return f"HASHBYTES('SHA2_256', CONCAT({parts}))"

    sql = _rewrite_call(sql, "HASHROW", hashrow, res, "HASHROW(...) -> HASHBYTES('SHA2_256', CONCAT(...))")
    if "HASHBYTES('SHA2_256'" in sql:
        res.warn("HASHROW replaced by HASHBYTES: hash values differ from Teradata - do not compare across platforms.")

    sql, n = sub_code(
        r"\bCURRENT_DATE\s*([-+])\s*(\d+)\b",
        sql,
        lambda g, m: f"DATEADD(DAY, {'-' if g(1) == '-' else ''}{g(2)}, CAST(GETDATE() AS DATE))",
    )
    if n:
        res.rule("CURRENT_DATE +/- n -> DATEADD(DAY, +/-n, CAST(GETDATE() AS DATE))")
    sql, n = sub_code(
        rf"\bCURRENT_DATE\s*-\s*((?:{_IDENT}\.)?{_IDENT})",
        sql,
        lambda g, m: f"DATEDIFF(DAY, {g(1)}, CAST(GETDATE() AS DATE))",
    )
    if n:
        res.rule("CURRENT_DATE - date_col -> DATEDIFF(DAY, date_col, CAST(GETDATE() AS DATE))")
    sql, n = sub_code(r"\bCURRENT_DATE\b", sql, "CAST(GETDATE() AS DATE)")
    if n:
        res.rule("CURRENT_DATE -> CAST(GETDATE() AS DATE)")
    sql, n = sub_code(r"\bCURRENT_TIMESTAMP\s*\(\s*\d\s*\)", sql, "SYSDATETIME()")
    if n:
        res.rule("CURRENT_TIMESTAMP(n) -> SYSDATETIME()")
    sql, n = sub_code(r"\bDATE\s+('\d{4}-\d{2}-\d{2}')", sql, lambda g, m: f"CAST({g(1)} AS DATE)")
    if n:
        res.rule("DATE 'yyyy-mm-dd' literal -> CAST('yyyy-mm-dd' AS DATE)")
    sql, n = sub_code(r"\bTIMESTAMP\s+('[^']*')", sql, lambda g, m: f"CAST({g(1)} AS DATETIME2)")
    if n:
        res.rule("TIMESTAMP '...' literal -> CAST('...' AS DATETIME2)")
    sql, n = sub_code(r"\bBYTEINT\b", sql, "SMALLINT")
    if n:
        res.rule("BYTEINT -> SMALLINT")
    sql, n = sub_code(r"(?<![\w.])TIMESTAMP\s*(\(\s*\d\s*\))", sql, lambda g, m: f"DATETIME2{g(1).replace(' ', '')}")
    if n:
        res.rule("TIMESTAMP(n) -> DATETIME2(n)")
    sql, n = sub_code(r"\s+CHARACTER\s+SET\s+\w+", sql, "")
    if n:
        res.rule("CHARACTER SET clauses dropped")

    sql, n = sub_code(r"\|\|", sql, "+")
    if n:
        res.rule("|| string concatenation -> +")
        res.warn("'||' replaced by '+': non-character operands need CAST/CONCAT in T-SQL.")

    sql = rewrite_group_by_ordinals(sql, res)
    sql = rewrite_qualify(sql, res)

    code = mask(sql)
    for pat, msg in (
        (
            r"\bSAMPLE\s+\d",
            "SAMPLE clause has no direct Synapse equivalent (use TABLESAMPLE or TOP ... ORDER BY NEWID()).",
        ),
        (r"\bHASHBUCKET\b|\bHASHAMP\b", "HASHBUCKET/HASHAMP functions have no Synapse equivalent."),
        (r"\bTOP\s+\d+\s+WITH\s+TIES\b", "TOP n WITH TIES requires ORDER BY in T-SQL."),
        (r"\b(SUM|AVG|MIN|MAX|COUNT)\s*\((?:[^()]|\([^()]*\))*\(\s*SELECT\b", None),
    ):
        if re.search(pat, code, re.I | re.S):
            res.warn(
                msg
                or "Subquery inside an aggregate function: T-SQL cannot aggregate an expression containing a "
                "subquery - rewrite as a join."
            )
    return sql


def translate_view(stmt: str, res: TranslationResult) -> str:
    code = mask(stmt)
    m = re.search(rf"\b(?:CREATE\s+OR\s+REPLACE|REPLACE|CREATE)\s+(?:RECURSIVE\s+)?VIEW\s+({_QNAME})", code, re.I)
    assert m
    if not re.match(r"CREATE\s+VIEW", code[m.start() :], re.I):
        res.rule("REPLACE VIEW -> CREATE VIEW")
    name = collapse_ws(stmt[m.start(1) : m.end(1)]).replace(" ", "")
    rest = stmt[m.end() :]
    return f"CREATE VIEW {name}" + translate_query(rest, res).rstrip() + ";"


# --------------------------------------------------------------------------- #
# Manual review
# --------------------------------------------------------------------------- #

_FEATURE_PATTERNS = (
    (r"^\s*\.LOGON\b", ".LOGON (BTEQ session)"),
    (r"^\s*\.IF\b", ".IF ERRORCODE / ACTIVITYCOUNT branching"),
    (r"^\s*\.(GOTO|LABEL)\b", ".GOTO / .LABEL control flow"),
    (r"^\s*\.EXPORT\b", ".EXPORT file output"),
    (r"^\s*\.IMPORT\b", ".IMPORT file input"),
    (r"^\s*\.QUIT\b", ".QUIT return codes"),
    (r"\bMERGE\s+INTO\b", "MERGE INTO"),
    (r"\bACTIVITY_COUNT\b", "ACTIVITY_COUNT"),
    (r"\bVOLATILE\s+TABLE\b", "VOLATILE TABLE"),
    (r"\bQUALIFY\b", "QUALIFY"),
    (r"\bCALL\b", "CALL"),
    (r"\bEXEC(UTE)?\b", "EXEC macro"),
    (r"\bSAMPLE\b", "SAMPLE"),
    (r"\bCSUM\b|\bMAVG\b|\bMSUM\b", "Teradata OLAP functions (CSUM/MAVG/MSUM)"),
    (r"\bHASHROW\b", "HASHROW"),
    (r"\bUPDATE\s+\w+(\.\w+)?\s+\w*\s*FROM\b", "UPDATE ... FROM (Teradata join-update syntax)"),
    (r"\bDECLARE\b.*\bHANDLER\b", "DECLARE ... HANDLER error handling"),
    (r"\bSEL\b|\bINS\b|\bUPD\b|\bDEL\b", "SEL/INS/UPD/DEL shorthand"),
    (r":\w+", "Macro/parameter placeholders (:param)"),
)

_MANUAL_GUIDANCE = {
    SCRIPT: "BTEQ scripts mix client commands (.LOGON/.IF/.EXPORT) with SQL. Re-implement orchestration in "
    "Azure Data Factory / Synapse Pipelines (or sqlcmd + PowerShell) and move SQL steps into "
    "T-SQL stored procedures.",
    MACRO: "Teradata macros have no Synapse equivalent. Convert to a T-SQL stored procedure (params become @params) "
    "or an inline table-valued function / parameterised view.",
    PROCEDURE: "Teradata SPL procedures must be rewritten to T-SQL: ACTIVITY_COUNT -> @@ROWCOUNT, handlers -> "
    "TRY/CATCH, VOLATILE tables -> #temp tables; verify UPDATE ... FROM join syntax and MERGE semantics.",
}


def detect_features(text: str) -> list[str]:
    code = mask(text)
    return [label for pat, label in _FEATURE_PATTERNS if re.search(pat, code, re.I | re.M | re.S)]


def manual_review(object_type: str, text: str) -> TranslationResult:
    res = TranslationResult(sql="", status=MANUAL_REVIEW, manual_reason=_MANUAL_GUIDANCE[object_type])
    for f in detect_features(text):
        res.warn(f"Teradata feature: {f}")
    draft = translate_query(strip_block_comments(text).strip(), TranslationResult(sql="", status=""))
    res.sql = (
        "-- MANUAL REVIEW REQUIRED - not emitted to synapse_ddl/\n"
        f"-- {_MANUAL_GUIDANCE[object_type]}\n"
        "-- Draft below has mechanical rules applied (shorthand, functions, QUALIFY) only.\n\n" + draft
    )
    return res


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def translate(object_type: str, text: str, rel_path: str = "", object_name: str = "") -> TranslationResult:
    if object_type not in AUTO_CONVERTIBLE:
        return manual_review(object_type, text)
    res = TranslationResult(sql="", status=CONVERTED)
    out: list[str] = []
    try:
        for stmt in split_statements(strip_block_comments(text)):
            code = mask(stmt).strip()
            if re.match(r"CREATE\s+(?:(?:SET|MULTISET)\s+)?(?:(?:GLOBAL\s+TEMPORARY|VOLATILE)\s+)?TABLE\b", code, re.I):
                out.append(translate_create_table(stmt.strip(), res))
            elif re.match(r"(?:CREATE\s+OR\s+REPLACE|REPLACE|CREATE)\s+(?:RECURSIVE\s+)?VIEW\b", code, re.I):
                out.append(translate_view(stmt.strip(), res))
            elif re.match(r"COLLECT\s+STAT", code, re.I):
                s = translate_collect_stats(stmt, res)
                if s:
                    out.append(s)
            elif re.match(r"COMMENT\s+ON\b", code, re.I):
                out.append(translate_comment(stmt, res))
            elif re.match(r"DATABASE\s+\w+", code, re.I):
                res.rule("DATABASE <name> statement dropped (use schema-qualified names)")
            else:
                res.warn(f"Statement not auto-converted, carried over as comment: {collapse_ws(stmt)[:120]}")
                out.append("-- TODO (not converted): " + collapse_ws(stmt))
    except Exception as exc:  # noqa: BLE001 - surface any parse failure as a manual-review item
        return TranslationResult(
            sql=f"-- Conversion failed: {exc}\n",
            status=FAILED,
            rules=res.rules,
            warnings=res.warnings + [f"Conversion failed: {exc}"],
            manual_reason=f"Automatic conversion failed ({exc}); convert by hand.",
        )

    header = (
        "-- ==========================================================================\n"
        f"-- Azure Synapse Analytics (dedicated SQL pool) T-SQL\n"
        f"-- Source : {rel_path or '<inline>'}\n"
        f"-- Object : {object_name} ({object_type})\n"
        "-- Generated by td2synapse rule-based translator\n"
        "-- ==========================================================================\n"
    )
    stats = [s for s in out if s.startswith("CREATE STATISTICS")]
    comments = [s for s in out if s.startswith("-- ")]
    main = [s for s in out if s not in stats and s not in comments]
    body = "\n\n".join(main)
    if stats:
        body += "\n\n" + "\n".join(stats)
    if comments:
        body += "\n\n" + "\n".join(comments)
    res.sql = header + "\n" + body + "\n"
    if res.warnings:
        res.status = CONVERTED_WITH_WARNINGS
    return res
