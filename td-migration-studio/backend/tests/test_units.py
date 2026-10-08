from __future__ import annotations

import pyarrow as pa
import pytest

from app.connectors.registry import get_target_meta
from app.contracts.models import (
    DQOptions,
    ForeignKey,
    GovernanceOptions,
    IdentifierRules,
    TableProfile,
)
from app.pipeline.arrow_types import parse_arrow_type
from app.pipeline.dq import ColumnDQ, OrphanResult, evaluate
from app.pipeline.governance import classify_table, hash_value, mask_array
from app.pipeline.identifiers import normalize_identifier
from app.pipeline.options import resolve_table_options
from app.pipeline.orchestrator import topo_order
from app.pipeline.transforms import ColumnSpec, transform_batch

from .fakes import fake_target_type_info, olist_like


def test_identifiers_deterministic_and_rules():
    rules = IdentifierRules(max_length=20, case="lower", reserved_words=["select"])
    assert normalize_identifier("Order Id", rules)[0] == "order_id"
    assert normalize_identifier("1st", rules)[0].startswith("_")
    long1, _ = normalize_identifier("A" * 40, rules)
    assert len(long1) <= 20 and long1 == normalize_identifier("A" * 40, rules)[0]
    assert normalize_identifier("SELECT", rules)[1]


def test_pii_classification_names_and_sampling():
    t = olist_like()
    meta, data = t["CUSTOMERS"]
    tags, _ = classify_table(meta, data, GovernanceOptions())
    assert tags["customer_unique_id"].category == "identifier"
    assert tags["contact_info"].category == "contact"  # found by regex sampling, not by name
    assert tags["customer_zip_code_prefix"].category in ("location", "quasi_identifier")
    assert tags["customer_city"].category in ("location", "quasi_identifier")
    assert "customer_id" not in tags
    rmeta, rdata = t["ORDER_REVIEWS"]
    rtags, _ = classify_table(rmeta, rdata, GovernanceOptions())
    assert rtags["review_comment_message"].category == "free_text"
    off, _ = classify_table(meta, data, GovernanceOptions(pii_classification=False))
    assert off == {}


def test_masking_strategies():
    arr = pa.array(["alice@example.com", None, "bob@example.com"])
    h = mask_array(arr, "hash", salt="s").to_pylist()
    assert h[1] is None and len(h[0]) == 64 and h[0] == hash_value("alice@example.com", "s")
    assert h[0] != mask_array(arr, "hash", salt="other").to_pylist()[0]
    p = mask_array(arr, "partial").to_pylist()
    assert p[0] != "alice@example.com" and p[0][:1] == "a"
    assert mask_array(arr, "nullify").null_count == 3


def _spec(name: str, ttype: str, transform: str | None = None, masking: str = "none") -> ColumnSpec:
    info = fake_target_type_info(None, ttype)  # type: ignore[arg-type]
    return ColumnSpec(name, name, info, parse_arrow_type(info.arrow_type), transform, masking)


def test_transform_rejects_and_truncate():
    batch = pa.record_batch({"a": pa.array(["ok", "toolong"]), "b": pa.array(["x", "toolong"])})
    out, rejects, _ = transform_batch(batch, [_spec("a", "STRING(3)"), _spec("b", "STRING(3)", "truncate")])
    assert out.num_rows == 1 and out.column("a").to_pylist() == ["ok"]
    assert rejects is not None and rejects.num_rows == 1
    assert "a" in rejects.column("_reject_reason")[0].as_py()
    batch2 = pa.record_batch({"b": pa.array(["toolong"])})
    out2, rej2, _ = transform_batch(batch2, [_spec("b", "STRING(3)", "truncate")])
    assert out2.column("b").to_pylist() == ["too"] and (rej2 is None or rej2.num_rows == 0)


def test_transform_decimal_round_and_tz():
    import datetime as dt
    from decimal import Decimal

    batch = pa.record_batch(
        {
            "d": pa.array([Decimal("1.235"), Decimal("-1.235")], pa.decimal128(10, 3)),
            "t": pa.array(
                [dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)] * 2, pa.timestamp("us", tz="UTC")
            ),
        }
    )
    out, _, _ = transform_batch(
        batch, [_spec("d", "NUMERIC(10,2)", "round_scale"), _spec("t", "TIMESTAMPTZ", "tz_to_utc")]
    )
    assert out.column("d").to_pylist() == [Decimal("1.24"), Decimal("-1.24")]
    assert out.schema.field("t").type == pa.timestamp("us", tz="UTC")


@pytest.mark.parametrize(
    "target,table,expect",
    [
        (
            "bigquery",
            "ORDERS",
            {"partition_column": "order_purchase_timestamp", "clustering_columns": ["order_id"]},
        ),
        ("redshift", "PRODUCT_CATEGORY_TRANSLATION", {"diststyle": "ALL"}),
        ("redshift", "ORDERS", {"sortkeys": ["order_purchase_timestamp"]}),
        ("synapse", "PRODUCT_CATEGORY_TRANSLATION", {"distribution": "REPLICATE"}),
    ],
)
def test_table_option_defaults_from_metadata(target, table, expect):
    meta = get_target_meta(target)
    tmeta, _ = olist_like()[table]
    colmap = {c.name: c.name for c in tmeta.columns}
    opts, _ = resolve_table_options(meta, tmeta, colmap, {}, {})
    for k, v in expect.items():
        got = opts.get(k)
        assert got == v or (isinstance(v, list) and got == v[0]) or (isinstance(got, list) and v in got), (
            k,
            got,
        )


def test_table_option_defaults_large_fact_hash():
    meta = get_target_meta("synapse")
    tmeta, _ = olist_like()["ORDERS"]
    tmeta = tmeta.model_copy(update={"row_count": 1_000_000})
    opts, _ = resolve_table_options(meta, tmeta, {c.name: c.name for c in tmeta.columns}, {}, {})
    assert opts["distribution"] == "HASH" and opts["distribution_column"] == "order_id"
    opts2, _ = resolve_table_options(
        meta, tmeta, {c.name: c.name for c in tmeta.columns}, {}, {"distribution": "ROUND_ROBIN"}
    )
    assert opts2["distribution"] == "ROUND_ROBIN"


def test_topo_order_parents_first(env):
    _, planner, _ = env
    from app.contracts.models import PlanRequest

    plan = planner.create(PlanRequest(tables=[], target_id="bigquery"))
    names = [t.name for t in topo_order(plan.tables)]
    assert names.index("CUSTOMERS") < names.index("ORDERS") < names.index("ORDER_ITEMS")


def test_dq_ri_threshold_soft_vs_enforced():
    prof = TableProfile(row_count=100)
    soft = OrphanResult(
        ForeignKey(columns=["c"], ref_database="d", ref_table="P", ref_columns=["c"]), ["c"], "P", 100, 1
    )
    hard = OrphanResult(soft.fk.model_copy(update={"enforced": True}), ["c"], "P", 100, 1)
    cols = [ColumnDQ("c", "c", False, False)]
    ok = evaluate(cols, [], prof, prof, prof, 0, [soft], DQOptions())
    bad = evaluate(cols, [], prof, prof, prof, 0, [hard], DQOptions())
    ri = lambda cs: next(c for c in cs if c.name == "referential_integrity")  # noqa: E731
    assert ri(ok).passed and not ri(bad).passed
    off = evaluate(cols, [], prof, prof, prof, 0, [soft], DQOptions(referential_integrity=False))
    assert not any(c.name == "referential_integrity" for c in off)
    rej = evaluate(cols, [], prof, TableProfile(row_count=95), TableProfile(row_count=95), 5, [], DQOptions())
    assert not next(c for c in rej if c.name == "rejected_rows").passed
    assert next(c for c in rej if c.name == "row_count").passed
