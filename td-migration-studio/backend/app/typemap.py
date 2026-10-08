"""Metadata-driven Teradata -> target type mapping (owned by the targets workstream).

The pipeline/planner only calls these two functions; all target knowledge lives in targets_meta/*.yaml.
"""

from __future__ import annotations

from .contracts.models import ColumnMeta, MappingDecision, TargetMeta, TargetTypeInfo


def resolve_type(meta: TargetMeta, column: ColumnMeta) -> MappingDecision:
    """Return the first TypeMappingRule in `meta.type_mappings` whose source/when matches, rendered."""
    raise NotImplementedError


def target_type_info(meta: TargetMeta, target_type: str) -> TargetTypeInfo:
    """Parse a target type string (possibly a user override) into the Arrow type/limits for staging."""
    raise NotImplementedError
