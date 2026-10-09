"""Small dedicated parser for Teradata CREATE TABLE / COMMENT ON DDL (what sqlglot's dialect does not cover).

Handles SET/MULTISET, table options, column types (incl. CHARACTER SET, [NOT] CASESPECIFIC, COMPRESS,
FORMAT, TITLE, DEFAULT, [NOT] NULL), [UNIQUE] PRIMARY INDEX / NO PRIMARY INDEX, PARTITION BY (RANGE_N,
CASE_N, multi-level), [UNIQUE] INDEX (USI/NUSI), PRIMARY KEY / UNIQUE / FOREIGN KEY ... REFERENCES
[WITH [NO] CHECK OPTION]. Produces `TableMeta` plus the index list needed for DBC.IndicesV.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import ColumnMeta, ForeignKey, Identity, TableMeta, TdBaseType
from .td_catalog import (
    CHAR_TYPES,
    IndexDef,
    finalize,
    keys_from_indexes,
    partition_columns,
)

T = TdBaseType

_TOKEN = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|[A-Za-z_$#][\w$#]*|\d+(?:\.\d+)?|\S""")
_UNITS = ("YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND")
_TYPE_ALIASES = {
    "INT": "INTEGER", "DEC": "DECIMAL", "NUMERIC": "DECIMAL", "REAL": "FLOAT", "CHARACTER": "CHAR",
}  # fmt: skip
_SIZE_MULT = {"K": 1024, "M": 1024**2, "G": 1024**3}


class DDLParseError(ValueError):
    pass


@dataclass
class ParsedTable:
    meta: TableMeta
    indexes: list[IndexDef] = field(default_factory=list)
    fk_names: list[str | None] = field(default_factory=list)
    comment: str | None = None
    options: list[str] = field(default_factory=list)


@dataclass
class _Tok:
    text: str
    start: int
    end: int

    @property
    def up(self) -> str:
        return self.text.upper()


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1].replace(s[0] * 2, s[0])
    return s


def strip_comments(sql: str) -> str:
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in "'\"":
            j = i + 1
            while j < n and not (sql[j] == ch and (j + 1 >= n or sql[j + 1] != ch)):
                j += 2 if sql[j] == ch else 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def split_statements(sql: str) -> list[str]:
    sql = strip_comments(sql)
    stmts, last = [], 0
    for m in _TOKEN.finditer(sql):
        if m.group() == ";":
            stmts.append(sql[last : m.start()].strip())
            last = m.end()
    stmts.append(sql[last:].strip())
    return [s for s in stmts if s]


class _Parser:
    def __init__(self, sql: str):
        self.sql = sql
        self.toks = [_Tok(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(sql)]
        self.i = 0

    # -- token helpers -----------------------------------------------------------------------------
    def peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.toks[j].up if j < len(self.toks) else ""

    def next(self) -> _Tok:
        if self.i >= len(self.toks):
            raise DDLParseError("unexpected end of DDL")
        self.i += 1
        return self.toks[self.i - 1]

    def accept(self, *words: str) -> bool:
        if all(self.peek(k) == w for k, w in enumerate(words)):
            self.i += len(words)
            return True
        return False

    def expect(self, *words: str) -> None:
        if not self.accept(*words):
            raise DDLParseError(f"expected {' '.join(words)!r} near {self.sql[self.pos() : self.pos() + 40]!r}")

    def pos(self) -> int:
        return self.toks[self.i].start if self.i < len(self.toks) else len(self.sql)

    def ident(self) -> str:
        return _unquote(self.next().text)

    def qualified(self) -> tuple[str | None, str]:
        a = self.ident()
        if self.accept("."):
            return a, self.ident()
        return None, a

    def int_(self) -> int:
        return int(self.next().text)

    def balanced(self) -> str:
        """Consume a parenthesised group; return its inner source text."""
        self.expect("(")
        start, depth = self.pos(), 1
        while depth:
            t = self.next()
            depth += {"(": 1, ")": -1}.get(t.text, 0)
            end = t.start
        return self.sql[start:end].strip()

    def ident_list(self) -> list[str]:
        self.expect("(")
        out = [self.ident()]
        while self.accept(","):
            out.append(self.ident())
        self.expect(")")
        return out

    def args(self) -> list[int | None]:
        """Optional '(n[, m])' type arguments; '*' -> None; supports K/M/G size suffixes."""
        if self.peek() != "(":
            return []
        self.next()
        out: list[int | None] = []
        while True:
            t = self.next()
            if t.text == "*":
                out.append(None)
            else:
                v = int(t.text)
                if self.peek() in _SIZE_MULT:
                    v *= _SIZE_MULT[self.next().up]
                out.append(v)
            if self.accept(")"):
                return out
            self.expect(",")

    # -- statements --------------------------------------------------------------------------------
    def create_table(self, default_database: str | None) -> ParsedTable:
        self.expect("CREATE")
        kind = "SET"
        if self.accept("MULTISET"):
            kind = "MULTISET"
        else:
            self.accept("SET")
        while self.peek() in ("GLOBAL", "TEMPORARY", "VOLATILE"):
            self.next()
        self.expect("TABLE")
        db, name = self.qualified()
        options = []
        while self.accept(","):
            start = self.pos()
            while self.peek() not in (",", "(", ""):
                self.next()
            options.append(self.sql[start : self.pos()].strip())
        meta = TableMeta(database=db or default_database or "", name=name, kind=kind)  # type: ignore[arg-type]
        meta.options = options
        pt = ParsedTable(meta=meta, options=options)
        self.expect("(")
        constraints: list[tuple[str, list[str], str | None]] = []
        while True:
            self.element(pt, constraints)
            if self.accept(")"):
                break
            self.expect(",")
        self.tail(pt, constraints)
        return pt

    def element(self, pt: ParsedTable, constraints: list) -> None:
        cname = None
        if self.accept("CONSTRAINT"):
            cname = self.ident()
        w = self.peek()
        if w == "FOREIGN":
            self.expect("FOREIGN", "KEY")
            cols = self.ident_list()
            self.foreign_key(pt, cols, cname)
        elif w == "PRIMARY" and self.peek(1) == "KEY":
            self.i += 2
            constraints.append(("K", self.ident_list(), cname))
        elif w == "UNIQUE":
            self.next()
            constraints.append(("U", self.ident_list(), cname))
        elif w == "CHECK":
            self.next()
            self.balanced()
        else:
            self.column(pt, constraints)

    def foreign_key(self, pt: ParsedTable, cols: list[str], name: str | None) -> None:
        self.expect("REFERENCES")
        enforced = True
        if self.accept("WITH", "NO", "CHECK", "OPTION"):
            enforced = False
        else:
            self.accept("WITH", "CHECK", "OPTION")
        rdb, rtable = self.qualified()
        rcols = self.ident_list() if self.peek() == "(" else list(cols)
        pt.meta.foreign_keys.append(
            ForeignKey(
                columns=cols,
                ref_database=rdb or pt.meta.database,
                ref_table=rtable,
                ref_columns=rcols,
                enforced=enforced,
            )
        )
        pt.fk_names.append(name)

    def column(self, pt: ParsedTable, constraints: list) -> None:
        name = self.ident()
        col = self.data_type(name, len(pt.meta.columns) + 1)
        while self.peek() not in (",", ")", ""):
            if self.accept("CHARACTER", "SET"):
                col.charset = self.next().up  # type: ignore[assignment]
            elif self.accept("NOT", "CASESPECIFIC") or self.accept("NOT", "CS"):
                col.case_specific = False
            elif self.accept("CASESPECIFIC") or self.accept("CS"):
                col.case_specific = True
            elif self.accept("NOT", "NULL"):
                col.nullable = False
            elif self.accept("NULL"):
                col.nullable = True
            elif self.accept("COMPRESS"):
                col.compress_values = []
                if self.peek() == "(":
                    self.next()
                    while not self.accept(")"):
                        t = self.next()
                        if t.text != "," and t.up != "NULL":
                            col.compress_values.append(_unquote(t.text))
                elif self.peek() == "NULL" or (self.peek()[:1] and self.peek()[0] in "'0123456789-"):
                    t = self.next()
                    if t.up != "NULL":
                        col.compress_values.append(_unquote(t.text))
            elif self.accept("FORMAT"):
                col.format = _unquote(self.next().text)
            elif self.accept("TITLE") or self.accept("NAMED"):
                self.next()
            elif self.accept("DEFAULT") or self.accept("WITH", "DEFAULT"):
                col.default = self.default_value()
            elif self.accept("GENERATED"):
                col.identity = self.identity()
            elif self.accept("PRIMARY", "KEY"):
                constraints.append(("K", [name], None))
            elif self.accept("UNIQUE"):
                constraints.append(("U", [name], None))
            elif self.accept("REFERENCES"):
                self.i -= 1
                self.foreign_key(pt, [name], None)
            elif self.accept("CONSTRAINT") or self.peek() in ("UPPERCASE", "UC"):
                self.next()
            elif self.accept("CHECK"):
                self.balanced()
            else:
                raise DDLParseError(f"unsupported column attribute near {self.sql[self.pos() : self.pos() + 40]!r}")
        if col.base_type in CHAR_TYPES:
            col.charset = col.charset or "LATIN"
            col.case_specific = bool(col.case_specific)
        pt.meta.columns.append(finalize(col))

    def identity(self) -> Identity:
        always = self.accept("ALWAYS")
        if not always:
            self.expect("BY", "DEFAULT")
        self.expect("AS", "IDENTITY")
        ident = Identity(always=always)
        if self.peek() == "(":
            body = self.balanced().upper()
            m = re.search(r"START\s+WITH\s+(-?\d+)", body)
            ident.start = int(m.group(1)) if m else 1
            m = re.search(r"INCREMENT\s+BY\s+(-?\d+)", body)
            ident.increment = int(m.group(1)) if m else 1
        return ident

    def default_value(self) -> str:
        start = self.pos()
        t = self.next()
        if t.text in "+-":
            self.next()
        if self.peek() == "(":
            self.balanced()
        elif t.up in ("DATE", "TIME", "TIMESTAMP") and self.peek()[:1] == "'":
            self.next()
        return self.sql[start : self.toks[self.i - 1].end]

    def data_type(self, name: str, ordinal: int) -> ColumnMeta:
        w = _TYPE_ALIASES.get(self.peek(), self.peek())
        self.next()
        col = ColumnMeta(name=name, ordinal=ordinal, base_type=T.INTEGER, td_type="", td_type_code="")
        if w == "DOUBLE":
            self.expect("PRECISION")
            w = "FLOAT"
        if w == "CHAR" and self.accept("VARYING"):
            w = "VARCHAR"
        elif w == "CHAR" and self.accept("LARGE", "OBJECT"):
            w = "CLOB"
        elif w == "BINARY":
            self.expect("LARGE", "OBJECT")
            w = "BLOB"
        elif w == "LONG":
            self.expect("VARCHAR")
            col.base_type, col.length = T.VARCHAR, 64000
            return col
        if w == "INTERVAL":
            return self.interval(col)
        if w == "PERIOD":
            return self.period(col)
        try:
            base = T(w)
        except ValueError as exc:
            raise DDLParseError(f"unsupported data type {w!r} for column {name}") from exc
        col.base_type = base
        a = self.args()
        if base in (T.CHAR, T.BYTE):
            col.length = a[0] if a else 1
        elif base in (T.VARCHAR, T.VARBYTE):
            col.length = a[0]
        elif base in (T.CLOB, T.BLOB):
            col.length = a[0] if a else 2097088000
        elif base == T.DECIMAL:
            col.precision, col.scale = (a[0] if a else 5), (a[1] if len(a) > 1 else 0)
        elif base == T.NUMBER:
            col.precision = a[0] if a else None
            col.scale = (a[1] if len(a) > 1 else 0) if a else None
        elif base in (T.TIME, T.TIMESTAMP):
            col.fractional_seconds = a[0] if a else 6
            if self.accept("WITH", "TIME", "ZONE"):
                col.base_type = T.TIME_TZ if base == T.TIME else T.TIMESTAMP_TZ
        return col

    def interval(self, col: ColumnMeta) -> ColumnMeta:
        col.base_type = T.INTERVAL
        lead = self.next().up
        if lead not in _UNITS:
            raise DDLParseError(f"bad INTERVAL qualifier {lead!r}")
        a = self.args()
        col.precision = a[0] if a else 2
        q = lead
        if lead == "SECOND":
            col.fractional_seconds = a[1] if len(a) > 1 else 6
        if self.accept("TO"):
            end = self.next().up
            q = f"{lead} TO {end}"
            if end == "SECOND":
                b = self.args()
                col.fractional_seconds = b[0] if b else 6
        col.interval_qualifier = q
        return col

    def period(self, col: ColumnMeta) -> ColumnMeta:
        col.base_type = T.PERIOD
        self.expect("(")
        inner = self.next().up
        a = self.args()
        if inner != "DATE":
            col.fractional_seconds = a[0] if a else 6
            if self.accept("WITH", "TIME", "ZONE"):
                inner += " WITH TIME ZONE"
        col.interval_qualifier = inner
        self.expect(")")
        return col

    def tail(self, pt: ParsedTable, constraints: list) -> None:
        pi: IndexDef | None = None
        no_pi = False
        secondary: list[IndexDef] = []
        partition = None
        while self.i < len(self.toks):
            if self.accept(","):
                continue
            unique = self.accept("UNIQUE")
            if self.accept("NO", "PRIMARY", "INDEX"):
                no_pi = True
            elif self.accept("PRIMARY", "AMP") or self.accept("PRIMARY", "INDEX"):
                self.accept("INDEX")
                iname = None if self.peek() == "(" else self.ident()
                pi = IndexDef(1, "P", unique, self.ident_list(), iname)
            elif self.accept("PARTITION", "BY"):
                start = self.pos()
                if self.peek() != "(":
                    self.next()
                self.balanced()
                partition = self.sql[start : self.toks[self.i - 1].end].strip()
            elif self.accept("INDEX"):
                iname = None if self.peek() in ("(", "ALL") else self.ident()
                self.accept("ALL")
                idx = IndexDef(0, "S", unique, self.ident_list(), iname)
                if self.accept("ORDER", "BY"):
                    if not self.accept("VALUES"):
                        self.accept("HASH")
                    self.ident_list()
                secondary.append(idx)
            elif self.peek() in ("WITH", "ON"):
                break
            else:
                raise DDLParseError(f"unsupported table clause near {self.sql[self.pos() : self.pos() + 40]!r}")
        cons = [IndexDef(0, k, True, cols, n) for k, cols, n in constraints]
        if pi is None and not no_pi:
            # Teradata default: PRIMARY KEY, else first UNIQUE, becomes the UPI; else first column NUPI.
            first = next((c for c in cons if c.kind == "K"), None) or next(iter(cons), None)
            if first:
                cons.remove(first)
                pi = IndexDef(1, "P", True, first.columns, first.name)
            else:
                pi = IndexDef(1, "P", False, [pt.meta.columns[0].name])
        if pi and partition:
            pi.kind = "Q"
        others = secondary + [c for c in cons if pi is None or c.columns != pi.columns or not pi.unique]
        for n, idx in enumerate(others, start=1):
            idx.number = 4 * n
        pt.indexes = ([pi] if pi else []) + others
        pt.meta.primary_index, pt.meta.primary_index_unique, pt.meta.unique_keys = keys_from_indexes(pt.indexes)
        if no_pi:
            pt.meta.kind = "MULTISET"
        pt.meta.secondary_indexes = [list(i.columns) for i in secondary]
        pt.meta.partition_expression = partition
        pt.meta.partition_columns = partition_columns(partition, [c.name for c in pt.meta.columns])

    def comment_on(self) -> tuple[str, list[str], str]:
        self.expect("COMMENT", "ON")
        objtype = self.next().up
        parts = [self.ident()]
        while self.accept("."):
            parts.append(self.ident())
        if not (self.accept("IS") or self.accept("AS")):
            raise DDLParseError("expected IS/AS in COMMENT ON")
        return objtype, parts, _unquote(self.next().text)


def parse_ddl(sql: str, default_database: str | None = None) -> list[ParsedTable]:
    """Parse all CREATE TABLE (+ COMMENT ON) statements in `sql`; other statements are ignored."""
    tables: list[ParsedTable] = []
    for stmt in split_statements(sql):
        head = stmt.split(None, 4)
        upper = [h.upper() for h in head]
        if upper[:1] == ["CREATE"] and "TABLE" in upper[1:4]:
            pt = _Parser(stmt).create_table(default_database)
            pt.meta.ddl = stmt + ";"
            tables.append(pt)
        elif upper[:2] == ["COMMENT", "ON"]:
            objtype, parts, text = _Parser(stmt).comment_on()
            _apply_comment(tables, objtype, parts, text)
    return tables


def _apply_comment(tables: list[ParsedTable], objtype: str, parts: list[str], text: str) -> None:
    if objtype == "COLUMN":
        *tbl, colname = parts
    else:
        tbl, colname = parts, None
    for pt in tables:
        if pt.meta.name.upper() == tbl[-1].upper() and (len(tbl) == 1 or pt.meta.database.upper() == tbl[0].upper()):
            if colname is None:
                pt.comment = text
                pt.meta.comment = text
            for c in pt.meta.columns:
                if colname and c.name.upper() == colname.upper():
                    c.comment = text


def parse_table(sql: str, default_database: str | None = None) -> ParsedTable:
    tables = parse_ddl(sql, default_database)
    if len(tables) != 1:
        raise DDLParseError(f"expected exactly one CREATE TABLE, found {len(tables)}")
    return tables[0]
