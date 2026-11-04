"""Offline contracts plus adversarial parity checks. Never connects to the warehouse."""

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from bank_model import (
    AS_OF,
    EXPECTED,
    FROZEN,
    ROOT,
    Column,
    TableDef,
    canonical,
    read_csv,
    summarize,
    tables,
    verify_manifest,
)
from derive_expected import derive
from generate_seed import dataset, render
from load_seed import compare


@pytest.fixture(scope="module")
def data():
    return dataset()


def test_frozen_bytes_are_reproducible():
    for name, content in render().items():
        assert (FROZEN / name).read_bytes() == content


def test_personal_fields_are_synthetic(data):
    fields = ["FIRST_NAME", "LAST_NAME", "EMAIL_ADDRESS", "PHONE_NUMBER", "ADDRESS_LINE_1", "ADDRESS_LINE_2"]
    with (ROOT / "data/seed/dim_customer_sample.csv").open() as stream:
        originals = {r[k] for r in csv.DictReader(stream, delimiter="|") for k in fields if r.get(k)}
    copied_values = sum(
        r.get(k) in originals for name in ["DIM_CUSTOMER", "STG_CUSTOMER"] for r in data[name] for k in fields
    )
    assert copied_values == 0


def test_jwt_role_and_host_isolation(monkeypatch):
    import os
    from unittest.mock import MagicMock

    import snowflake.connector
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from load_seed import connect

    pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        .decode()
    )
    for k, v in dict(
        SFNFR_ACCOUNT="test-account",
        SFNFR_USER="test-principal",
        SFNFR_ROLE="TEST_MIGRATION_ROLE",
        SFNFR_PRIVATE_KEY=pem,
        SNOWFLAKE_HOST="wrong.example.invalid",
    ).items():
        monkeypatch.setenv(k, v)
    mock = MagicMock()
    monkeypatch.setattr(snowflake.connector, "connect", mock)
    assert connect() is mock.return_value
    params = mock.call_args.kwargs
    assert params["authenticator"] == "SNOWFLAKE_JWT"
    assert params["role"] == "TEST_MIGRATION_ROLE"
    assert params["application"] == "Devin_Demo"
    assert "host" not in params and "SNOWFLAKE_HOST" not in os.environ
    mock.return_value.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
        "USE SECONDARY ROLES NONE"
    )


def test_independent_reference_is_frozen():
    assert derive() == json.loads(EXPECTED.read_text())


def test_manifest_counts_and_original_count_contract():
    manifest = verify_manifest()
    for name, table in tables().items():
        assert (
            len(read_csv(FROZEN / manifest["tables"][name]["file"], table))
            == manifest["tables"][name]["rows"]
        )
    with (ROOT / "data/validation/expected_row_counts.csv").open() as stream:
        for row in csv.DictReader(stream, delimiter="|"):
            assert manifest["tables"][row["TABLE_NAME"]]["rows"] == int(row["EXPECTED_ROW_COUNT"])
            assert row["AS_OF_DATE"] == AS_OF.isoformat()


@pytest.mark.parametrize("name", list(tables()))
def test_lossless_target_ddl(name):
    source = tables()[name]
    target = tables(ROOT / "snowflake/ddl/tables")[name]
    assert [c.name for c in source.columns] == [c.name for c in target.columns]
    for old, new in zip(source.columns, target.columns):
        assert new.declared_type.replace("TIMESTAMP_NTZ", "TIMESTAMP").replace(
            "SMALLINT", "BYTEINT"
        ) == old.declared_type.replace("SMALLINT", "BYTEINT")
        assert old.nullable == new.nullable


def test_required_fields_lengths_precision_and_keys(data):
    for name, table in tables().items():
        projected = [{c.name: row.get(c.name) for c in table.columns} for row in data[name]]
        assert len(summarize(projected, table)["hashes"]) == len(projected)
        for row in projected:
            for col in table.columns:
                value = row[col.name]
                assert col.nullable or value is not None
                if value is not None and col.declared_type.startswith(("VARCHAR(", "CHAR(")):
                    assert len(value) <= int(re.search(r"\((\d+)\)", col.declared_type)[1])
                if value is not None and col.declared_type.startswith("DECIMAL"):
                    precision, scale = map(int, re.search(r"\((\d+),(\d+)\)", col.declared_type).groups())
                    assert abs(value) < Decimal(10) ** (precision - scale)
                    assert value == value.quantize(Decimal(1).scaleb(-scale))


def test_date_span_and_holidays(data):
    dates = data["DIM_DATE"]
    assert dates[0]["CALENDAR_DATE"] == date(2000, 1, 1)
    assert dates[-1]["CALENDAR_DATE"] == date(2029, 12, 31)
    assert len(dates) == 10958
    assert next(r for r in dates if r["CALENDAR_DATE"] == date(2026, 4, 6))["IS_BUSINESS_DAY"] == 0


def test_staging_scenarios_are_real_conditions(data):
    staged = data["STG_TRANSACTIONS"]
    accounts = {a["ACCOUNT_ID"]: a for a in data["DIM_ACCOUNT"]}
    assert sum(r["ACCOUNT_ID"] not in accounts for r in staged) == 2
    groups = {
        label: [r for r in staged if r["DESCRIPTION_TEXT"] == label]
        for label in {r["DESCRIPTION_TEXT"] for r in staged}
    }
    assert len(groups["STRUCTURING"]) == 3
    assert all(
        40000 <= r["TRANSACTION_AMOUNT"] <= 50000 and r["TRANSACTION_TYPE"] == "CREDIT"
        for r in groups["STRUCTURING"]
    )
    assert groups["RAPID_CREDIT"][0]["TRANSACTION_AMOUNT"] >= 50000
    assert groups["RAPID_DEBIT"][0]["TRANSACTION_AMOUNT"] >= 45000
    intl = groups["NEW_CUSTOMER_INTL"]
    account = accounts[intl[0]["ACCOUNT_ID"]]
    customer = next(c for c in data["DIM_CUSTOMER"] if c["CUSTOMER_ID"] == account["CUSTOMER_ID"])
    assert (AS_OF - customer["ONBOARDING_DATE"]).days <= 90
    rate = next(r["EXCHANGE_RATE"] for r in data["DIM_EXCHANGE_RATES"] if r["FROM_CURRENCY"] == "EUR")
    assert sum(r["TRANSACTION_AMOUNT"] * rate for r in intl) >= 50000
    assert len({(r["TRANSACTION_DATE"], r["TRANSACTION_TIME"]) for r in groups["TIMESTAMP_TIE"]}) == 1
    customer_stage = data["STG_CUSTOMER"]
    assert len(customer_stage) == 5
    baseline = {r["CUSTOMER_ID"]: r for r in data["DIM_CUSTOMER"]}
    assert sum(r["CUSTOMER_ID"] not in baseline for r in customer_stage) == 2
    assert customer_stage[1]["RISK_SCORE"] != baseline[customer_stage[1]["CUSTOMER_ID"]]["RISK_SCORE"]
    assert customer_stage[2]["ADDRESS_LINE_1"] is None
    assert baseline[customer_stage[2]["CUSTOMER_ID"]]["ADDRESS_LINE_1"] is not None
    ties = Counter((r["ACCOUNT_KEY"], r["TRANSACTION_TS"]) for r in data["FACT_TRANSACTION"])
    assert max(ties.values()) >= 2


def test_reject_projection_and_frozen_clock():
    definitions = tables()
    assert definitions["STG_TRANSACTION_ERRORS"].columns[:-2] == definitions["STG_TRANSACTIONS"].columns
    for path in (ROOT / "snowflake/ddl").rglob("*.sql"):
        sql = re.sub(r"/\*.*?\*/|--[^\n]*", "", path.read_text(), flags=re.S)
        assert not re.search(r"\bCURRENT_(DATE|TIMESTAMP)\b", sql, re.I)


def test_canonicalization_keeps_null_empty_scale_and_timestamp():
    assert canonical(None, Column("C", "VARCHAR(20)", True)) is None
    assert canonical("", Column("C", "VARCHAR(20)", True)) == ""
    assert canonical("X ", Column("C", "VARCHAR(20)", True)) == "X "
    assert canonical("X ", Column("C", "CHAR(2)", True)) == "X"
    assert canonical(Decimal("1.540001"), Column("C", "DECIMAL(12,6)", True)) == "1.540001"
    assert canonical(datetime(2026, 1, 31), Column("C", "TIMESTAMP(6)", True)) == "2026-01-31 00:00:00.000000"
    assert canonical(time(12), Column("C", "TIME(0)", True)) == "12:00:00.000000"


def test_parity_does_not_hide_value_or_count_regression():
    table = TableDef(
        "DIM_PRODUCT", [Column("PRODUCT_ID", "INTEGER", False), Column("LABEL", "VARCHAR(50)", True)]
    )
    expected = summarize([dict(PRODUCT_ID=1, LABEL="complete")], table)
    changed = summarize([dict(PRODUCT_ID=1, LABEL="truncated")], table)
    report = compare(expected, changed)
    assert report["L1"]["match"] and not report["L2"]["match"]
    assert report["status"] == "red" and report["L3"]["match_percent"] == 0
    assert len(report["L4"]) == 1
    assert report["L4"][0]["key_sha256"] == hashlib.sha256('["1"]'.encode()).hexdigest()
    assert compare(expected, summarize([], table))["status"] == "red"
    assert compare(summarize([], table), summarize([], table))["status"] == "green"
    with pytest.raises(ValueError, match="Duplicate comparison key"):
        summarize([dict(PRODUCT_ID=1, LABEL="a"), dict(PRODUCT_ID=1, LABEL="b")], table)
