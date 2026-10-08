"""Apply a target's IdentifierRules (case, max length, allowed characters, reserved words)."""

from __future__ import annotations

import hashlib
import re

from ..contracts.models import IdentifierRules

_INVALID = re.compile(r"[^0-9A-Za-z_]")


def normalize_identifier(name: str, rules: IdentifierRules) -> tuple[str, list[str]]:
    """Return (target identifier, notes). Deterministic, so re-planning yields identical names."""
    notes: list[str] = []
    out = _INVALID.sub("_", name)
    if out != name:
        notes.append(f"invalid characters in '{name}' replaced with '_'")
    if out[:1].isdigit():
        out = f"_{out}"
    if rules.case == "lower":
        out = out.lower()
    elif rules.case == "upper":
        out = out.upper()
    if len(out) > rules.max_length:
        suffix = hashlib.sha1(name.encode()).hexdigest()[:6]
        out = f"{out[: rules.max_length - 7]}_{suffix}"
        notes.append(f"'{name}' exceeds {rules.max_length} chars; shortened to '{out}'")
    if out.upper() in {w.upper() for w in rules.reserved_words}:
        notes.append(f"'{out}' is a reserved word; it will be quoted with {rules.quote}")
    return out, notes
