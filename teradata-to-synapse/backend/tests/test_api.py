import io
import zipfile


def scan(client, sample_repo):
    r = client.post("/jobs", json={"repo_url": str(sample_repo)})
    assert r.status_code == 201, r.text
    return r.json()


def test_scan_returns_inventory_grouped_by_type(client, sample_repo):
    job = scan(client, sample_repo)
    inv = job["inventory"]
    assert set(inv) == {"table", "view", "macro", "stored_procedure", "script"}
    assert [o["rel_path"] for o in inv["table"]] == ["ddl/tables/01_dim_widget.sql"]
    assert [o["object_name"] for o in inv["view"]] == ["SALES.VW_LATEST_WIDGET"]
    assert [o["rel_path"] for o in inv["script"]] == ["dml/scripts/load.bteq"]
    assert len(inv["macro"]) == len(inv["stored_procedure"]) == 1
    assert job["total_objects"] == 5  # scripts/other.sql and ddl/README.md ignored
    assert job["status"] == "scanned"
    assert all(o["status"] == "pending" for objs in inv.values() for o in objs)


def test_convert_download_and_report(client, sample_repo):
    job_id = scan(client, sample_repo)["job_id"]
    assert client.get(f"/jobs/{job_id}/download").status_code == 409

    r = client.post(f"/jobs/{job_id}/convert")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "converted"
    statuses = {o["object_type"]: o["status"] for objs in job["inventory"].values() for o in objs}
    assert statuses["table"] in ("converted", "converted_with_warnings")
    assert statuses["macro"] == statuses["script"] == "manual_review"

    table = job["inventory"]["table"][0]
    detail = client.get(f"/jobs/{job_id}/objects/{table['id']}").json()
    assert "MULTISET" in detail["source_sql"]
    assert "DISTRIBUTION = HASH(WIDGET_ID)" in detail["generated_sql"]
    assert detail["output_path"] == "synapse_ddl/tables/01_dim_widget.sql"

    served = client.get(f"/output/{job_id}/synapse_ddl/tables/01_dim_widget.sql")
    assert served.status_code == 200 and "CLUSTERED COLUMNSTORE INDEX" in served.text

    assert client.get(f"/output/{job_id}/../../data/jobs.db").status_code == 404

    r = client.get(f"/jobs/{job_id}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "SQL_TRANSLATION_NOTES.md" in names
    assert "synapse_ddl/tables/01_dim_widget.sql" in names
    assert "synapse_ddl/views/01_vw_latest_widget.sql" in names
    assert not any(n.startswith("synapse_ddl/") and "macro" in n for n in names)

    notes = zipfile.ZipFile(io.BytesIO(r.content)).read("SQL_TRANSLATION_NOTES.md").decode()
    manual = notes.split("## Manual-review items", 1)[1].split("## Auto-converted objects", 1)[0]
    for name in ("SALES.M_WIDGETS", "load", "SALES.SP_LOAD"):
        assert f"`{name}`" in manual
    assert client.get(f"/jobs/{job_id}/report").text == notes


def test_convert_subset_marks_job_partial(client, sample_repo):
    job = scan(client, sample_repo)
    tid = job["inventory"]["table"][0]["id"]
    r = client.post(f"/jobs/{job['job_id']}/convert", json={"object_ids": [tid]})
    assert r.json()["status"] == "partially_converted"
    assert r.json()["counts_by_status"]["pending"] == 4


def test_job_state_persisted_in_sqlite(client, sample_repo):
    from app import config, db

    job_id = scan(client, sample_repo)["job_id"]
    assert config.DB_PATH.is_file()
    assert db.get_job(job_id)["repo_url"] == str(sample_repo)
    assert client.get(f"/jobs/{job_id}").json()["total_objects"] == 5


def test_errors(client):
    assert client.post("/jobs", json={"repo_url": "ftp://example.com/x"}).status_code == 400
    assert client.post("/jobs", json={"repo_url": "http://github.com/org/repo"}).status_code == 400
    assert client.post("/jobs", json={"repo_url": "--upload-pack=evil"}).status_code == 400
    assert client.post("/jobs", json={"repo_url": "file:///nonexistent/repo"}).status_code == 400
    assert client.get("/jobs/nope").status_code == 404
    assert client.post("/jobs/nope/convert").status_code == 404
    assert client.get("/jobs/nope/download").status_code == 404
