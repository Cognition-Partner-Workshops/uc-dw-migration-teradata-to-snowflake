"""Offline comparison, spec, report, and mocked-runner contracts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bank_model import ROOT, digest
from parity.compare import apply_value_maps, compare_rows, read_expected
from parity.runner import run_object
from parity.spec import load_spec, validate_spec

_VALIDATION_SPEC = ROOT / "parity/objects/validation.json"
_VALIDATION_OUTPUTS = (
    json.loads(_VALIDATION_SPEC.read_text(encoding="utf-8")).get("outputs", [])
    if _VALIDATION_SPEC.is_file()
    else []
)
_VALIDATION_EXPECTED_READY = bool(_VALIDATION_OUTPUTS) and all(
    (ROOT / output["expected"]).is_file() for output in _VALIDATION_OUTPUTS
)


def _column(name: str, declared_type: str, plain: bool = False) -> dict[str, Any]:
    return {"name": name, "type": declared_type, "plain": plain}


def test_green_comparison():
    columns = [_column("ID", "INTEGER"), _column("AMOUNT", "DECIMAL(10,2)")]
    expected = [{"ID": 1, "AMOUNT": Decimal("1.20")}]
    result = compare_rows(expected, expected, columns, ["ID"])
    assert result["status"] == "green"
    assert result["L1"]["match"] and result["L2"]["match"]
    assert result["L3"]["match_percent"] == 100.0


def test_l1_mismatch_is_red():
    columns = [_column("ID", "INTEGER")]
    result = compare_rows([{"ID": 1}], [], columns, ["ID"])
    assert result["status"] == "red"
    assert result["L1"] == {"expected": 1, "actual": 0, "match": False}


def test_both_empty_is_green_with_vacuous_l3_match():
    columns = [_column("ID", "INTEGER")]
    result = compare_rows([], [], columns, ["ID"])
    assert result["status"] == "green"
    assert result["L3"]["match_percent"] == 100.0
    assert result["L3"]["vacuous"]


def test_decimal_value_change_is_red_with_l4_column_difference():
    columns = [_column("ID", "INTEGER"), _column("AMOUNT", "DECIMAL(10,2)")]
    result = compare_rows(
        [{"ID": 1, "AMOUNT": Decimal("1.20")}],
        [{"ID": 1, "AMOUNT": Decimal("1.21")}],
        columns,
        ["ID"],
    )
    assert result["status"] == "red"
    assert result["L4"][0]["columns"]["AMOUNT"] == {
        "expected": "1.20",
        "actual": "1.21",
        "representation": "canonical",
    }


def test_null_and_empty_string_are_distinct():
    columns = [_column("ID", "INTEGER"), _column("VALUE", "VARCHAR(20)", plain=True)]
    result = compare_rows(
        [{"ID": 1, "VALUE": None}],
        [{"ID": 1, "VALUE": ""}],
        columns,
        ["ID"],
    )
    assert result["status"] == "red"
    assert result["L4"][0]["columns"]["VALUE"]["expected"] is None
    assert result["L4"][0]["columns"]["VALUE"]["actual"] == ""


def test_duplicate_key_is_red_and_never_deduplicated():
    columns = [_column("ID", "INTEGER"), _column("VALUE", "VARCHAR(20)")]
    result = compare_rows(
        [{"ID": 1, "VALUE": "a"}, {"ID": 1, "VALUE": "b"}],
        [{"ID": 1, "VALUE": "a"}],
        columns,
        ["ID"],
    )
    assert result["status"] == "red"
    assert result["error"] == "Duplicate comparison key in expected"


def test_single_row_key_rejects_more_than_one_row():
    columns = [_column("COUNT", "INTEGER")]
    result = compare_rows([{"COUNT": 1}, {"COUNT": 2}], [{"COUNT": 1}], columns, [])
    assert result["status"] == "red"
    assert "Duplicate comparison key" in result["error"]


def test_open_question_can_explain_residual_without_mutating_expected():
    columns = [_column("ID", "INTEGER"), _column("STATUS", "VARCHAR(20)", plain=True)]
    expected = [{"ID": 1, "STATUS": "A"}]
    actual = [{"ID": 1, "STATUS": "B"}]
    question = {
        "id": "Q1",
        "column": "STATUS",
        "value_map": {"A": "B"},
    }
    baseline = compare_rows(expected, actual, columns, ["ID"])
    residual = compare_rows(apply_value_maps(expected, columns, [question]), actual, columns, ["ID"])
    assert baseline["status"] == "red"
    assert residual["status"] == "green"
    assert expected[0]["STATUS"] == "A"


def test_value_map_uses_the_original_value_for_each_mapping():
    columns = [_column("VALUE", "VARCHAR(20)", plain=True)]
    expected = [{"VALUE": "A"}, {"VALUE": "B"}]
    question = {"id": "Q1", "column": "VALUE", "value_map": {"A": "B", "B": "C"}}
    assert apply_value_maps(expected, columns, [question]) == [{"VALUE": "B"}, {"VALUE": "C"}]


def test_question_that_does_not_explain_other_column_difference_stays_red():
    columns = [
        _column("ID", "INTEGER"),
        _column("STATUS", "VARCHAR(20)", plain=True),
        _column("AMOUNT", "INTEGER"),
    ]
    expected = [{"ID": 1, "STATUS": "A", "AMOUNT": 2}]
    actual = [{"ID": 1, "STATUS": "B", "AMOUNT": 3}]
    question = {"id": "Q1", "column": "STATUS", "value_map": {"A": "B"}}
    residual = compare_rows(apply_value_maps(expected, columns, [question]), actual, columns, ["ID"])
    assert residual["status"] == "red"
    assert not residual["L2"]["match"] or not residual["L3"]["match"]


def test_text_profiles_and_l4_are_hashed_unless_plain():
    columns = [_column("ID", "INTEGER"), _column("NAME", "VARCHAR(20)")]
    result = compare_rows(
        [{"ID": 1, "NAME": "alice"}],
        [{"ID": 1, "NAME": "alicia"}],
        columns,
        ["ID"],
    )
    profile = result["L2"]["expected"]["NAME"]
    assert profile["min"] == digest("alice")
    assert profile["max"] == digest("alice")
    assert result["L4"][0]["columns"]["NAME"]["representation"] == "sha256"
    assert "key" in result["L4"][0] and result["L4"][0]["key"] == ["1"]

    plain_columns = [_column("ID", "INTEGER"), _column("NAME", "VARCHAR(20)", plain=True)]
    plain = compare_rows(
        [{"ID": 1, "NAME": "alice"}],
        [{"ID": 1, "NAME": "alicia"}],
        plain_columns,
        ["ID", "NAME"],
    )
    assert plain["L2"]["expected"]["NAME"]["min"] == "alice"
    assert plain["L4"][0]["key"] == ["1", "alice"]
    assert plain["L4"][0]["columns"]["NAME"]["expected"] == "alice"


def test_expected_csv_uses_pipe_null_token_and_spec_order(tmp_path: Path):
    path = tmp_path / "expected.csv"
    path.write_text("ID|VALUE\n1|\\N\n2|\n", encoding="utf-8")
    columns = [_column("ID", "INTEGER"), _column("VALUE", "VARCHAR(10)")]
    assert read_expected(path, columns) == [
        {"ID": 1, "VALUE": None},
        {"ID": 2, "VALUE": ""},
    ]
    path.write_text("VALUE|ID\nx|1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header mismatch"):
        read_expected(path, columns)


def _fixture_spec(root: Path) -> dict[str, Any]:
    (root / "parity" / "objects").mkdir(parents=True)
    (root / "parity" / "expected").mkdir(parents=True)
    (root / "snowflake").mkdir()
    (root / "data").mkdir()
    (root / "data" / "legacy.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (root / "parity" / "expected" / "DERIVATION.md").write_text("Derived.\n", encoding="utf-8")
    (root / "parity" / "expected" / "out.csv").write_text("ID\n1\n", encoding="utf-8")
    (root / "snowflake" / "out.sql").write_text("SELECT ID FROM T\n", encoding="utf-8")
    legacy_hash = hashlib.sha256((root / "data" / "legacy.sql").read_bytes()).hexdigest()
    return {
        "object": "fixture",
        "title": "Fixture",
        "legacy_source": "data/legacy.sql",
        "legacy_sha256": legacy_hash,
        "derivation": "parity/expected/DERIVATION.md",
        "seed": "verify",
        "deploy": [],
        "outputs": [
            {
                "name": "out",
                "sql": "snowflake/out.sql",
                "expected": "parity/expected/out.csv",
                "key": ["ID"],
                "columns": [{"name": "ID", "type": "INTEGER"}],
            }
        ],
        "waivers": [],
        "questions": [],
    }


def test_spec_validation_rejects_unknown_keys_missing_files_xor_and_bad_key(tmp_path: Path):
    spec = _fixture_spec(tmp_path)
    with pytest.raises(ValueError, match="unknown key"):
        validate_spec({**spec, "unexpected": True}, tmp_path)

    both_sql_and_table = json.loads(json.dumps(spec))
    both_sql_and_table["outputs"][0]["table"] = "DB.SCHEMA.TABLE"
    with pytest.raises(ValueError, match="exactly one"):
        validate_spec(both_sql_and_table, tmp_path)

    bad_key = json.loads(json.dumps(spec))
    bad_key["outputs"][0]["key"] = ["MISSING"]
    with pytest.raises(ValueError, match="key columns"):
        validate_spec(bad_key, tmp_path)

    missing = json.loads(json.dumps(spec))
    missing["outputs"][0]["sql"] = "snowflake/missing.sql"
    with pytest.raises(ValueError, match="file does not exist"):
        validate_spec(missing, tmp_path)


@pytest.mark.skipif(
    not _VALIDATION_EXPECTED_READY,
    reason="validation expected CSVs are being added separately",
)
def test_validation_object_references_are_present_when_expected_csvs_exist():
    spec, _ = load_spec("validation")
    for output in spec["outputs"]:
        assert (ROOT / output["expected"]).is_file()
        if "sql" in output:
            assert (ROOT / output["sql"]).is_file()


def test_validation_object_legacy_hash_matches_source():
    spec_path = ROOT / "parity/objects/validation.json"
    if not spec_path.exists():
        pytest.skip("validation object spec is being added separately")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    actual = hashlib.sha256((ROOT / spec["legacy_source"]).read_bytes()).hexdigest()
    assert spec["legacy_sha256"] == actual


def _mocked_fixture_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, actual_id: int
) -> tuple[dict[str, Any], int]:
    from parity import runner

    spec = _fixture_spec(tmp_path)
    spec["questions"] = [
        {
            "id": "Q1",
            "output": "out",
            "column": "ID",
            "value_map": {"1": 2},
            "question": "Is the identifier expected to change?",
            "decision_owner": "Migration lead",
            "status": "open",
        }
    ]
    spec_path = tmp_path / "parity" / "objects" / "fixture.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    class Cursor:
        description: list[tuple[str]] = []
        sfqid = "query-123"

        def execute(self, query: str) -> None:
            if query.strip().upper().startswith("SELECT"):
                self.description = [("ID",)]

        def fetchall(self) -> list[tuple[int]]:
            return [(actual_id,)]

        def close(self) -> None:
            return None

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            return None

    monkeypatch.setattr(runner, "_commit", lambda: "deadbeef")
    monkeypatch.setattr(runner.load_seed, "verify_manifest", lambda: {"as_of_date": "2026-01-31"})
    monkeypatch.setattr(runner.load_seed, "connect", lambda: Connection())
    monkeypatch.setattr(
        runner.load_seed,
        "verify",
        lambda *_: ({"tables": {}, "views": {}, "manifest_sha256": "manifest"}, True),
    )
    return run_object("fixture", "2026-01-31", root=tmp_path)


def test_mocked_runner_writes_derived_header_and_marks_green_question_not_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    report, code = _mocked_fixture_run(tmp_path, monkeypatch, 1)
    assert code == 0
    assert report["status"] == "green"
    assert report["outputs"][0]["query_id"] == "query-123"
    assert report["outputs"][0]["questions"][0]["status"] == "not observed"
    markdown = (tmp_path / "evidence" / "fixture" / "run.md").read_text(encoding="utf-8")
    assert markdown.startswith("# fixture / run: GREEN\n\n")
    assert (
        "**Reference: DERIVED, NOT EXECUTED — expected outputs were derived by hand from the frozen seed "
        "under Teradata semantics (see parity/expected/DERIVATION.md); no Teradata instance exists.**"
    ) in markdown


def test_mocked_runner_marks_an_explained_residual_amber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    report, code = _mocked_fixture_run(tmp_path, monkeypatch, 2)
    output = report["outputs"][0]
    assert code == 2
    assert report["status"] == output["status"] == "amber"
    assert output["residual"]["L1"]["match"]
    assert output["residual"]["L2"]["match"]
    assert output["residual"]["L3"]["match"]
    assert output["questions"][0]["status"] == "explains residual"
    markdown = (tmp_path / "evidence" / "fixture" / "run.md").read_text(encoding="utf-8")
    assert "Residual matched at L1–L3: L1=True, L2=True, L3=True (100.0%)." in markdown


def test_as_of_rejects_non_frozen_date_before_connect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from parity.cli import main
    from parity import runner

    monkeypatch.setattr(runner.load_seed, "verify_manifest", lambda: {"as_of_date": "2026-01-31"})
    monkeypatch.setattr(runner.load_seed, "connect", lambda: pytest.fail("must not connect"))
    assert main(["smoke", "--as-of", "2026-02-01"]) == 1
    assert "Invalid --as-of" in capsys.readouterr().out
