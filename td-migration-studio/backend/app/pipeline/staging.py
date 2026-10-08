"""Staging layout + extraction to Parquet.

  $DATA_DIR/staging/<run>/<table>/raw/part-*.parquet          source extract (durable stage)
  $DATA_DIR/staging/<run>/<table>/transformed/part-*.parquet  shaped to target types, masked
  $DATA_DIR/rejects/<run>/<table>.parquet                     rejected rows + `_reject_reason`
Directories are written under a temporary name and renamed when complete, so a crash never leaves a
half-written stage that a resume could mistake for a durable one.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ..contracts.models import TablePlan
from ..contracts.source import SourceConnector

PART_ROWS = 1_000_000


@dataclass(frozen=True)
class TablePaths:
    root: Path
    rejects: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def transformed(self) -> Path:
        return self.root / "transformed"


def table_paths(data_dir: Path, run_id: str, table: str) -> TablePaths:
    return TablePaths(
        data_dir / "staging" / run_id / table, data_dir / "rejects" / run_id / f"{table}.parquet"
    )


def parquet_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.parquet")) if directory.is_dir() else []


def files_bytes(files: list[Path]) -> int:
    return sum(f.stat().st_size for f in files)


class PartWriter:
    """Writes record batches into part-NNNNN.parquet files under a temp dir; `commit` renames it."""

    def __init__(self, final_dir: Path, schema: pa.Schema, part_rows: int = PART_ROWS):
        self.final_dir = final_dir
        self.tmp_dir = final_dir.with_name(f"{final_dir.name}.tmp-{uuid.uuid4().hex[:8]}")
        self.tmp_dir.mkdir(parents=True)
        self.schema = schema
        self.part_rows = part_rows
        self.rows = 0
        self._part_rows = 0
        self._idx = 0
        self._writer: pq.ParquetWriter | None = None

    def _open(self) -> pq.ParquetWriter:
        if self._writer is None:
            path = self.tmp_dir / f"part-{self._idx:05d}.parquet"
            self._writer = pq.ParquetWriter(path, self.schema, compression="zstd")
        return self._writer

    def write(self, data: pa.RecordBatch | pa.Table) -> None:
        if data.num_rows == 0:
            return
        if data.schema != self.schema:
            data = (
                data.cast(self.schema)
                if isinstance(data, pa.Table)
                else pa.Table.from_batches([data]).cast(self.schema)
            )
        self._open().write(data if isinstance(data, pa.Table) else pa.Table.from_batches([data]))
        self.rows += data.num_rows
        self._part_rows += data.num_rows
        if self._part_rows >= self.part_rows:
            self._close_part()

    def _close_part(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
            self._idx += 1
            self._part_rows = 0

    def commit(self) -> list[Path]:
        if self.rows == 0 and self._idx == 0:
            self._open()  # always leave one (possibly empty) part so the schema is recorded
        self._close_part()
        if self.final_dir.exists():
            shutil.rmtree(self.final_dir)
        self.tmp_dir.rename(self.final_dir)
        return parquet_files(self.final_dir)

    def abort(self) -> None:
        if self._writer is not None:
            self._writer.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


@dataclass
class ExtractResult:
    rows: int
    files: list[Path]
    bytes: int
    batches: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def extract_table(
    source: SourceConnector,
    table: TablePlan,
    out_dir: Path,
    batch_rows: int,
    on_batch: Callable[[int, int], None] | None = None,
) -> ExtractResult:
    """Stream `source.extract` into raw Parquet parts. `on_batch(rows_so_far, batches)` may raise to abort."""
    cols = [c.source.name for c in table.columns]
    it: Iterator[pa.RecordBatch] = iter(
        source.extract(table.source.database, table.source.name, columns=cols, batch_rows=batch_rows)
    )
    writer: PartWriter | None = None
    batches = 0
    try:
        for batch in it:
            if writer is None:
                writer = PartWriter(out_dir, batch.schema)
            writer.write(batch)
            batches += 1
            if on_batch:
                on_batch(writer.rows, batches)
        if writer is None:  # empty table: no batch to infer a schema from
            writer = PartWriter(out_dir, pa.schema([pa.field(c, pa.null()) for c in cols]))
        files = writer.commit()
    except BaseException:
        if writer is not None:
            writer.abort()
        raise
    finally:
        close = getattr(it, "close", None)
        if close:
            close()
    return ExtractResult(rows=writer.rows, files=files, bytes=files_bytes(files), batches=batches)


def read_rejects(path: Path, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    pf = pq.ParquetFile(path)
    total = pf.metadata.num_rows
    if limit <= 0 or offset >= total:
        return [], total
    table = pf.read().slice(offset, limit)
    return table.to_pylist(), total


def remove_run_staging(data_dir: Path, run_id: str) -> None:
    shutil.rmtree(data_dir / "staging" / run_id, ignore_errors=True)
