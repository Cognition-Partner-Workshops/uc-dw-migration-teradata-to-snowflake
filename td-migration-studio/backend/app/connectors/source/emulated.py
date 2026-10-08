"""Emulated Teradata source: PostgreSQL `tdemu` DB, physical tables in `retail_dw`, dictionary in `dbc`.

Metadata comes only from the emulated DBC views (see base.py for the queries); data is streamed through a
server-side cursor so `extract` stays memory-bounded by `batch_rows`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ...contracts.models import ColumnMeta, ConnectionTestResult, TdBaseType
from ...settings import Settings
from .base import SQL_VERSION, DictionarySource
from .catalog import arrow_type, quote_ident

T = TdBaseType


class EmulatedTeradataSource(DictionarySource):
    mode = "emulated"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.dsn = settings.td_emu_dsn
        self._pool = ConnectionPool(self.dsn, min_size=0, max_size=8, open=False, name="tdemu")
        self._opened = False

    def _conn(self):
        if not self._opened:
            self._pool.open(wait=False)
            self._opened = True
        return self._pool.connection(timeout=30)

    def close(self) -> None:
        if self._opened:
            self._pool.close()
            self._opened = False

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.replace("?", "%s"), list(params) if params else None)
            return list(cur.fetchall())

    def _stream(self, sql: str, batch_rows: int) -> Iterator[list[tuple]]:
        with self._conn() as conn, conn.cursor(name=f"td_extract_{uuid.uuid4().hex[:12]}") as cur:
            cur.itersize = batch_rows
            cur.execute(sql)
            while rows := cur.fetchmany(batch_rows):
                yield rows

    def _relation(self, database: str, table: str) -> str:
        return f"{quote_ident(database.lower())}.{quote_ident(table.lower())}"

    def _column_ident(self, name: str) -> str:
        return quote_ident(name.lower())

    def test_connection(self) -> ConnectionTestResult:
        info = conninfo_to_dict(self.dsn)
        details = {"host": info.get("host", "localhost"), "database": self.settings.td_database}
        t0 = time.perf_counter()
        try:
            rows = self._rows(SQL_VERSION)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            msg = f"{type(exc).__name__}: {exc}".strip()
            if "dbc" in msg.lower() and "does not exist" in msg.lower():
                msg = "emulator not seeded yet (run `python -m app.connectors.source.seed`): " + msg
            return ConnectionTestResult(ok=False, mode="emulated", message=msg, details=details)
        latency = (time.perf_counter() - t0) * 1000
        version = rows[0]["infodata"] if rows else None
        return ConnectionTestResult(
            ok=True, mode="emulated", latency_ms=round(latency, 2), server_version=version,
            message="Connected to emulated Teradata (PostgreSQL-backed DBC dictionary)", details=details,
        )  # fmt: skip

    def _checksum(self, database: str, table: str, columns: list[ColumnMeta]) -> str | None:
        if not columns:
            return None
        parts = " || chr(31) || ".join(_pg_canonical(c, self._column_ident(c.name)) for c in columns)
        row_hash = f"('x' || substr(md5({parts}), 1, 8))::bit(32)::bigint"
        sql = f"SELECT COALESCE(SUM({row_hash}), 0)::text AS checksum FROM {self._relation(database, table)}"
        return self._rows(sql)[0]["checksum"]


def _pg_canonical(col: ColumnMeta, c: str) -> str:
    """PostgreSQL rendering of contracts/checksum.py canon(v) for the column's Arrow contract type."""
    t = arrow_type(col)
    b = col.base_type
    if b in (T.DECIMAL, T.NUMBER):
        expr = f"CAST(CAST({c} AS NUMERIC({t.precision},{t.scale})) AS TEXT)"
    elif b == T.FLOAT:
        expr = f"CAST(CAST(ROUND(CAST({c} AS DOUBLE PRECISION) * 1e6) AS BIGINT) AS TEXT)"
    elif b == T.DATE:
        expr = f"to_char({c}, 'YYYY-MM-DD')"
    elif b == T.TIMESTAMP:
        expr = f"to_char({c}, 'YYYY-MM-DD HH24:MI:SS.US')"
    elif b == T.TIMESTAMP_TZ:
        expr = f"to_char({c} AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')"
    elif b in (T.BYTE, T.VARBYTE, T.BLOB):
        expr = f"encode({c}, 'hex')"
    elif b == T.CHAR:
        expr = f"rtrim({c})"
    else:
        expr = f"CAST({c} AS TEXT)"
    return f"COALESCE({expr}, '\\N')"
