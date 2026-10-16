"""Small, dependency-free helpers for working with raw SQL text."""

from __future__ import annotations

import re
from collections.abc import Callable

_OBJECT_RE = re.compile(
    r"\b(?:CREATE|REPLACE)\s+(?:OR\s+REPLACE\s+)?(?:SET\s+|MULTISET\s+|TRANSIENT\s+|SECURE\s+)?"
    r"(TABLE|VIEW)\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
    re.IGNORECASE,
)


def strip_comments(sql: str) -> str:
    """Remove ``/* */`` and ``--`` comments while leaving string literals intact."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """Split comment-free SQL on top-level semicolons."""
    stmts: list[str] = []
    buf: list[str] = []
    in_str = False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
        if ch == ";" and not in_str:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def object_of(stmt: str) -> tuple[str, str] | None:
    """Return ``(kind, NAME)`` for a CREATE/REPLACE TABLE|VIEW statement."""
    m = _OBJECT_RE.search(stmt)
    if not m:
        return None
    return m.group(1).upper(), m.group(2).upper()


def matching_paren(text: str, open_idx: int) -> int:
    """Index of the parenthesis closing the one at ``open_idx``."""
    depth = 0
    in_str = False
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "'":
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
    raise ValueError("unbalanced parentheses")


def split_args(args: str) -> list[str]:
    """Split a function argument list on top-level commas."""
    parts: list[str] = []
    depth = 0
    in_str = False
    buf: list[str] = []
    for ch in args:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
        buf.append(ch)
    parts.append("".join(buf).strip())
    return parts


def rewrite_calls(sql: str, name: str, fn: Callable[[list[str]], str]) -> str:
    """Replace every ``name(args...)`` call (innermost-safe) with ``fn(args)``."""
    pattern = re.compile(rf"\b{re.escape(name)}\s*\(", re.IGNORECASE)
    while True:
        m = pattern.search(sql)
        if not m:
            return sql
        open_idx = m.end() - 1
        close_idx = matching_paren(sql, open_idx)
        inner = rewrite_calls(sql[open_idx + 1 : close_idx], name, fn)
        sql = sql[: m.start()] + fn(split_args(inner)) + sql[close_idx + 1 :]
