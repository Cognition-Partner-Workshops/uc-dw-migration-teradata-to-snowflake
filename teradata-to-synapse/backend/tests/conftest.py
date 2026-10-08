import subprocess
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config

FIXTURE_FILES = {
    "ddl/tables/01_dim_widget.sql": """
        CREATE MULTISET TABLE SALES.DIM_WIDGET, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL,
            CHECKSUM = DEFAULT
        (
            WIDGET_ID   INTEGER NOT NULL,
            NAME        VARCHAR(100) CHARACTER SET UNICODE NOT CASESPECIFIC,
            IS_ACTIVE   BYTEINT DEFAULT 1,
            LOADED_TS   TIMESTAMP(6)
        )
        PRIMARY INDEX (WIDGET_ID);
    """,
    "ddl/views/01_vw_latest_widget.sql": """
        REPLACE VIEW SALES.VW_LATEST_WIDGET AS
        SEL WIDGET_ID, NAME
        FROM SALES.DIM_WIDGET
        QUALIFY ROW_NUMBER() OVER (PARTITION BY WIDGET_ID ORDER BY LOADED_TS DESC) = 1;
    """,
    "dml/macros/m_widgets.sql": """
        REPLACE MACRO SALES.M_WIDGETS (p_id INTEGER) AS (
            SEL * FROM SALES.DIM_WIDGET WHERE WIDGET_ID = :p_id;
        );
    """,
    "dml/procs/sp_load.sql": """
        REPLACE PROCEDURE SALES.SP_LOAD()
        BEGIN
            INS INTO SALES.DIM_WIDGET SEL * FROM STG.WIDGET;
        END;
    """,
    "dml/scripts/load.bteq": """
        .LOGON tdprod/etl,secret;
        SEL COUNT(*) FROM SALES.DIM_WIDGET;
        .QUIT 0;
    """,
    # Ignored: outside ddl/ and dml/, or wrong extension.
    "scripts/other.sql": "SELECT 1;",
    "ddl/README.md": "# not sql",
}


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source_repo"
    for rel, body in FIXTURE_FILES.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(textwrap.dedent(body).strip() + "\n")
    git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "init.defaultBranch=main"]
    subprocess.run([*git, "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([*git, "-C", str(repo), "commit", "-qm", "init"], check=True)
    return repo


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "SOURCES_DIR", data / "sources")
    monkeypatch.setattr(config, "DB_PATH", data / "jobs.db")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "ALLOW_LOCAL_REPOS", True)
    from app.main import app

    with TestClient(app) as c:
        yield c
