import copy
import json
import re
import shutil
from datetime import date

import pytest
import sqlglot

from tools import load_seed, seed
from tools import sf_attribution as sf


@pytest.fixture(scope="module")
def tables():
    return seed.build()


def test_repeat_frozen_counts_and_hashes(tables):
    again = seed.build()
    assert {t: seed.fingerprint(r) for t, r in tables.items()} == {
        t: seed.fingerprint(r) for t, r in again.items()}
    assert {t: len(r) for t, r in tables.items() if t != "SEED_FK_EXCEPTION"} == {
        "DIM_CUSTOMER": 15, "DIM_ACCOUNT": 20, "DIM_PRODUCT": 10, "DIM_BRANCH": 14,
        "DIM_DATE": 10958, "FACT_TRANSACTION": 0, "FACT_MONTHLY_ACCOUNT_SNAPSHOT": 0}
    assert tables["DIM_CUSTOMER"][0]["CUSTOMER_KEY"] == "1"
    assert tables["DIM_ACCOUNT"][-1]["ACCOUNT_KEY"] == "20"
    for table in seed.FILES:
        for row in tables[table]:
            assert row["ETL_INSERT_TS"] == seed.STAMP


def test_source_drift_rejected(tmp_path):
    for filename in seed.FILES.values():
        shutil.copy(seed.ROOT / "data/seed" / filename, tmp_path / filename)
    with (tmp_path / seed.FILES["DIM_ACCOUNT"]).open("a") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="frozen seed changed"):
        seed.build(tmp_path)


def test_all_officer_columns_are_found_and_masked(tables):
    discovered = {}
    for path in (seed.ROOT / "ddl/tables").glob("*.sql"):
        source = path.read_text()
        fields = re.findall(r"^\s+(\w*(?:OFFICER|MANAGER|MGR)\w*)\s+INTEGER", source, re.M)
        if fields:
            table = re.search(r"TABLE BANKING_DW\.(\w+)", source)[1]
            discovered[table] = tuple(fields)
    assert discovered == seed.OFFICER_FIELDS
    for table, fields in discovered.items():
        for row in tables[table]:
            assert all(row[field] is None for field in fields)
        poisoned = {field: "987654321" for field in fields}
        assert all(v is None for v in seed.mask_officers(table, poisoned).values())


def test_orphan_retained_with_one_exception_per_failed_fk(tables):
    modified = copy.deepcopy(tables)
    row = modified["DIM_ACCOUNT"][0]
    row.update(CUSTOMER_ID="-999", PRODUCT_ID="-999", BRANCH_ID="-999", RELATIONSHIP_MGR_ID="123456")
    rejected = [r for r in seed.exceptions(modified) if r["SOURCE_KEY"] == row["ACCOUNT_ID"]]
    assert len(rejected) == 3
    assert len(modified["DIM_ACCOUNT"]) == 20
    assert all(r["ROW_DATA"]["RELATIONSHIP_MGR_ID"] is None for r in rejected)
    assert "123456" not in seed.canonical(rejected)
    row["BRANCH_ID"] = None
    assert len([r for r in seed.exceptions(modified) if r["SOURCE_KEY"] == row["ACCOUNT_ID"]]) == 2


def test_calendar_edges_and_norwegian_holidays(tables):
    dates = {r["CALENDAR_DATE"]: r for r in tables["DIM_DATE"]}
    assert dates["2024-02-29"]["SAME_DAY_PREV_YEAR"] == "2023-02-28"
    assert dates["2026-04-03"]["HOLIDAY_NAME"] == "Good Friday"
    assert dates["2026-05-17"]["IS_BUSINESS_DAY"] == "0"
    assert dates["2026-12-31"]["IS_YEAR_END"] == "1"
    assert date.fromisoformat(dates["2000-01-01"]["CALENDAR_DATE"]) == date(2000, 1, 1)


@pytest.mark.parametrize("path", sorted((seed.ROOT / "snowflake/ddl").glob("*.sql")))
def test_ddl_snowflake_syntax_and_column_parity(path):
    sql = path.read_text()
    statements = sqlglot.parse(sql, read="snowflake", error_level="RAISE")
    assert statements and isinstance(statements[0], sqlglot.exp.Create)
    assert not re.search(r"\b(COMPRESS|CASESPECIFIC|FALLBACK|JOURNAL|COLLECT STATISTICS|PRIMARY INDEX|RANGE_N)\b", sql)
    assert sf.RUN_TOKEN in sql and sf.EXPIRES in sql
    legacy = seed.ROOT / "ddl/tables" / path.name
    if legacy.exists():
        source_cols = re.findall(r"^    (\w+)\s+(?:INTEGER|BIGINT|SMALLINT|BYTEINT|CHAR|VARCHAR|DECIMAL|DATE|TIME|TIMESTAMP)\b",
                                 legacy.read_text(), re.M)
        table = re.search(r"BANKING_DW\.(\w+)", sql)[1]
        assert source_cols == [c for c, _ in seed.columns(table)]


class GuardRunner(load_seed.Runner):
    def __init__(self, monitor=True, attached=True):
        super().__init__(None)
        self.monitor, self.attached, self.calls = monitor, attached, []

    def show(self, label, sql):
        self.calls.append(label)
        if "MONITORS" in sql:
            return [{"name": load_seed.MONITOR, "credit_quota": 5, "frequency": "MONTHLY",
                     "suspend_at": "100%", "suspend_immediately_at": "110%"}] if self.monitor else []
        return [{"name": load_seed.WAREHOUSE, "resource_monitor": load_seed.MONITOR if self.attached else "OTHER",
                 "size": "X-Small", "auto_suspend": 60, "max_cluster_count": 1}]


@pytest.mark.parametrize("monitor,attached", [(False, True), (True, False)])
def test_guard_fails_closed_before_compute(monitor, attached):
    runner = GuardRunner(monitor, attached)
    with pytest.raises(RuntimeError, match="no compute started"):
        runner.verify({})
    assert runner.calls[0] == "monitor_read_back"
    assert set(runner.calls) <= {"monitor_read_back", "warehouse_read_back"}


def test_guard_accepts_only_designated_monitor_and_warehouse():
    runner = GuardRunner()
    runner.guard()
    assert runner.calls == ["monitor_read_back", "warehouse_read_back"]


def test_attribution_tag_and_unique_run_ids():
    ep = sf.endpoint("cs_mig_td_schema_seed")
    first, second = (sf.make_run_id(ep.workload, "dev") for _ in range(2))
    assert first != second
    params = sf.connection_params(ep, phase="dev", account="example-account", private_key=b"memory-only",
                                  commit="a" * 40, run_id=first,
                                  session_url="https://example.com/sessions/" + "1" * 32)
    assert params["authenticator"] == "SNOWFLAKE_JWT"
    assert "private_key_file" not in params
    tag = json.loads(params["session_parameters"]["QUERY_TAG"])
    assert list(tag) == ["csid", "workload", "phase", "commit", "run_id", "session_url"]
    assert params["application"] == "Devin_Demo"
