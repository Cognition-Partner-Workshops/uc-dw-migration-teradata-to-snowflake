"""Teradata macros, stored procedures and BTEQ scripts -> native BigQuery / Redshift / Synapse routines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import sqlglot

from .ddl_render import target_schema
from .models import Conversion, SourceObject, TargetId
from .sql_convert import DIALECT, _rewrite_calls, preprocess, transpile_ex
from .td_ddl import _Parser, split_statements, strip_comments
from .typemap import map_type

FLAGS = re.IGNORECASE | re.DOTALL
_IND = "  "
_ORCHESTRATOR = {
    "bigquery": "Cloud Composer / Workflows or a BigQuery scheduled query",
    "redshift": "Redshift Query Editor scheduler, Step Functions or MWAA",
    "synapse": "an Azure Data Factory / Synapse pipeline",
}


def split_top(s: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    depth, in_str = 0, False
    for ch in s:
        if ch == "'":
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def target_type(td_type: str, target: str) -> str:
    try:
        t = map_type(_Parser(td_type).data_type("x", 0), target).type  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        t = td_type.upper()
    return re.sub(r"\(.*\)", "", t) if target == "bigquery" else t


def _indent(lines: list[str], n: int = 1) -> list[str]:
    return [(_IND * n + ln) if ln else ln for ln in "\n".join(lines).splitlines()]


def _snip(sql: str, n: int = 70) -> str:
    one = " ".join(sql.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def _comment(sql: str, why: str) -> list[str]:
    return [f"-- TODO (manual): {why}"] + [f"--   {ln}" for ln in sql.strip().splitlines()]


@dataclass
class Param:
    mode: str
    name: str
    td_type: str
    default: str | None


_PARAM = re.compile(r"^(?:(IN|OUT|INOUT)\s+)?(\w+)\s+(.+?)(?:\s+FORMAT\s+'[^']*')?(?:\s+DEFAULT\s+(.+?))?$", FLAGS)


def parse_params(text: str | None) -> list[Param]:
    out = []
    for p in split_top(text or ""):
        m = _PARAM.match(p.strip())
        if not m:
            raise ValueError(f"cannot read parameter '{_snip(p, 40)}'")
        out.append(Param((m.group(1) or "IN").upper(), m.group(2), m.group(3).strip(), m.group(4)))
    return out


_PROC = re.compile(
    r"(?:CREATE|REPLACE)\s+PROCEDURE\s+([\w.\"]+)\s*\((.*?)\)\s*(?:SQL\s+SECURITY\s+\w+\s*)?BEGIN\b(.*)\bEND\s*;?\s*$", FLAGS
)
_MACRO = re.compile(r"(?:CREATE|REPLACE)\s+MACRO\s+([\w.\"]+)\s*(?:\((.*?)\))?\s*AS\s*\((.*)\)\s*;?\s*$", FLAGS)


@dataclass
class Ctx:
    obj: SourceObject
    target: str
    schema_map: dict[str, str]
    project: str
    registry: dict[str, SourceObject]
    vars: dict[str, str] = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    temps: set[str] = field(default_factory=set)
    decls: list[str] = field(default_factory=list)

    def name(self, database: str, name: str) -> str:
        schema = target_schema(database or self.obj.database, self.schema_map)
        if self.target == "bigquery":
            return f"`{self.project + '.' if self.project else ''}{schema}.{name}`"
        if self.target == "redshift":
            return f"{schema}.{name.lower()}"
        return f"[{schema}].[{name}]"

    def ref(self, var: str) -> str:
        return f"@{var}" if self.target == "synapse" else var

    def declare(self, var: str, td_type: str, default: str | None = None) -> None:
        if var.upper() in self.vars:
            return
        self.vars[var.upper()] = td_type
        tt = target_type(td_type, self.target)
        d = {"bigquery": " DEFAULT ", "redshift": " := ", "synapse": " = "}[self.target] + default if default else ""
        self.decls.append(
            f"DECLARE @{var} {tt}{d};" if self.target == "synapse" else f"{'DECLARE ' if self.target == 'bigquery' else ''}{var} {tt}{d};"
        )

    def assign(self, var: str, expr: str) -> str:
        if self.target == "redshift":
            return f"{var} := {expr};"
        return f"SET {self.ref(var)} = {expr};"

    def rowcount(self, var: str) -> str:
        self.rules.append(
            "ACTIVITY_COUNT -> "
            + {"bigquery": "@@row_count", "redshift": "GET DIAGNOSTICS ... ROW_COUNT", "synapse": "@@ROWCOUNT"}[self.target]
        )
        if self.target == "redshift":
            return f"GET DIAGNOSTICS {var} := ROW_COUNT;"
        return f"SET {self.ref(var)} = {'@@row_count' if self.target == 'bigquery' else '@@ROWCOUNT'};"

    def lookup(self, name: str, kind: str) -> SourceObject | None:
        n = name.replace('"', "").upper()
        fq = n if "." in n else f"{self.obj.database.upper()}.{n}"
        short = fq.split(".")[-1]
        for o in self.registry.values():
            if o.object_type == kind and (o.fqn.upper() == fq or o.name.upper() in (short, f"MACRO_{short}")):
                return o
        return None


def _outside_strings(sql: str, fn) -> str:
    parts = re.split(r"('(?:[^']|'')*')", sql)
    return "".join(fn(x) if i % 2 == 0 else x for i, x in enumerate(parts))


def _prefix(sql: str, ctx: Ctx) -> str:
    names = sorted(ctx.vars, key=len, reverse=True)
    temps = sorted(ctx.temps, key=len, reverse=True)
    parts = re.split(r"('(?:[^']|'')*')", sql)
    for i in range(0, len(parts), 2):
        if names:
            parts[i] = re.sub(rf"(?<![\w@#.\[])\b({'|'.join(names)})\b(?![\w(.])", r"@\1", parts[i], flags=re.IGNORECASE)
        if temps:
            parts[i] = re.sub(rf"(?<![\w@#.\[])\b({'|'.join(temps)})\b(?![\w(])", r"#\1", parts[i], flags=re.IGNORECASE)
    return "".join(parts)


def tx(ctx: Ctx, td: str) -> str | None:
    """One Teradata statement -> target SQL (no trailing semicolon); None when it cannot be converted safely."""
    s = td.strip().rstrip(";").strip()
    if m := re.search(r"\bSAMPLE\s+(\d+)\s*$", s, re.IGNORECASE):
        s = s[: m.start()] + f"LIMIT {m.group(1)}"
        ctx.rules.append("SAMPLE n -> LIMIT n")
        ctx.warnings.append("SAMPLE n returned n random rows on Teradata; LIMIT n returns the first n rows of the ORDER BY")
    s = _outside_strings(s, lambda t: re.sub(r"\b(SQLCODE|ERRORCODE)\b", r"TD_\1()", t, flags=re.IGNORECASE))
    pre, rules, warnings = preprocess(s)
    try:
        res = transpile_ex(pre, ctx.target, ctx.schema_map, ctx.project, var_types=ctx.vars)
    except Exception as exc:  # noqa: BLE001
        ctx.manual.append(f"Could not translate: {_snip(td)} ({str(exc).splitlines()[0][:100]})")
        return None
    ctx.rules += rules + res.rules
    ctx.warnings += warnings + res.warnings
    ctx.manual += res.manual
    out = res.sql
    out, n = _rewrite_calls(out, "TD_SQLCODE", lambda a: "ERROR_NUMBER()" if ctx.target == "synapse" else "-1")
    if n:
        ctx.rules.append("SQLCODE -> " + ("ERROR_NUMBER()" if ctx.target == "synapse" else "-1 (no numeric error code on this target)"))
    out, _ = _rewrite_calls(
        out, "TD_ERRORCODE", lambda a: {"bigquery": "@@error.message", "redshift": "SQLERRM", "synapse": "ERROR_NUMBER()"}[ctx.target]
    )
    now = {"bigquery": "CURRENT_DATETIME()", "redshift": "GETDATE()", "synapse": "CAST(SYSDATETIME() AS DATETIME2(0))"}[ctx.target]
    out, n = re.subn(r"\b(?:CURRENT_TIMESTAMP|GETDATE)\s*\(\s*\d*\s*\)", now, out, flags=re.IGNORECASE)
    if n:
        ctx.rules.append(f"CURRENT_TIMESTAMP(n) -> {now}")
    if ctx.target == "synapse":
        out = _prefix(out, ctx)
    elif ctx.target == "redshift" and ctx.temps:
        out = re.sub(rf"\b({'|'.join(ctx.temps)})\b", lambda m: m.group(1).lower(), out, flags=re.IGNORECASE)
    try:
        sqlglot.parse_one(out, read=DIALECT[ctx.target])
    except Exception as exc:  # noqa: BLE001
        ctx.manual.append(f"Generated SQL does not re-parse as {ctx.target}: {_snip(td)} ({str(exc).splitlines()[0][:100]})")
        return None
    return out


def tx_expr(ctx: Ctx, td_expr: str) -> str | None:
    out = tx(ctx, f"SELECT {td_expr}")
    return re.sub(r"^\s*SELECT\s+", "", out, flags=re.IGNORECASE).strip() if out else None


_DML = re.compile(r"(SELECT|SEL|INSERT|UPDATE|DELETE|MERGE|WITH)\b", re.IGNORECASE)


def _qualified(ctx: Ctx, ref: str) -> str:
    db, _, name = ref.rpartition(".")
    return ctx.name(db, name)


def stmt(ctx: Ctx, td: str) -> list[str]:
    """A Teradata statement inside a procedure / script body -> target lines."""
    s = td.strip().rstrip(";").strip()
    if m := re.match(r"DECLARE\s+(\w+)\s+(.+?)(?:\s+DEFAULT\s+(.+))?$", s, FLAGS):
        default = tx_expr(ctx, m.group(3)) if m.group(3) else None
        ctx.declare(m.group(1), m.group(2).strip(), default)
        return []
    if m := re.match(r"SET\s+(\w+)\s*=\s*(.+)$", s, FLAGS):
        if re.fullmatch(r"\s*ACTIVITY_COUNT\s*", m.group(2), re.IGNORECASE):
            return [ctx.rowcount(m.group(1))]
        e = tx_expr(ctx, m.group(2))
        return [ctx.assign(m.group(1), e)] if e else _comment(s, "assignment not converted")
    if re.match(r"CREATE\s+(?:MULTISET\s+|SET\s+)?VOLATILE\s+", s, re.IGNORECASE):
        m = re.match(r"CREATE\s+.*?VOLATILE\s+(?:MULTISET\s+|SET\s+)?TABLE\s+(\w+)\s+AS\s*\((.*)\)\s*WITH\s+DATA(.*)$", s, FLAGS)
        if not m:
            ctx.manual.append("VOLATILE TABLE without AS (SELECT ...) WITH DATA")
            return _comment(s, "volatile table definition")
        name, sel, tail = m.group(1), m.group(2), m.group(3)
        out = tx(ctx, sel)
        if out is None:
            return _comment(s, "volatile table query")
        ctx.temps.add(name.upper())
        ctx.rules.append("VOLATILE TABLE -> temporary table")
        pi = re.search(r"PRIMARY\s+INDEX\s*\(\s*(\w+)", tail, re.IGNORECASE)
        if ctx.target == "bigquery":
            return [f"CREATE TEMP TABLE {name} AS", out + ";"]
        if ctx.target == "redshift":
            return [f"CREATE TEMP TABLE {name.lower()}{f' DISTKEY({pi.group(1).lower()})' if pi else ''} AS", out + ";"]
        dist = f"HASH([{pi.group(1)}])" if pi else "ROUND_ROBIN"
        return [f"CREATE TABLE #{name} WITH (DISTRIBUTION = {dist}, HEAP) AS", out + ";"]
    if (m := re.match(r"DROP\s+TABLE\s+(\w+)$", s, re.IGNORECASE)) and m.group(1).upper() in ctx.temps:
        n = m.group(1)
        return [f"DROP TABLE {'#' + n if ctx.target == 'synapse' else n.lower() if ctx.target == 'redshift' else n};"]
    if m := re.match(r"COLLECT\s+STAT(?:ISTICS)?\b(.*?)\bON\s+([\w.]+)(.*)$", s, FLAGS):
        cols = [
            c for c in re.findall(r"COLUMN\s*\(\s*([\w\s,]+?)\s*\)", m.group(1) + m.group(3), re.IGNORECASE) if c.upper() != "PARTITION"
        ]
        tbl = _qualified(ctx, m.group(2))
        ctx.rules.append(
            "COLLECT STATISTICS -> "
            + {"bigquery": "removed (BigQuery maintains statistics)", "redshift": "ANALYZE", "synapse": "UPDATE STATISTICS"}[ctx.target]
        )
        if ctx.target == "bigquery":
            return [f"-- COLLECT STATISTICS on {m.group(2)} removed: BigQuery maintains statistics automatically"]
        if ctx.target == "redshift":
            return [f"ANALYZE {tbl}{' (' + ', '.join(c.lower() for c in cols) + ')' if cols else ''};"]
        return [f"UPDATE STATISTICS {tbl};"]
    if re.match(r"DATABASE\s+\w+$", s, re.IGNORECASE):
        ctx.rules.append("DATABASE x removed (all objects are schema-qualified)")
        return []
    if re.match(r"CALL\b", s, re.IGNORECASE):
        return call(ctx, s)
    if _DML.match(s):
        out = tx(ctx, s)
        return [out + ";"] if out else _comment(s, "statement not converted")
    if re.match(r"(BT|ET|COMMIT|ROLLBACK|ABORT|BEGIN\s+TRANSACTION|END\s+TRANSACTION)\b", s, re.IGNORECASE):
        ctx.manual.append(f"Transaction control statement: {_snip(s, 40)}")
        return _comment(s, "transaction control")
    ctx.manual.append(f"Statement not converted: {_snip(s)}")
    return _comment(s, "statement not converted")


def call(ctx: Ctx, s: str) -> list[str]:
    m = re.match(r"CALL\s+([\w.\"]+)\s*\((.*)\)\s*$", s, FLAGS)
    callee = ctx.lookup(m.group(1), "procedure") if m else None
    hdr = _PROC.search(strip_comments(callee.sql)) if callee else None
    if not m or not callee or not hdr:
        ctx.manual.append(f"CALL to a procedure that is not in the dump: {_snip(s, 50)}")
        return _comment(s, "CALL target not found in the configuration dump")
    params, args = parse_params(hdr.group(2)), split_top(m.group(2))
    if len(params) != len(args):
        ctx.manual.append(f"CALL {callee.name}: {len(args)} arguments for {len(params)} parameters")
        return _comment(s, "argument count mismatch")
    lines, rendered = [], []
    for p, a in zip(params, args, strict=True):
        if p.mode != "IN":
            if not re.fullmatch(r"\w+", a):
                ctx.manual.append(f"CALL {callee.name}: OUT argument {a} is not a variable")
                return _comment(s, "OUT argument")
            ctx.declare(a, p.td_type)
            rendered.append(f"@{a} OUTPUT" if ctx.target == "synapse" else a)
        elif re.fullmatch(r"-?\d+(\.\d+)?|'(?:[^']|'')*'", a) or a.upper() in ctx.vars:
            rendered.append(ctx.ref(a) if a.upper() in ctx.vars else a)
        else:
            e = tx_expr(ctx, a)
            if e is None:
                return _comment(s, "CALL argument")
            v = f"v_{p.name.removeprefix('p_')}"
            ctx.declare(v, p.td_type)
            lines.append(ctx.assign(v, e))
            rendered.append(ctx.ref(v))
    ctx.rules.append(
        "CALL -> " + ("EXEC" if ctx.target == "synapse" else "CALL") + " of the converted procedure (expressions passed via variables)"
    )
    if ctx.target == "redshift" and any(p.mode != "IN" for p in params):
        ctx.warnings.append("Redshift: check that nested CALLs return OUT parameters into the caller's variables")
    name = ctx.name(callee.database, callee.name)
    if ctx.target == "synapse":
        return [*lines, f"EXEC {name} {', '.join(rendered)};"]
    return [*lines, f"CALL {name}({', '.join(rendered)});"]


def _handler(ctx: Ctx, body: list[str], handler: list[str]) -> list[str]:
    if ctx.target == "synapse":
        return ["BEGIN TRY", *_indent(body), "END TRY", "BEGIN CATCH", *_indent(handler or ["THROW;"]), "END CATCH;"]
    kw = "EXCEPTION WHEN ERROR THEN" if ctx.target == "bigquery" else "EXCEPTION WHEN OTHERS THEN"
    return ["BEGIN", *_indent(body), kw, *_indent(handler or ["RAISE;"]), "END;"]


def routine_sql(ctx: Ctx, name: str, params: list[str], body: list[str], kind: str = "PROCEDURE") -> str:
    if ctx.target == "bigquery":
        return "\n".join([f"CREATE OR REPLACE {kind} {name}({', '.join(params)})", "BEGIN", *_indent(ctx.decls), *_indent(body), "END;"])
    if ctx.target == "redshift":
        decl = ["DECLARE", *_indent(ctx.decls)] if ctx.decls else []
        return "\n".join(
            [
                f"CREATE OR REPLACE PROCEDURE {name}({', '.join(params)})",
                "AS $$",
                *decl,
                "BEGIN",
                *_indent(body),
                "END;",
                "$$ LANGUAGE plpgsql;",
            ]
        )
    plist = ["", *_indent([",\n".join(params)])] if params else []
    return "\n".join(
        [
            f"IF OBJECT_ID('{name}', 'P') IS NOT NULL DROP PROCEDURE {name};",
            "GO",
            f"CREATE PROCEDURE {name}" + "\n".join(plist),
            "AS",
            "BEGIN",
            *_indent(["SET NOCOUNT ON;", *ctx.decls, *body]),
            "END;",
            "GO",
        ]
    )


def _param_sql(ctx: Ctx, p: Param, with_default: bool = False) -> str:
    tt = target_type(p.td_type, ctx.target)
    if ctx.target == "bigquery":
        return f"{'' if p.mode == 'IN' else p.mode + ' '}{p.name} {tt}"
    if ctx.target == "redshift":
        return f"{p.name} {'' if p.mode == 'IN' else p.mode + ' '}{tt}"
    return f"@{p.name} {tt}{' OUTPUT' if p.mode != 'IN' else ''}{' = NULL' if with_default and p.default else ''}"


def _missing_refs(ctx: Ctx, sql: str) -> list[str]:
    known = {o.fqn.upper() for o in ctx.registry.values()}
    refs = re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE|USING)\s+(\w+\.\w+)", strip_comments(sql), re.IGNORECASE)
    return sorted({r.upper() for r in refs} - known)


def _td_default(d: str) -> str:
    return re.sub(r"^\s*DATE\b", "CURRENT_DATE", d.strip(), flags=re.IGNORECASE)


def _bind_macro(body: str, params: list[Param], args: dict[str, str] | None, ctx: Ctx | None = None) -> str:
    """Replace :param references with procedure parameters (args=None) or with literal call arguments."""
    for p in params:
        if args is None:
            ref = p.name if p.name.lower().startswith("p_") else f"p_{p.name}"
            val = f"COALESCE({ref}, {_td_default(p.default)})" if p.default else ref
        else:
            val = args.get(p.name.upper()) or (_td_default(p.default) if p.default else "NULL")
        body = re.sub(rf"(?<![\w:]):{p.name}\b", lambda _m, v=val: f"({v})" if args is not None else v, body, flags=re.IGNORECASE)
    return body


def convert_macro(ctx: Ctx) -> tuple[str, int]:
    m = _MACRO.search(strip_comments(ctx.obj.sql))
    if not m:
        raise ValueError("not a CREATE/REPLACE MACRO statement")
    params = parse_params(m.group(2))
    for p in params:
        if p.name.lower().startswith("p_"):
            continue
        p.name = f"p_{p.name}"
    for p in params:
        ctx.vars[p.name.upper()] = p.td_type
    body = _bind_macro(m.group(3), [Param(p.mode, p.name.removeprefix("p_"), p.td_type, p.default) for p in params], None)
    if params:
        ctx.rules.append(":param -> routine parameter p_param")
    if any(p.default for p in params):
        ctx.rules.append("Parameter DEFAULT -> COALESCE(p_param, default); pass NULL to use the default")
    stmts = split_statements(body)
    selects = [s for s in stmts if re.match(r"(SEL|SELECT|WITH)\b", s.strip(), re.IGNORECASE)]
    name = ctx.name(ctx.obj.database, ctx.obj.name)
    psql = [_param_sql(ctx, p, with_default=True) for p in params]
    if len(selects) > 1:
        ctx.warnings.append(f"Macro returns {len(selects)} result sets; callers must read each one")
    if ctx.target == "bigquery" and len(stmts) == 1 and selects:
        out = tx(ctx, selects[0])
        ctx.rules.append("Macro -> table function")
        sql = (
            f"CREATE OR REPLACE TABLE FUNCTION {name}({', '.join(psql)})\nAS (\n" + "\n".join(_indent([out or "-- not converted"])) + "\n);"
        )
        usage = f"-- Usage: SELECT * FROM {name}({', '.join(p.name for p in params)});"
        return usage + "\n" + sql, len(selects)
    body_lines: list[str] = []
    k = 0
    for s in stmts:
        if s in selects:
            out = tx(ctx, s)
            if out is None:
                body_lines += _comment(s, "query not converted")
            elif ctx.target == "redshift":
                k += 1
                psql.append(f"rs{k} INOUT REFCURSOR")
                body_lines += [f"OPEN rs{k} FOR", out + ";"]
            else:
                body_lines.append(out + ";")
        else:
            body_lines += stmt(ctx, s)
    ctx.rules.append(
        "Macro -> "
        + {
            "bigquery": "procedure (each SELECT returns a result set)",
            "redshift": "procedure returning one REFCURSOR per SELECT",
            "synapse": "procedure",
        }[ctx.target]
    )
    names = ", ".join(p.name for p in params)
    cursors = [f"'rs{i}'" for i in range(1, k + 1)]
    fetch = " ".join(f"FETCH ALL FROM rs{i};" for i in range(1, k + 1))
    usage = {
        "bigquery": f"-- Usage: CALL {name}({names});",
        "redshift": f"-- Usage: BEGIN; CALL {name}({', '.join([x for x in [names, *cursors] if x])}); {fetch} COMMIT;",
        "synapse": f"-- Usage: EXEC {name} {', '.join('@' + p.name + ' = ...' for p in params)};",
    }[ctx.target]
    return usage + "\n" + routine_sql(ctx, name, psql, body_lines), len(selects)


def convert_procedure(ctx: Ctx) -> str:
    m = _PROC.search(strip_comments(ctx.obj.sql))
    if not m:
        raise ValueError("not a CREATE/REPLACE PROCEDURE statement")
    params = parse_params(m.group(2))
    for p in params:
        ctx.vars[p.name.upper()] = p.td_type
    stmts = split_statements(m.group(3))
    main: list[str] = []
    handler_src: list[str] | None = None
    i = 0
    while i < len(stmts):
        st = stmts[i].strip()
        if h := re.match(r"DECLARE\s+(EXIT|CONTINUE)\s+HANDLER\s+FOR\s+(\w+)\s*(BEGIN\b)?\s*(.*)$", st, FLAGS):
            block = [h.group(4)] if h.group(4).strip() else []
            if h.group(3):
                i += 1
                while i < len(stmts) and stmts[i].strip().upper() != "END":
                    block.append(stmts[i])
                    i += 1
            if h.group(1).upper() != "EXIT" or h.group(2).upper() != "SQLEXCEPTION":
                ctx.manual.append(
                    f"{h.group(1).upper()} HANDLER FOR {h.group(2).upper()} (only EXIT HANDLER FOR SQLEXCEPTION is converted)"
                )
            handler_src = block
        else:
            main.append(st)
        i += 1
    body: list[str] = []
    for st in main:
        body += stmt(ctx, st)
    if handler_src is not None:
        handler: list[str] = []
        for st in handler_src:
            handler += stmt(ctx, st)
        ctx.rules.append(
            "EXIT HANDLER FOR SQLEXCEPTION -> "
            + {"bigquery": "EXCEPTION WHEN ERROR", "redshift": "EXCEPTION WHEN OTHERS", "synapse": "BEGIN TRY / BEGIN CATCH"}[ctx.target]
        )
        body = _handler(ctx, body, handler)
    ctx.rules.append(
        "Stored procedure -> "
        + {"bigquery": "BigQuery scripting procedure", "redshift": "PL/pgSQL procedure", "synapse": "T-SQL procedure"}[ctx.target]
    )
    return routine_sql(ctx, ctx.name(ctx.obj.database, ctx.obj.name), [_param_sql(ctx, p) for p in params], body)


# ---------------------------------------------------------------- BTEQ


def _bteq_ops(text: str) -> list[tuple[str, str, str]]:
    ops: list[tuple[str, str, str]] = []
    buf: list[str] = []
    for line in strip_comments(text).splitlines():
        st = line.strip()
        if not buf and st.startswith("."):
            m = re.match(r"\.(\w+)\s*(.*?)\s*;?\s*$", st)
            if m:
                ops.append(("dot", m.group(1).upper(), m.group(2)))
            continue
        if st:
            buf.append(line)
        if st.endswith(";"):
            ops += [("sql", s, "") for s in split_statements("\n".join(buf))]
            buf = []
    ops += [("sql", s, "") for s in split_statements("\n".join(buf))]
    return ops


_IF = re.compile(r"^(ACTIVITYCOUNT|ERRORCODE)\s*(=|<>|\^=|!=|>=|<=|>|<)\s*(\d+)\s+THEN\s+\.(GOTO\s+(\w+)|QUIT\s*(\d*))\s*$", re.IGNORECASE)


@dataclass
class _Bteq:
    labels: dict[str, list[tuple[str, str, str]]]
    error_label: str | None = None
    error_quit: str | None = None
    used: set[str] = field(default_factory=set)
    sep: str = "|"
    export: tuple[str, str] | None = None


def _quit(ctx: Ctx, code: str, last: bool) -> list[str]:
    code = code or "0"
    if code != "0" and ctx.target != "synapse":
        ctx.warnings.append(
            f".QUIT {code}: procedures on this target have no exit code; the run ends successfully. Map it in {_ORCHESTRATOR[ctx.target]}"
        )
    if last:
        return []
    return [f"RETURN {code};" if ctx.target == "synapse" else "RETURN;"]


def _reraise(ctx: Ctx, code: str) -> list[str]:
    msg = f"{ctx.obj.name} failed (BTEQ exit code {code or '8'})"
    if ctx.target == "bigquery":
        return [f"RAISE USING MESSAGE = CONCAT('{msg}: ', @@error.message);"]
    if ctx.target == "redshift":
        return [f"RAISE EXCEPTION '{msg}: %', SQLERRM;"]
    return [f"DECLARE @err NVARCHAR(2048) = CONCAT(N'{msg}: ', ERROR_MESSAGE());", "THROW 50000, @err, 1;"]


def _strip_order(sql: str) -> tuple[str, bool]:
    out = re.sub(r"\s+ORDER\s+BY\s+[^()]*$", "", sql.strip().rstrip(";"), flags=FLAGS)
    return out, out != sql.strip().rstrip(";")


def _export(ctx: Ctx, st: _Bteq, sel: str, part: str = "") -> list[str]:
    mode, path = st.export or ("DATA", "export.txt")
    p = PurePosixPath(path)
    folder, stem, ext = str(p.parent).strip("/"), p.stem + part, p.suffix or ".txt"
    report = mode == "REPORT"
    ctx.rules.append(
        ".EXPORT FILE -> "
        + {"bigquery": "EXPORT DATA to Cloud Storage", "redshift": "UNLOAD to S3", "synapse": "CETAS external table"}[ctx.target]
    )
    ctx.warnings.append(
        "Export destination placeholders ("
        + {"bigquery": "EXPORT_BUCKET", "redshift": "EXPORT_BUCKET, IAM role ARN", "synapse": "export_data_source, export_delimited_text"}[
            ctx.target
        ]
        + ") must be set before running"
    )
    if ctx.target == "synapse":
        sel, dropped = _strip_order(sel)
        if dropped:
            ctx.warnings.append("CETAS exports cannot keep ORDER BY; file row order is not guaranteed")
        if report:
            ctx.warnings.append(".EXPORT REPORT headers / titles are not written by CETAS")
    out = tx(ctx, sel)
    if out is None:
        return _comment(sel, "export query not converted")
    if ctx.target == "bigquery":
        uri = f"gs://EXPORT_BUCKET/{folder}/{stem}_*{ext}"
        return [
            f"EXPORT DATA OPTIONS (uri = '{uri}', format = 'CSV', overwrite = true, header = {str(report).lower()}, field_delimiter = '{st.sep}') AS",
            out + ";",
        ]
    if ctx.target == "redshift":
        esc = out.replace("'", "''")
        return [
            f"UNLOAD ('{esc}')",
            f"TO 's3://EXPORT_BUCKET/{folder}/{stem}_'",
            "IAM_ROLE 'arn:aws:iam::ACCOUNT_ID:role/REDSHIFT_UNLOAD_ROLE'",
            f"DELIMITER '{st.sep}'{' HEADER' if report else ''} ALLOWOVERWRITE PARALLEL OFF;",
        ]
    ext_name = ctx.name(ctx.obj.database, "ext_" + re.sub(r"\W", "_", stem))
    return [
        f"IF OBJECT_ID('{ext_name}') IS NOT NULL DROP EXTERNAL TABLE {ext_name};",
        f"CREATE EXTERNAL TABLE {ext_name}",
        f"WITH (LOCATION = '/{folder}/{stem}/', DATA_SOURCE = [export_data_source], FILE_FORMAT = [export_delimited_text])",
        "AS",
        out + ";",
    ]


def _exec(ctx: Ctx, st: _Bteq, s: str) -> list[str]:
    m = re.match(r"EXEC(?:UTE)?\s+([\w.\"]+)\s*(?:\((.*)\))?\s*$", s, FLAGS)
    macro = ctx.lookup(m.group(1), "macro") if m else None
    hdr = _MACRO.search(strip_comments(macro.sql)) if macro else None
    if not m or not macro or not hdr:
        ctx.manual.append(f"EXEC of a macro that is not in the dump: {_snip(s, 50)}")
        return _comment(s, "macro not found in the configuration dump")
    params, args = parse_params(hdr.group(2)), split_top(m.group(2) or "")
    bound: dict[str, str] = {}
    for i, a in enumerate(args):
        if kv := re.match(r"(\w+)\s*=\s*(.+)$", a, FLAGS):
            bound[kv.group(1).upper()] = kv.group(2)
        elif i < len(params):
            bound[params[i].name.upper()] = a
    if st.export:
        body = _bind_macro(hdr.group(3), params, bound)
        sels = [x for x in split_statements(body) if re.match(r"(SEL|SELECT|WITH)\b", x.strip(), re.IGNORECASE)]
        ctx.rules.append("EXEC macro under .EXPORT -> macro queries inlined into the export")
        lines: list[str] = []
        for i, sel in enumerate(sels, 1):
            lines += _export(ctx, st, sel, f"_part{i}" if len(sels) > 1 else "")
        return lines
    rendered = []
    for p in params:
        a = bound.get(p.name.upper())
        rendered.append((tx_expr(ctx, a) or "NULL") if a else "NULL")
    name = ctx.name(macro.database, macro.name)
    ctx.rules.append("EXEC macro -> call of the converted macro routine")
    if ctx.target == "redshift":
        ctx.warnings.append(
            "Redshift: macro result sets are cursors and are not shown in the script log; run the macro separately to see them"
        )
        return [
            f"-- EXEC {macro.name}: result sets are returned as cursors; run separately:",
            f"-- CALL {name}({', '.join(rendered)}, 'rs1');",
        ]
    if ctx.target == "synapse":
        return [f"EXEC {name} {', '.join(rendered)};"]
    single = len([x for x in split_statements(hdr.group(3))]) == 1
    return [f"SELECT * FROM {name}({', '.join(rendered)});" if single else f"CALL {name}({', '.join(rendered)});"]


def _emit(ctx: Ctx, st: _Bteq, ops: list[tuple[str, str, str]], top: bool, in_handler: bool = False) -> list[str]:
    lines: list[str] = []
    for idx, (kind, a, b) in enumerate(ops):
        last = top and idx == len(ops) - 1
        if kind == "dot":
            if a == "LOGON":
                ctx.rules.append(
                    ".LOGON removed: connection and credentials come from the scheduler, not the script (credentials not copied)"
                )
            elif a in ("LOGOFF", "EXIT") and not b:
                pass
            elif a == "SET":
                if sm := re.match(r"SEPARATOR\s+'(.)'", b, re.IGNORECASE):
                    st.sep = sm.group(1)
                ctx.rules.append(".SET session/format options removed")
            elif a == "EXPORT":
                if re.match(r"RESET\b", b, re.IGNORECASE):
                    st.export = None
                elif em := re.match(r"(DATA|REPORT|INDICDATA)?\s*FILE\s*=\s*(\S+)", b, re.IGNORECASE):
                    st.export = ((em.group(1) or "DATA").upper(), em.group(2))
                else:
                    ctx.manual.append(f".EXPORT {b} not understood")
            elif a == "IF" and (im := _IF.match(b)):
                var, op, n, goto, quit_code = im.group(1).upper(), im.group(2), im.group(3), im.group(5), im.group(6)
                if var == "ERRORCODE":
                    continue
                op = {"^=": "<>", "!=": "<>"}.get(op, op)
                if goto:
                    block = st.labels.get(goto.upper())
                    if block is None:
                        ctx.manual.append(f".GOTO {goto}: label not found")
                        continue
                    st.used.add(goto.upper())
                    inner = _emit(ctx, st, block, top=False)
                else:
                    inner = _quit(ctx, quit_code, last=False)
                ctx.declare("v_activity_count", "INTEGER")
                ctx.rules.append(".IF ACTIVITYCOUNT ... THEN .GOTO label -> IF ... THEN <label steps>; RETURN; END IF")
                lines += [f"IF {ctx.ref('v_activity_count')} {op} {n} {'BEGIN' if ctx.target == 'synapse' else 'THEN'}", *_indent(inner)]
                lines.append("END;" if ctx.target == "synapse" else "END IF;")
            elif a == "QUIT":
                code = (re.match(r"\d*", b) or re.match("", "")).group(0)  # type: ignore[union-attr]
                lines += _reraise(ctx, code) if in_handler else _quit(ctx, code, last)
            else:
                ctx.manual.append(f"BTEQ command .{a} {_snip(b, 30)} not converted")
                lines += _comment(f".{a} {b}", "BTEQ command")
            continue
        s = a.strip().rstrip(";")
        needs_count = False
        for k2, a2, b2 in ops[idx + 1 :]:
            if k2 == "sql":
                break
            if a2 == "IF" and re.match(r"ACTIVITYCOUNT\b", b2, re.IGNORECASE):
                needs_count = True
        is_select = bool(re.match(r"(SEL|SELECT|WITH)\b", s, re.IGNORECASE))
        if re.match(r"EXEC(UTE)?\b", s, re.IGNORECASE):
            lines += _exec(ctx, st, s)
        elif is_select and st.export:
            lines += _export(ctx, st, s)
        elif is_select:
            out = tx(ctx, s)
            if out is None:
                lines += _comment(s, "query not converted")
            elif ctx.target == "redshift":
                ctx.warnings.append("Redshift: informational SELECTs of the script are not returned by a procedure; kept as comments")
                lines += ["-- Log output (not returned by a Redshift procedure):"] + [f"-- {ln}" for ln in out.splitlines()]
            else:
                lines.append(out + ";")
        else:
            lines += stmt(ctx, s)
        if needs_count:
            ctx.declare("v_activity_count", "INTEGER")
            if is_select:
                cnt = tx(ctx, f"SELECT COUNT(*) FROM ({_strip_order(s)[0]}) AS q")
                if cnt:
                    lines.append(ctx.assign("v_activity_count", f"({cnt})"))
                    ctx.rules.append("ACTIVITYCOUNT after a SELECT -> COUNT(*) over the same query")
                    ctx.warnings.append("ACTIVITYCOUNT is computed by running the query a second time as COUNT(*)")
            elif _DML.match(s):
                lines.append(ctx.rowcount("v_activity_count"))
            else:
                ctx.manual.append(f"ACTIVITYCOUNT after {_snip(s, 30)}")
    return lines


def convert_bteq(ctx: Ctx) -> str:
    ops = _bteq_ops(ctx.obj.sql)
    labels: dict[str, list[tuple[str, str, str]]] = {}
    main: list[tuple[str, str, str]] = []
    cur = main
    for op in ops:
        if op[0] == "dot" and op[1] == "LABEL":
            cur = labels.setdefault(op[2].strip().upper(), [])
        else:
            cur.append(op)
    st = _Bteq(labels)
    for kind, a, b in ops:
        if kind == "dot" and a == "IF" and (im := _IF.match(b)) and im.group(1).upper() == "ERRORCODE":
            if im.group(5):
                st.error_label = im.group(5).upper()
            else:
                st.error_quit = im.group(6) or "8"
        elif kind == "dot" and a == "GOTO":
            ctx.manual.append(f"Unconditional .GOTO {b}")
    body = _emit(ctx, st, main, top=True)
    if st.error_label or st.error_quit:
        handler: list[str] = []
        if st.error_label in labels:
            st.used.add(st.error_label)
            handler = _emit(ctx, st, labels[st.error_label], top=False, in_handler=True)
        if not any("RAISE" in h or "THROW" in h for h in handler):
            handler += _reraise(ctx, st.error_quit or "8")
        ctx.rules.append(".IF ERRORCODE <> 0 THEN .GOTO handler -> exception handler that re-raises the error")
        body = _handler(ctx, body, handler)
    else:
        ctx.warnings.append("BTEQ continues after a failed statement unless ERRORCODE is checked; the target stops at the first error")
    for name in set(labels) - st.used:
        ctx.manual.append(f".LABEL {name} is never reached by a converted .GOTO")
    ctx.rules.append(f"BTEQ script -> stored procedure; schedule it with {_ORCHESTRATOR[ctx.target]}")
    name = ctx.name(ctx.obj.database, ctx.obj.name)
    run = f"-- Run: {'EXEC' if ctx.target == 'synapse' else 'CALL'} {name}{'' if ctx.target == 'synapse' else '()'};"
    return run + "\n" + routine_sql(ctx, name, [], body)


def convert_routine(
    obj: SourceObject, target: TargetId, schema_map: dict[str, str], project: str, registry: dict[str, SourceObject]
) -> Conversion:
    ctx = Ctx(obj, target, schema_map, project, registry)
    label = {"macro": "macro", "procedure": "stored procedure", "bteq_script": "BTEQ script"}[obj.object_type]
    if obj.object_type == "macro":
        sql, _ = convert_macro(ctx)
    elif obj.object_type == "procedure":
        sql = convert_procedure(ctx)
    else:
        sql = convert_bteq(ctx)
    missing = [m for m in _missing_refs(ctx, obj.sql) if m.split(".")[-1] not in ctx.temps]
    if missing:
        ctx.warnings.append(f"Uses objects that are not in the configuration dump: {', '.join(missing)}; create or map them first")
    header = f"-- Source: {obj.fqn} ({label}) from {obj.source_file}\n"
    manual = list(dict.fromkeys(ctx.manual))
    if manual:
        header += "".join(f"-- MANUAL REVIEW: {m}\n" for m in manual)
    return Conversion(
        object_id=obj.id,
        target=target,
        status="manual_review" if manual else "converted_with_warnings" if ctx.warnings else "converted",
        sql=header + sql + "\n",
        rules=list(dict.fromkeys(ctx.rules)),
        warnings=list(dict.fromkeys(ctx.warnings)),
        reason="; ".join(manual[:3]) if manual else None,
    )
