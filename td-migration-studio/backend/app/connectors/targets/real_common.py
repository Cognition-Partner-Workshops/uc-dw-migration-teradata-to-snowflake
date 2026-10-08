"""Helpers shared by the real (cloud) connectors."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pyarrow.parquet as pq

from ...contracts.models import ConnectionTestResult, TargetMeta
from .base import import_error_message, missing_message


def timed_test(
    meta: TargetMeta, connection: dict[str, Any], required: list[str], probe: Callable[[], str]
) -> ConnectionTestResult:
    msg = missing_message(meta, connection, required)
    if msg:
        return ConnectionTestResult(ok=False, mode="real", message=msg, details={"missing": True})
    t0 = time.perf_counter()
    try:
        version = probe()
    except ImportError as exc:
        return ConnectionTestResult(ok=False, mode="real", message=import_error_message(meta, exc))
    except Exception as exc:
        return ConnectionTestResult(
            ok=False,
            mode="real",
            message=f"{meta.display_name} connection failed: {type(exc).__name__}: {exc}",
        )
    return ConnectionTestResult(
        ok=True,
        mode="real",
        latency_ms=(time.perf_counter() - t0) * 1000,
        server_version=str(version)[:200],
        message=f"Connected to {meta.display_name}",
    )


def parquet_rows(files, batch_rows: int = 5000):
    """Yield lists of row tuples from staged Parquet files (INSERT_BATCHES fallback)."""
    for f in files:
        for batch in pq.ParquetFile(f).iter_batches(batch_size=batch_rows):
            cols = [c.to_pylist() for c in batch.columns]
            yield list(zip(*cols, strict=True))
