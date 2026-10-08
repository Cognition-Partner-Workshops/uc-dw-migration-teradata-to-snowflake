"""Shape raw staged Arrow data into target types: transforms, PII masking, casting, rejects."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .. import typemap
from ..contracts.models import TablePlan, TargetMeta, TargetTypeInfo
from .arrow_types import is_text, parse_arrow_type
from .governance import mask_array
from .staging import PartWriter

REJECT_REASON = "_reject_reason"
REJECT_ROW = "_source_row"
ROUND_MODE = "half_towards_infinity"  # Teradata rounds halfway values away from zero


@dataclass(frozen=True)
class ColumnSpec:
    source: str
    target: str
    info: TargetTypeInfo
    arrow_type: pa.DataType
    transform: str | None
    masking: str


def build_specs(table: TablePlan, meta: TargetMeta) -> list[ColumnSpec]:
    specs = []
    for c in table.columns:
        info = typemap.target_type_info(meta, c.effective_type)
        specs.append(
            ColumnSpec(
                source=c.source.name,
                target=c.target_name,
                info=info,
                arrow_type=parse_arrow_type(info.arrow_type),
                transform=c.mapping.transform or None,
                masking=c.pii.masking if c.pii else "none",
            )
        )
    return specs


def target_schema(specs: list[ColumnSpec]) -> pa.Schema:
    return pa.schema([pa.field(s.target, s.arrow_type) for s in specs])


@dataclass
class ColumnOutcome:
    array: pa.Array
    bad: set[int] = field(default_factory=set)
    reason: str = ""
    lossy: int = 0
    touched: bool = False


def safe_cast(arr: pa.Array, typ: pa.DataType) -> tuple[pa.Array, set[int], str]:
    """Cast; values that cannot be cast are located by bisection and nulled (returned as bad indices)."""
    if arr.type == typ:
        return arr, set(), ""
    try:
        return arr.cast(typ), set(), ""
    except pa.ArrowNotImplementedError:
        raise
    except pa.ArrowInvalid as exc:
        first_error = str(exc)
    bad: set[int] = set()

    def bisect(lo: int, hi: int) -> None:
        try:
            arr.slice(lo, hi - lo).cast(typ)
        except pa.ArrowInvalid:
            if hi - lo == 1:
                bad.add(lo)
            else:
                mid = (lo + hi) // 2
                bisect(lo, mid)
                bisect(mid, hi)

    bisect(0, len(arr))
    mask = pa.array([i in bad for i in range(len(arr))], pa.bool_())
    cleaned = pc.if_else(mask, pa.scalar(None, arr.type), arr)
    return cleaned.cast(typ), bad, first_error


def _truncate_bytes(value: str, limit: int) -> str:
    return value.encode()[:limit].decode(errors="ignore")


def transform_column(arr: pa.Array, spec: ColumnSpec, salt: str | None = None) -> ColumnOutcome:
    out = ColumnOutcome(array=arr, touched=spec.transform not in (None, "none") or spec.masking != "none")
    tgt = spec.arrow_type
    t = spec.transform

    if t == "tz_to_utc" and pa.types.is_timestamp(arr.type) and arr.type.tz:
        arr = arr.cast(pa.timestamp(arr.type.unit, tz="UTC"))
    elif t == "to_string" and not is_text(arr.type):
        arr = arr.cast(pa.string())
    if pa.types.is_decimal(tgt) and (pa.types.is_floating(arr.type) or pa.types.is_decimal(arr.type)):
        if not pa.types.is_decimal(arr.type) or arr.type.scale > tgt.scale:
            rounded = pc.round(arr, ndigits=tgt.scale, round_mode=ROUND_MODE)
            if pa.types.is_decimal(arr.type):
                out.lossy += int(pc.sum(pc.not_equal(arr, rounded)).as_py() or 0)
            arr, out.touched = rounded, True

    if spec.masking != "none":
        arr = mask_array(arr, spec.masking, salt)  # type: ignore[arg-type]

    arr, bad, err = safe_cast(arr, tgt)
    if bad:
        out.bad |= bad
        out.reason = f"cannot cast to {spec.info.target_type}: {err}"

    if spec.info.max_length and is_text(tgt):
        lengths = pc.binary_length(arr) if spec.info.length_unit == "bytes" else pc.utf8_length(arr)
        over = pc.fill_null(pc.greater(lengths, spec.info.max_length), False)
        n_over = int(pc.sum(over).as_py() or 0)
        if n_over:
            limit = spec.info.max_length
            if t == "truncate":
                if spec.info.length_unit == "bytes":
                    vals = arr.to_pylist()
                    over_l = over.to_pylist()
                    arr = pa.array(
                        [_truncate_bytes(v, limit) if o else v for v, o in zip(vals, over_l, strict=True)],
                        tgt,
                    )
                else:
                    arr = pc.if_else(over, pc.utf8_slice_codeunits(arr, 0, limit), arr)
                out.lossy += n_over
                out.touched = True
            else:
                idx = {i for i, o in enumerate(over.to_pylist()) if o}
                out.bad |= idx
                unit = spec.info.length_unit or "chars"
                msg = f"longer than {limit} {unit} ({spec.info.target_type})"
                out.reason = f"{out.reason}; {msg}" if out.reason else msg
    out.array = arr
    return out


@dataclass
class TransformResult:
    rows_in: int = 0
    rows_out: int = 0
    rows_rejected: int = 0
    files: list[Path] = field(default_factory=list)
    bytes: int = 0
    lossy: Counter = field(default_factory=Counter)
    touched: set[str] = field(default_factory=set)
    reject_reasons: Counter = field(default_factory=Counter)


def _reject_rows(batch: pa.RecordBatch, bad: dict[int, list[str]], offset: int) -> pa.Table:
    idx = sorted(bad)
    rows = batch.take(pa.array(idx, pa.int64())).to_pylist()
    cols = batch.schema.names
    data: dict[str, list] = {c: [None if r[c] is None else str(r[c]) for r in rows] for c in cols}
    data[REJECT_REASON] = ["; ".join(bad[i]) for i in idx]
    data[REJECT_ROW] = [offset + i for i in idx]
    schema = pa.schema(
        [
            *(pa.field(c, pa.string()) for c in cols),
            pa.field(REJECT_REASON, pa.string()),
            pa.field(REJECT_ROW, pa.int64()),
        ]
    )
    return pa.table(data, schema=schema)


def transform_batch(
    batch: pa.RecordBatch, specs: list[ColumnSpec], salt: str | None = None, offset: int = 0
) -> tuple[pa.Table, pa.Table | None, dict[str, ColumnOutcome]]:
    outcomes = {s.target: transform_column(batch.column(s.source), s, salt) for s in specs}
    bad: dict[int, list[str]] = {}
    for s in specs:
        o = outcomes[s.target]
        for i in o.bad:
            bad.setdefault(i, []).append(f"{s.source}: {o.reason}")
    out = pa.table([outcomes[s.target].array for s in specs], schema=target_schema(specs))
    rejects = None
    if bad:
        keep = pa.array([i not in bad for i in range(batch.num_rows)], pa.bool_())
        out = out.filter(keep)
        rejects = _reject_rows(batch, bad, offset)
    return out, rejects, outcomes


def transform_files(
    raw_files: list[Path],
    specs: list[ColumnSpec],
    out_dir: Path,
    rejects_path: Path,
    salt: str | None = None,
    batch_rows: int = 100_000,
) -> TransformResult:
    res = TransformResult()
    writer = PartWriter(out_dir, target_schema(specs))
    rejects_path.unlink(missing_ok=True)
    rej_writer: pq.ParquetWriter | None = None
    try:
        for f in raw_files:
            for batch in pq.ParquetFile(f).iter_batches(batch_size=batch_rows):
                out, rejects, outcomes = transform_batch(batch, specs, salt, offset=res.rows_in)
                res.rows_in += batch.num_rows
                writer.write(out)
                for name, o in outcomes.items():
                    if o.lossy:
                        res.lossy[name] += o.lossy
                    if o.touched:
                        res.touched.add(name)
                if rejects is not None:
                    res.rows_rejected += rejects.num_rows
                    for r in rejects.column(REJECT_REASON).to_pylist():
                        for part in r.split("; "):
                            res.reject_reasons[part.split(":", 1)[0]] += 1
                    if rej_writer is None:
                        rejects_path.parent.mkdir(parents=True, exist_ok=True)
                        rej_writer = pq.ParquetWriter(rejects_path, rejects.schema)
                    rej_writer.write_table(rejects)
        res.files = writer.commit()
    except BaseException:
        writer.abort()
        raise
    finally:
        if rej_writer is not None:
            rej_writer.close()
    res.rows_out = writer.rows
    res.bytes = sum(p.stat().st_size for p in res.files)
    return res
