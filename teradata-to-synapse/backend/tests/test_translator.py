import re
from pathlib import Path

import pytest

from app import translator as t


def tr(sql: str, kind: str = t.TABLE) -> t.TranslationResult:
    return t.translate(kind, sql, "x.sql", "X")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_primary_index_becomes_hash_distribution_with_columnstore():
    res = tr("CREATE TABLE DB.T (ID INTEGER NOT NULL, V VARCHAR(10)) PRIMARY INDEX (ID);")
    out = norm(res.sql)
    assert "WITH ( DISTRIBUTION = HASH(ID), CLUSTERED COLUMNSTORE INDEX )" in out
    assert "PRIMARY INDEX" not in res.sql.split("CREATE TABLE", 1)[1]


def test_no_primary_index_is_round_robin():
    res = tr("CREATE MULTISET TABLE DB.T (ID INTEGER) NO PRIMARY INDEX;")
    assert "DISTRIBUTION = ROUND_ROBIN" in res.sql


@pytest.mark.parametrize("kind", ["SET", "MULTISET"])
def test_set_multiset_and_table_options_dropped(kind):
    sql = (
        f"CREATE {kind} TABLE DB.T, FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL, CHECKSUM = DEFAULT, "
        "DEFAULT MERGEBLOCKRATIO (ID INTEGER) PRIMARY INDEX (ID);"
    )
    body = tr(sql).sql.split("CREATE TABLE", 1)[1]
    for token in (kind + " ", "FALLBACK", "JOURNAL", "CHECKSUM", "MERGEBLOCKRATIO"):
        assert token not in body
    assert "CREATE TABLE DB.T" in tr(sql).sql


def test_no_fallback_dropped():
    assert "FALLBACK" not in tr("CREATE TABLE DB.T, NO FALLBACK (ID INTEGER) PRIMARY INDEX (ID);").sql


def test_data_type_mapping():
    res = tr(
        "CREATE TABLE DB.T (A BYTEINT, B TIMESTAMP(6), C TIMESTAMP, "
        "D VARCHAR(50) CHARACTER SET LATIN NOT CASESPECIFIC, E CHAR(3) CHARACTER SET UNICODE) PRIMARY INDEX (A);"
    )
    out = res.sql
    assert re.search(r"\bA\s+SMALLINT\b", out)
    assert re.search(r"\bB\s+DATETIME2\(6\)", out)
    assert re.search(r"\bC\s+DATETIME2\b", out)
    assert re.search(r"\bD\s+VARCHAR\(50\)", out)
    assert "CHARACTER SET" not in out
    assert "CASESPECIFIC" not in out
    assert "BYTEINT -> SMALLINT" in res.rules


def test_shorthand_expanded_but_not_inside_strings_or_identifiers():
    res = tr("REPLACE VIEW DB.V AS SEL 'SEL x' AS lit, SELLER, DEL_FLAG FROM DB.T;", t.VIEW)
    assert "CREATE VIEW DB.V AS" in res.sql
    assert "SELECT 'SEL x' AS lit, SELLER, DEL_FLAG" in res.sql


@pytest.mark.parametrize("short,full", [("INS", "INSERT"), ("UPD", "UPDATE"), ("DEL", "DELETE")])
def test_dml_shorthand(short, full):
    out = t.translate_query(f"{short} DB.T", t.TranslationResult(sql="", status=""))
    assert out.startswith(full)


def test_qualify_rewritten_to_row_number_subquery():
    res = tr(
        "REPLACE VIEW DB.V AS SEL ID, NAME FROM DB.T "
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY TS DESC) = 1;",
        t.VIEW,
    )
    out = norm(res.sql)
    assert "QUALIFY" not in res.sql
    assert "ROW_NUMBER() OVER (PARTITION BY ID ORDER BY TS DESC) AS qualify_rn" in out
    assert re.search(r"SELECT q\.ID, q\.NAME FROM \( SELECT ID, NAME, ROW_NUMBER\(\)", out)
    assert ") AS q WHERE q.qualify_rn = 1" in out


def test_qualify_with_group_by_after_keeps_group_by_inside():
    out = norm(
        t.translate_query(
            "SELECT A, COUNT(*) AS N FROM T QUALIFY RANK() OVER (ORDER BY COUNT(*) DESC) <= 3 GROUP BY A ORDER BY A",
            t.TranslationResult(sql="", status=""),
        )
    )
    assert "GROUP BY A ) AS q WHERE q.qualify_rn <= 3 ORDER BY A" in out


def test_macros_and_bteq_are_manual_review():
    assert tr("REPLACE MACRO DB.M AS (SEL 1;);", t.MACRO).status == t.MANUAL_REVIEW
    res = tr(".LOGON a/b,c;\nSEL 1;\n.QUIT 0;", t.SCRIPT)
    assert res.status == t.MANUAL_REVIEW
    assert res.manual_reason


@pytest.mark.parametrize(
    "path,text,expected",
    [
        ("ddl/tables/a.sql", "CREATE SET TABLE DB.A (X INT) PRIMARY INDEX (X);", (t.TABLE, "DB.A")),
        ("ddl/views/v.sql", "REPLACE VIEW DB.V AS SEL 1 AS X;", (t.VIEW, "DB.V")),
        ("dml/m.sql", "REPLACE MACRO DB.M AS (SEL 1;);", (t.MACRO, "DB.M")),
        ("dml/p.sql", "REPLACE PROCEDURE DB.P() BEGIN END;", (t.PROCEDURE, "DB.P")),
        ("dml/s.bteq", ".LOGON x/y,z;\nSEL 1;", (t.SCRIPT, "s")),
    ],
)
def test_classify(path, text, expected):
    assert t.classify(path, text) == expected


# This tool lives inside the demo repo, whose ddl/ is three levels above tests/.
SAMPLE = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(not (SAMPLE / "ddl" / "tables").is_dir(), reason="demo ddl/ not found")
def test_demo_repo_tables_and_views_convert():
    for f in sorted((SAMPLE / "ddl").rglob("*.sql")):
        rel = f.relative_to(SAMPLE).as_posix()
        kind, name = t.classify(rel, f.read_text())
        res = t.translate(kind, f.read_text(), rel, name)
        assert res.status in (t.CONVERTED, t.CONVERTED_WITH_WARNINGS), rel
        code = res.sql
        for token in ("MULTISET", "FALLBACK", "BYTEINT", "QUALIFY", "CHARACTER SET", "PRIMARY INDEX", "\nSEL "):
            assert token not in code, (rel, token)
