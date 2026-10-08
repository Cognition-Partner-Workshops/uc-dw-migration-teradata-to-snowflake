"""Low-level helpers for scanning SQL text while ignoring strings and comments."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

STRING_FILL = "\x01"


def mask(sql: str) -> str:
    """Return ``sql`` with comment text blanked and string-literal contents replaced.

    The result has the same length as the input so match offsets map 1:1 back to
    the original text. Quote characters are kept so literal patterns still match.
    """
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if sql[k] != "\n":
                    out[k] = " "
            i = j
        elif ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n:
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:
                        j += 2
                        continue
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                if quote == "'":
                    out[k] = STRING_FILL
            i = j + 1
        else:
            i += 1
    return "".join(out)


def depth_map(masked: str) -> list[int]:
    """Paren depth *before* each character."""
    depths, d = [], 0
    for ch in masked:
        depths.append(d)
        if ch == "(":
            d += 1
        elif ch == ")":
            d -= 1
    return depths


def matching_paren(masked: str, open_idx: int) -> int:
    d = 0
    for i in range(open_idx, len(masked)):
        if masked[i] == "(":
            d += 1
        elif masked[i] == ")":
            d -= 1
            if d == 0:
                return i
    raise ValueError("unbalanced parentheses")


def split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split ``text`` on ``sep`` occurrences that are outside parens, strings and comments."""
    masked = mask(text)
    parts, d, start = [], 0, 0
    for i, ch in enumerate(masked):
        if ch == "(":
            d += 1
        elif ch == ")":
            d -= 1
        elif ch == sep and d == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def split_statements(sql: str) -> list[str]:
    return [s for s in split_top_level(sql, ";") if s.strip() and mask(s).strip()]


def finditer_code(pattern: str, sql: str, flags: int = re.IGNORECASE) -> Iterator[re.Match]:
    """Find pattern matches in code (matches are against the masked text)."""
    return re.finditer(pattern, mask(sql), flags)


def sub_code(
    pattern: str,
    sql: str,
    repl: Callable[[str, re.Match], str] | str,
    flags: int = re.IGNORECASE,
) -> tuple[str, int]:
    """Substitute matches of ``pattern`` that occur in code (not strings/comments).

    ``repl`` receives a function ``g(n)`` returning the *original* text of group n
    and the masked match. Returns (new_sql, count).
    """
    pieces, last, count = [], 0, 0
    for m in finditer_code(pattern, sql, flags):

        def g(idx: int | str = 0, _m: re.Match = m) -> str:
            s, e = _m.span(idx)
            return sql[s:e] if s >= 0 else ""

        pieces.append(sql[last : m.start()])
        pieces.append(repl if isinstance(repl, str) else repl(g, m))
        last = m.end()
        count += 1
    pieces.append(sql[last:])
    return "".join(pieces), count


def strip_block_comments(sql: str) -> str:
    """Remove /* ... */ comments (outside strings)."""
    masked = mask(sql)
    res, i, n = [], 0, len(sql)
    while i < n:
        if sql.startswith("/*", i) and masked[i] == " ":
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        res.append(sql[i])
        i += 1
    return "".join(res)


def strip_line_comments(sql: str) -> tuple[str, list[str]]:
    """Remove -- comments and return them separately."""
    masked = mask(sql)
    comments: list[str] = []
    res, i, n = [], 0, len(sql)
    while i < n:
        if sql.startswith("--", i) and masked[i] == " ":
            j = sql.find("\n", i)
            j = n if j == -1 else j
            comments.append(sql[i + 2 : j].strip())
            i = j
            continue
        res.append(sql[i])
        i += 1
    return "".join(res), comments


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
