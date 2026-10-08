"""SourceConnector contract. Implementations: connectors/source/emulated.py, connectors/source/real.py."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

import pyarrow as pa

from .models import ConnectionTestResult, ProfileSpec, SourceTableSummary, TableMeta, TableProfile


class SourceConnector(ABC):
    """Reads Teradata (real or emulated) metadata and data.

    Arrow type contract for `extract` (so staging/transforms are engine-independent):
      BYTEINT->int8, SMALLINT->int16, INTEGER->int32, BIGINT->int64, DECIMAL(p,s)->decimal128(p,s),
      NUMBER(p,s)->decimal128(p,s), unbounded NUMBER->decimal128(38,15), FLOAT->float64,
      CHAR/VARCHAR/CLOB/JSON/XML/INTERVAL/PERIOD->string, BYTE/VARBYTE/BLOB->binary, DATE->date32,
      TIME->time64('us'), TIMESTAMP->timestamp('us'), TIMESTAMP WITH TIME ZONE->timestamp('us', tz='UTC').
      CHAR values are returned right-trimmed (Teradata pads CHAR).
    """

    mode: str  # "emulated" | "real"

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult: ...

    @abstractmethod
    def list_databases(self) -> list[str]: ...

    @abstractmethod
    def list_tables(self, database: str) -> list[SourceTableSummary]: ...

    @abstractmethod
    def describe_table(self, database: str, table: str) -> TableMeta:
        """Full metadata incl. columns (Teradata types), PI/PPI, unique keys, soft FKs, row_count."""

    @abstractmethod
    def extract(
        self, database: str, table: str, columns: list[str] | None = None, batch_rows: int = 100_000
    ) -> Iterator[pa.RecordBatch]:
        """Stream the table as Arrow record batches following the type contract above."""

    @abstractmethod
    def profile(self, database: str, table: str, spec: ProfileSpec) -> TableProfile:
        """Row count, per-column nulls, numeric sum/min/max computed by the source engine itself."""

    def close(self) -> None:  # pragma: no cover - optional
        return None
