"""Conversion engine: route each source object to the table / view / routine converter for each target."""

from __future__ import annotations

from collections.abc import Callable

from .checklist import build_checklist, checklist_header
from .ddl_render import column_mappings, render_table
from .models import ColumnMapping, Conversion, SourceObject, TargetId
from .routine_convert import convert_routine
from .sql_convert import convert_view, draft_routine
from .td_catalog import NUMERIC_TYPES
from .testpack import test_queries


def numeric_columns(objects: list[SourceObject]) -> frozenset[str]:
    return frozenset(c.name for o in objects if o.table for c in o.table.columns if c.base_type in NUMERIC_TYPES)


def _convert(
    obj: SourceObject,
    target: TargetId,
    schema_map: dict[str, str],
    project: str,
    numeric_cols: frozenset[str] = frozenset(),
    registry: dict[str, SourceObject] | None = None,
) -> Conversion:
    if obj.parse_error and obj.object_type in ("table", "view", "other"):
        return Conversion(
            object_id=obj.id,
            target=target,
            status="unsupported",
            sql=f"-- Not converted: {obj.parse_error}\n{obj.sql}",
            reason=obj.parse_error,
        )
    if obj.object_type == "table" and obj.table:
        return render_table(obj, target, schema_map)
    if obj.object_type == "view":
        return convert_view(obj, target, schema_map, project if target == "bigquery" else "", numeric_cols)
    if obj.object_type in ("macro", "procedure", "bteq_script") and registry is not None:
        try:
            return convert_routine(obj, target, schema_map, project if target == "bigquery" else "", registry)
        except Exception as exc:  # noqa: BLE001
            conv = draft_routine(obj, target, schema_map, project if target == "bigquery" else "")
            conv.reason = f"Automatic routine conversion failed ({exc}); {conv.reason or 'draft only'}"
            return conv
    return draft_routine(obj, target, schema_map, project if target == "bigquery" else "")


def convert_object(
    obj: SourceObject,
    target: TargetId,
    schema_map: dict[str, str],
    project: str,
    numeric_cols: frozenset[str] = frozenset(),
    registry: dict[str, SourceObject] | None = None,
) -> Conversion:
    conv = _convert(obj, target, schema_map, project, numeric_cols, registry)
    conv.checklist = build_checklist(obj, conv)
    if conv.checklist:
        conv.sql = checklist_header(conv.checklist) + conv.sql
    conv.test_source, conv.test_target = test_queries(obj, conv, target, schema_map, project)
    return conv


def convert_all(
    objects: list[SourceObject],
    order: list[str],
    targets: list[TargetId],
    schema_map: dict[str, str],
    project: str,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> tuple[list[Conversion], dict[str, dict[str, list[ColumnMapping]]]]:
    by_id = {o.id: o for o in objects}
    conversions: list[Conversion] = []
    mappings: dict[str, dict[str, list[ColumnMapping]]] = {}
    numeric = numeric_columns(objects)
    total = len(order) * len(targets)
    for target in targets:
        mappings[target] = {}
        for oid in order:
            obj = by_id[oid]
            if on_progress:
                on_progress(len(conversions), total, obj.name)
            conversions.append(convert_object(obj, target, schema_map, project, numeric, by_id))
            if obj.table:
                mappings[target][oid] = column_mappings(obj.table, target)
    return conversions, mappings
