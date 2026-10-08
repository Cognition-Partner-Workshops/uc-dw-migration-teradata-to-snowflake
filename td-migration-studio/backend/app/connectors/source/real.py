"""Real Teradata source via `teradatasql` (TD_HOST / TD_USER / TD_PASSWORD / TD_LOGMECH).

Issues the same DBC.TablesV / ColumnsV / IndicesV / All_RI_ChildrenV / TableSizeV queries as the emulator
(base.py) and shares the type-code -> ColumnMeta/Arrow mapping (catalog.py), so both produce identical
`TableMeta`. Extract uses a dedicated session and `fetchmany` chunks converted to Arrow.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from ...contracts.models import ConnectionTestResult
from ...settings import Settings
from .base import SQL_VERSION, DictionarySource
from .catalog import quote_ident


class RealTeradataSource(DictionarySource):
    mode = "real"
    optional_views_may_fail = True

    def __init__(self, settings: Settings, connect: Callable[[], Any] | None = None):
        self.settings = settings
        self._connect = connect or self._teradatasql_connect
        self._meta_conn: Any = None
        self._lock = threading.Lock()

    def _teradatasql_connect(self) -> Any:
        s = self.settings
        if not (s.td_host and s.td_user):
            raise RuntimeError("real Teradata mode needs TD_HOST, TD_USER and TD_PASSWORD")
        import teradatasql  # optional dependency (.[real])

        return teradatasql.connect(
            host=s.td_host, user=s.td_user, password=s.td_password or "", logmech=s.td_logmech
        )

    def close(self) -> None:
        with self._lock:
            if self._meta_conn is not None:
                try:
                    self._meta_conn.close()
                finally:
                    self._meta_conn = None

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            if self._meta_conn is None:
                self._meta_conn = self._connect()
            try:
                with self._meta_conn.cursor() as cur:
                    if params:
                        cur.execute(sql, list(params))
                    else:
                        cur.execute(sql)
                    names = [d[0] for d in cur.description or []]
                    return [dict(zip(names, row, strict=False)) for row in cur.fetchall()]
            except Exception:
                self._meta_conn = None  # force a fresh session next time
                raise

    def _stream(self, sql: str, batch_rows: int) -> Iterator[list[tuple]]:
        con = self._connect()
        try:
            with con.cursor() as cur:
                cur.execute(sql)
                while rows := cur.fetchmany(batch_rows):
                    yield [tuple(r) for r in rows]
        finally:
            con.close()

    def _relation(self, database: str, table: str) -> str:
        return f"{quote_ident(database)}.{quote_ident(table)}"

    def _ddl(self, database: str, table: str, request_text: str | None) -> str | None:
        try:
            rows = self._query(f"SHOW TABLE {self._relation(database, table)}")
        except Exception:  # noqa: BLE001 - fall back to DBC.TablesV.RequestText
            return request_text
        text = "\n".join(str(v) for r in rows for v in r.values() if v is not None)
        return text.replace("\r\n", "\n").replace("\r", "\n").strip() or request_text

    def test_connection(self) -> ConnectionTestResult:
        details = {"host": self.settings.td_host, "database": self.settings.td_database}
        t0 = time.perf_counter()
        try:
            rows = self._rows(SQL_VERSION)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            return ConnectionTestResult(
                ok=False, mode="real", message=f"{type(exc).__name__}: {exc}", details=details
            )
        latency = (time.perf_counter() - t0) * 1000
        return ConnectionTestResult(
            ok=True,
            mode="real",
            latency_ms=round(latency, 2),
            server_version=rows[0]["infodata"] if rows else None,
            message="Connected to Teradata",
            details=details,
        )
