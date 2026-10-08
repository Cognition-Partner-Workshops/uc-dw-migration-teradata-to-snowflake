import pytest
from target_fixtures import GEOLOCATION, ORDER_REVIEWS, ORDERS, col

from app.connectors.registry import get_target_meta, list_target_meta
from app.contracts.models import TdBaseType
from app.typemap import ExpressionError, resolve_type, safe_eval, target_type_info

TARGETS = ["synapse", "bigquery", "redshift"]
TRANSFORMS = {None, "none", "tz_to_utc", "round_scale", "truncate", "to_string"}
VARIANTS = {
    "DECIMAL": [dict(precision=10, scale=2), dict(precision=38, scale=12), dict(precision=31, scale=0)],
    "NUMBER": [{}, dict(precision=12, scale=4)],
    "CHAR": [dict(length=2, charset="LATIN"), dict(length=32, charset="UNICODE")],
    "VARCHAR": [dict(length=60, charset="LATIN"), dict(length=5000, charset="UNICODE"), dict(length=64000)],
    "CLOB": [dict(length=2097152, charset="UNICODE")],
    "BYTE": [dict(length=16)],
    "VARBYTE": [dict(length=200)],
    "BLOB": [dict(length=1000000)],
    "TIME": [dict(fractional_seconds=0)],
    "TIME_TZ": [dict(fractional_seconds=6)],
    "TIMESTAMP": [dict(fractional_seconds=0), {}],
    "TIMESTAMP_TZ": [dict(fractional_seconds=6)],
    "INTERVAL": [dict(interval_qualifier="DAY TO SECOND")],
    "PERIOD": [dict(interval_qualifier="DATE")],
}


def resolve(target, column):
    return resolve_type(get_target_meta(target), column)


def by_name(table, name):
    return next(c for c in table.columns if c.name == name)


@pytest.mark.parametrize("target", TARGETS)
def test_every_td_base_type_maps_to_a_parseable_type(target):
    meta = get_target_meta(target)
    for bt in TdBaseType:
        for v in VARIANTS.get(bt.value, [{}]):
            d = resolve_type(meta, col("c", bt.value, **v))
            assert d.rule_index is not None and d.transform in TRANSFORMS, (bt, v, d)
            assert target_type_info(meta, d.target_type).arrow_type, (bt, d.target_type)


def test_rules_only_use_contract_transforms():
    for meta in list_target_meta().values():
        assert {r.transform for r in meta.type_mappings} <= TRANSFORMS
        assert meta.dq.checksum_sql_template and meta.governance.role_script_template


@pytest.mark.parametrize("target", TARGETS)
def test_geolocation_unbounded_number_is_lossy(target):
    d = resolve(target, by_name(GEOLOCATION, "geolocation_lat"))
    assert d.lossy and d.severity == "warning" and d.transform == "round_scale"
    assert d.target_type == {"bigquery": "BIGNUMERIC(38,15)"}.get(target, "DECIMAL(38,15)")


@pytest.mark.parametrize("target", TARGETS)
def test_timestamp_with_time_zone_loses_offset(target):
    d = resolve(target, by_name(ORDER_REVIEWS, "review_answer_timestamp"))
    assert d.lossy and d.transform == "tz_to_utc" and "offset" in d.reason


def test_byteint():
    score = by_name(ORDER_REVIEWS, "review_score")
    assert resolve("synapse", score).target_type == "SMALLINT"  # TINYINT is unsigned
    assert "unsigned" in resolve("synapse", score).reason
    assert resolve("redshift", score).target_type == "SMALLINT"
    assert resolve("bigquery", score).target_type == "INT64"


def test_order_reviews_unicode_comment():
    c = by_name(ORDER_REVIEWS, "review_comment_message")  # VARCHAR(5000) UNICODE
    syn = resolve("synapse", c)
    assert syn.target_type == "NVARCHAR(MAX)" and syn.severity == "warning" and "4000" in syn.reason
    rs = resolve("redshift", c)
    assert rs.target_type == "VARCHAR(15000)" and not rs.lossy  # 3 UTF-8 bytes per char
    assert resolve("bigquery", c).target_type == "STRING(5000)"
    long = col("x", "VARCHAR", length=30000, charset="UNICODE")
    assert resolve("redshift", long).target_type == "VARCHAR(65535)" and resolve("redshift", long).lossy


def test_bigquery_numeric_vs_bignumeric():
    assert resolve("bigquery", col("p", "DECIMAL", precision=10, scale=2)).target_type == "NUMERIC(10,2)"
    assert resolve("bigquery", col("p", "DECIMAL", precision=31, scale=0)).target_type == "BIGNUMERIC(31,0)"
    assert resolve("bigquery", col("p", "DECIMAL", precision=20, scale=12)).target_type == "BIGNUMERIC(20,12)"


def test_orders_char_keys():
    oid = by_name(ORDERS, "order_id")
    assert resolve("synapse", oid).target_type == "CHAR(32)"
    assert resolve("redshift", oid).target_type == "CHAR(32)"
    assert resolve("bigquery", oid).target_type == "STRING(32)"


@pytest.mark.parametrize(
    "target,type_str,arrow,max_length,unit",
    [
        ("synapse", "NVARCHAR(200)", "string", 200, "chars"),
        ("synapse", "VARCHAR(MAX)", "string", 2147483647, "bytes"),
        ("synapse", "DATETIMEOFFSET(6)", "timestamp[us, tz=UTC]", None, None),
        ("redshift", "VARCHAR(256)", "string", 256, "bytes"),
        ("redshift", "VARBYTE(16)", "binary", 16, "bytes"),
        ("redshift", "DECIMAL(18,4)", "decimal128(18, 4)", None, None),
        ("bigquery", "STRING", "string", None, None),
        ("bigquery", "BIGNUMERIC(60,20)", "decimal256(60, 20)", None, None),
        ("bigquery", "DATETIME", "timestamp[us]", None, None),
    ],
)
def test_target_type_info_overrides(target, type_str, arrow, max_length, unit):
    info = target_type_info(get_target_meta(target), type_str)
    assert (info.arrow_type, info.max_length, info.length_unit) == (arrow, max_length, unit)


def test_safe_eval_is_restricted():
    names = {"length": 10, "precision": None, "charset": "UNICODE"}
    assert safe_eval("min(length * 3, 65535)", names) == 30
    assert safe_eval("precision is None and charset in ('UNICODE',)", names) is True
    assert safe_eval("precision > 5", names) is False  # None ordering is False, not an error
    for bad in ["__import__('os')", "length.__class__", "open('x')", "[c for c in 'ab']", "lambda: 1"]:
        with pytest.raises(ExpressionError):
            safe_eval(bad, names)
