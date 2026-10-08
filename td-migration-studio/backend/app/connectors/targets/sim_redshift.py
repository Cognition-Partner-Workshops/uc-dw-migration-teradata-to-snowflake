"""Simulated Redshift (DuckDB file) rendering native Redshift DDL."""

from __future__ import annotations

from ..registry import register_target
from .base import SimulatedTarget
from .ddl_redshift import RedshiftDDL


@register_target("redshift", "simulated")
class SimulatedRedshift(RedshiftDDL, SimulatedTarget):
    pass
