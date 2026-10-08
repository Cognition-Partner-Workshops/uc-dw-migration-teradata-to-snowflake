"""Simulated BigQuery (DuckDB file) rendering native BigQuery DDL."""

from __future__ import annotations

from ..registry import register_target
from .base import SimulatedTarget
from .ddl_bigquery import BigQueryDDL


@register_target("bigquery", "simulated")
class SimulatedBigQuery(BigQueryDDL, SimulatedTarget):
    pass
