"""Resolve TablePlan.target_options from TargetMeta.config_fields + request config + metadata defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..contracts.models import FieldSpec, TableMeta, TargetMeta, TdBaseType

DEFAULTS_PATH = Path(__file__).resolve().parent / "table_defaults.yaml"
DATE_TYPES = {TdBaseType.DATE, TdBaseType.TIMESTAMP, TdBaseType.TIMESTAMP_TZ}


@lru_cache
def load_defaults(path: Path = DEFAULTS_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _rules_for(target_id: str, defaults: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rules = {k: dict(v) for k, v in defaults.get("rules", {}).items()}
    for k, v in (defaults.get("target_overrides", {}).get(target_id) or {}).items():
        rules[k] = {**rules.get(k, {}), **v}
    return rules


def _derive(rule: dict[str, Any], table: TableMeta, small_rows: int) -> tuple[Any, str | None]:
    kind = rule.get("derive")
    cols = {c.name: c for c in table.columns}
    rows = table.row_count
    if rule.get("min_rows") and (rows or 0) < rule["min_rows"]:
        return None, None
    if kind == "value":
        return rule.get("value"), None
    if kind == "partition_column":
        for c in table.partition_columns:
            if c in cols and cols[c].base_type in DATE_TYPES:
                return c, "from the Teradata PPI"
        return None, None
    if kind == "date_column":
        for c in [*table.partition_columns, *cols]:
            if c in cols and cols[c].base_type in DATE_TYPES:
                return c, "PPI column" if c in table.partition_columns else "first DATE/TIMESTAMP column"
        return None, None
    if kind == "primary_index":
        return (list(table.primary_index), "primary index") if table.primary_index else (None, None)
    if kind == "primary_index_first":
        return (table.primary_index[0], "primary index") if table.primary_index else (None, None)
    if kind == "by_size":
        if rows is not None and rows <= small_rows:
            return rule.get("small"), f"{rows:,} rows <= {small_rows:,} (small dimension)"
        if not table.primary_index:
            return rule.get("no_key"), "no primary index"
        return rule.get("large"), f"{rows:,} rows" if rows is not None else "row count unknown"
    return None, None


def _show(field: FieldSpec, values: dict[str, Any]) -> bool:
    return not field.show_if or all(values.get(k) == v for k, v in field.show_if.items())


def _normalize(field: FieldSpec, value: Any, colmap: dict[str, str]) -> tuple[Any, str | None]:
    """Map column references to target names, clip lists, and validate select options."""
    if value in (None, "", []):
        return None, None
    if field.type in ("column", "columns"):
        items = value if isinstance(value, list) else [value]
        lookup = {k.lower(): v for k, v in colmap.items()} | {v.lower(): v for v in colmap.values()}
        mapped = [lookup.get(str(i).lower()) for i in items]
        unknown = [i for i, m in zip(items, mapped, strict=True) if m is None]
        if unknown:
            return None, f"{field.key}: unknown column(s) {unknown} ignored"
        if field.type == "column":
            return mapped[0], None
        if field.max_items and len(mapped) > field.max_items:
            return mapped[: field.max_items], f"{field.key}: clipped to {field.max_items} columns"
        return mapped, None
    if field.type == "select" and field.options and value not in field.options:
        return None, f"{field.key}: '{value}' is not one of {field.options}"
    return value, None


def resolve_target_config(meta: TargetMeta, target_config: dict[str, Any]) -> dict[str, Any]:
    out = {f.key: f.default for f in meta.config_fields if f.scope == "target" and f.default is not None}
    out.update({k: v for k, v in target_config.items() if v not in (None, "")})
    return out


def resolve_table_options(
    meta: TargetMeta,
    table: TableMeta,
    colmap: dict[str, str],
    target_values: dict[str, Any],
    table_config: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return (target-level + table-level options for this table, human notes about derived values)."""
    defaults = defaults or load_defaults()
    rules = _rules_for(meta.id, defaults)
    small_rows = int(defaults.get("small_table_rows", 50_000))
    values: dict[str, Any] = dict(target_values)
    notes: list[str] = []
    for field in (f for f in meta.config_fields if f.scope == "table"):
        source = "default"
        if field.key in table_config:
            value, note = _normalize(field, table_config[field.key], colmap)
            source = "config"
        else:
            value, note = None, None
            rule = rules.get(field.key)
            if rule and (not rule.get("requires") or values.get(rule["requires"])):
                raw, why = _derive(rule, table, small_rows)
                value, note = _normalize(field, raw, colmap)
                if value is not None:
                    source = "derived"
                    notes.append(f"{field.key} = {value}" + (f" ({why})" if why else ""))
            if value is None:
                value, _ = _normalize(field, field.default, colmap)
        if note:
            notes.append(note)
        if value is not None and (_show(field, values) or source == "config"):
            values[field.key] = value
    for field in meta.config_fields:
        if field.scope == "table" and field.key in values and not _show(field, values):
            values.pop(field.key)
    return values, notes
