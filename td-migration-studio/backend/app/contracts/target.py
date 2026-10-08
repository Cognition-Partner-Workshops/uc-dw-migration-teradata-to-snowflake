"""TargetConnector contract. One class per (target_id, mode), registered in connectors/registry.py.

Simulated implementations store data in a local DuckDB file per target but must render and record the
*native* DDL (TablePlan.ddl) exactly as it would be executed on the real warehouse.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from .models import (
    ConnectionTestResult,
    LoadResult,
    MigrationPlan,
    ProfileSpec,
    TablePlan,
    TableProfile,
    TargetMeta,
)


class TargetConnector(ABC):
    target_id: ClassVar[str]
    mode: ClassVar[str]  # "simulated" | "real"

    def __init__(self, meta: TargetMeta, connection: dict[str, Any], config: dict[str, Any]):
        self.meta = meta
        self.connection = connection
        self.config = config

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult: ...

    @abstractmethod
    def render_ddl(self, table: TablePlan) -> str:
        """Native dialect CREATE TABLE incl. target options (distribution/partition/sort/cluster...)."""

    @abstractmethod
    def ensure_container(self, container: str) -> None:
        """Create schema/dataset if missing (idempotent)."""

    @abstractmethod
    def create_table(self, table: TablePlan) -> None:
        """Create (or replace if the definition changed) the final table. Idempotent."""

    @abstractmethod
    def load(self, table: TablePlan, files: list[Path], load_id: str) -> LoadResult:
        """Load staged Parquet files (already transformed to target types) with REPLACE semantics:
        after success the final table contains exactly these files' rows, regardless of earlier
        partial/complete loads. Use a staging table + atomic swap, or WRITE_TRUNCATE."""

    @abstractmethod
    def profile(self, table: TablePlan, spec: ProfileSpec) -> TableProfile:
        """Row count, null counts, numeric aggregates, canonical checksum, duplicate-key counts,
        all computed by the target engine (see contracts/checksum.py for the checksum definition)."""

    @abstractmethod
    def drop_table(self, table: TablePlan) -> None: ...

    def access_script(self, plan: MigrationPlan) -> str:
        """Role/GRANT/IAM script for the plan (rendered from meta.governance.role_script_template)."""
        return ""

    def close(self) -> None:  # pragma: no cover - optional
        return None
