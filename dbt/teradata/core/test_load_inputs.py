"""Input-loader checks independent of the accepted fixture and baseline."""

import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

SPEC = importlib.util.spec_from_file_location("core_loader", Path(__file__).with_name("load_inputs.py"))
loader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(loader)


@pytest.mark.parametrize("rows", [[], ["1|\\N", "2|hello"]])
def test_load_inputs(tmp_path, monkeypatch, rows):
    frozen = tmp_path / "fixtures/frozen"
    frozen.mkdir(parents=True)
    (frozen / "sample.csv").write_text("ID|TEXT\n" + "\n".join(rows))
    (frozen / "manifest.json").write_text(json.dumps({"tables": {"SAMPLE": {
        "columns": ["ID", "TEXT"], "file": "sample.csv", "rows": len(rows)
    }}}))
    path = tmp_path / "test.duckdb"
    monkeypatch.setenv("TD_DUCKDB_PATH", str(path))
    monkeypatch.setattr(loader, "ROOT", tmp_path)
    monkeypatch.setattr(loader, "CONTRACT", {"SAMPLE": {"ID": "INTEGER", "TEXT": "VARCHAR"}})
    loader.load()
    with duckdb.connect(str(path)) as con:
        assert con.execute("SELECT count(*) FROM td_src_core.SAMPLE").fetchone()[0] == len(rows)
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='main'").fetchone()[0] == 0
        if rows:
            assert con.execute("SELECT TEXT FROM td_src_core.SAMPLE WHERE ID=1").fetchone()[0] is None


def test_bad_contract(tmp_path, monkeypatch):
    frozen = tmp_path / "fixtures/frozen"
    frozen.mkdir(parents=True)
    (frozen / "manifest.json").write_text(json.dumps({"tables": {"SAMPLE": {"columns": ["WRONG"]}}}))
    monkeypatch.setenv("TD_DUCKDB_PATH", str(tmp_path / "bad.duckdb"))
    monkeypatch.setattr(loader, "ROOT", tmp_path)
    monkeypatch.setattr(loader, "CONTRACT", {"SAMPLE": {"ID": "INTEGER"}})
    with pytest.raises(ValueError, match="Fixture columns differ: SAMPLE"):
        loader.load()
