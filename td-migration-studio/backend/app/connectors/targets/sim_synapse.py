"""Simulated Synapse (DuckDB file) rendering native Synapse DDL."""

from __future__ import annotations

from ..registry import register_target
from .base import SimulatedTarget
from .ddl_synapse import SynapseDDL


@register_target("synapse", "simulated")
class SimulatedSynapse(SynapseDDL, SimulatedTarget):
    pass
