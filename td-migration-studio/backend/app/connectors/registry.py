"""Connector registry: targets are discovered from targets_meta/*.yaml + @register_target classes.

Adding a target = drop `targets_meta/<id>.yaml` + implement TargetConnector subclasses decorated with
`@register_target("<id>", "simulated")` / `@register_target("<id>", "real")` and import the module in
connectors/targets/__init__.py. No other code changes.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..contracts.models import TargetMeta, TargetSummary
from ..contracts.source import SourceConnector
from ..contracts.target import TargetConnector
from ..settings import Settings, get_settings

META_DIR = Path(__file__).resolve().parent.parent / "targets_meta"

_TARGETS: dict[tuple[str, str], type[TargetConnector]] = {}


def register_target(target_id: str, mode: str):
    def deco(cls: type[TargetConnector]) -> type[TargetConnector]:
        cls.target_id = target_id
        cls.mode = mode
        _TARGETS[(target_id, mode)] = cls
        return cls

    return deco


@lru_cache
def list_target_meta() -> dict[str, TargetMeta]:
    metas: dict[str, TargetMeta] = {}
    for path in sorted(META_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        meta = TargetMeta.model_validate(data)
        metas[meta.id] = meta
    return metas


def get_target_meta(target_id: str) -> TargetMeta:
    try:
        return list_target_meta()[target_id]
    except KeyError as exc:
        raise KeyError(f"unknown target '{target_id}'") from exc


def real_ready(meta: TargetMeta) -> bool:
    return bool(meta.real_mode_required_env) and all(os.environ.get(k) for k in meta.real_mode_required_env)


def target_summaries() -> list[TargetSummary]:
    _import_connectors()
    out = []
    for meta in list_target_meta().values():
        modes = [m for m in ("simulated", "real") if (meta.id, m) in _TARGETS]
        out.append(
            TargetSummary(
                id=meta.id,
                display_name=meta.display_name,
                vendor=meta.vendor,
                modes=modes,  # type: ignore[arg-type]
                real_ready=real_ready(meta),
                free_tier_note=meta.free_tier_note,
            )
        )
    return out


def get_target_connector(
    target_id: str, mode: str, connection: dict[str, Any] | None = None, config: dict[str, Any] | None = None
) -> TargetConnector:
    _import_connectors()
    meta = get_target_meta(target_id)
    cls = _TARGETS.get((target_id, mode))
    if cls is None:
        raise KeyError(f"no '{mode}' connector registered for target '{target_id}'")
    conn = {f.key: os.environ.get(f.env) for f in meta.connection_fields if f.env and os.environ.get(f.env)}
    conn.update(connection or {})
    return cls(meta, conn, config or {})


def get_source_connector(settings: Settings | None = None) -> SourceConnector:
    settings = settings or get_settings()
    if settings.td_mode == "real":
        from .source.real import RealTeradataSource

        return RealTeradataSource(settings)
    from .source.emulated import EmulatedTeradataSource

    return EmulatedTeradataSource(settings)


def _import_connectors() -> None:
    from . import targets  # noqa: F401  (registers @register_target classes)
