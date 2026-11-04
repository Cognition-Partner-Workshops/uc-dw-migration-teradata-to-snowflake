"""Frozen-input diagnostics, independent of converted Snowflake SQL."""

from collections import defaultdict

from bank_model import AS_OF, FROZEN, ROOT, read_csv, tables, verify_manifest
from parity.compare import read_expected
from parity.spec import load_expected_failure, load_spec


def test_daily_balance_check_reference_and_source_contract():
    import hashlib

    spec, _ = load_spec("daily_balance_check")
    assert hashlib.sha256((ROOT / spec["legacy_source"]).read_bytes()).hexdigest() == spec["legacy_sha256"]
    contract = load_expected_failure(ROOT / spec["outputs"][0]["expected_failure"])
    assert contract["legacy_outcome"] == "failure_no_relational_result"
    assert contract["question"]["status"] == "open"
    assert spec["seed"] == "verify"


def test_timestamp_tie_reference_matches_frozen_inputs_without_running_target_sql():
    manifest = verify_manifest()
    definitions = tables()
    data = {
        name: read_csv(FROZEN / manifest["tables"][name]["file"], definitions[name])
        for name in ("DIM_ACCOUNT", "DIM_CUSTOMER", "FACT_TRANSACTION")
    }
    accounts = [a for a in data["DIM_ACCOUNT"] if a["CURRENT_FLAG"] == "Y"]
    customers = [c for c in data["DIM_CUSTOMER"] if c["CURRENT_FLAG"] == "Y"]
    candidates = {"summary_candidates": [], "alert_candidates": []}
    for txn in data["FACT_TRANSACTION"]:
        if txn["TRANSACTION_DATE"] != AS_OF:
            continue
        for account in accounts:
            if account["ACCOUNT_KEY"] != txn["ACCOUNT_KEY"]:
                continue
            if account["ACCOUNT_STATUS"] == "ACTIVE":
                candidates["summary_candidates"].append(txn)
            if (
                account["ACCOUNT_TYPE"] not in {"CREDIT_CARD", "LOAN"}
                and txn["RUNNING_BALANCE"] is not None and txn["RUNNING_BALANCE"] < 0
            ):
                for customer in customers:
                    if customer["CUSTOMER_ID"] == account["CUSTOMER_ID"]:
                        candidates["alert_candidates"].append(txn)

    actual = []
    for population, rows in candidates.items():
        groups = defaultdict(list)
        by_account = defaultdict(list)
        for row in rows:
            assert row["TRANSACTION_TS"] is not None
            groups[row["ACCOUNT_KEY"], row["TRANSACTION_TS"]].append(row)
            by_account[row["ACCOUNT_KEY"]].append(row)
        tied = [group for group in groups.values() if len(group) > 1]
        latest = [
            groups[account, max(row["TRANSACTION_TS"] for row in transactions)]
            for account, transactions in by_account.items()
        ]
        actual.append({
            "POPULATION": population,
            "ELIGIBLE_ROWS": len(rows),
            "ELIGIBLE_ACCOUNTS": len(by_account),
            "TIED_TIMESTAMP_GROUPS": len(tied),
            "ROWS_IN_TIES": sum(map(len, tied)),
            "LATEST_TIED_ACCOUNTS": sum(len(group) > 1 for group in latest),
            "LATEST_CONFLICTING_BALANCE_ACCOUNTS": sum(
                len({row["RUNNING_BALANCE"] for row in group}) > 1 for group in latest
            ),
        })
    spec, _ = load_spec("daily_balance_check")
    output = spec["outputs"][1]
    expected = read_expected(ROOT / output["expected"], output["columns"])
    assert actual == expected
