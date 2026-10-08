from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api import Services
from app.main import create_app


@pytest.fixture
def client(env, tmp_path):
    repo, planner, orch = env
    with TestClient(create_app(Services(repo, planner, orch, tmp_path / "data"))) as c:
        yield c


def _wait(client, run_id):
    for _ in range(300):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_source_and_targets(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/source/connection").json()["database"] == "RETAIL_DW"
    assert client.post("/api/source/test", json={}).json()["ok"]
    assert client.get("/api/source/databases").json() == ["RETAIL_DW"]
    assert len(client.get("/api/source/tables", params={"database": "RETAIL_DW"}).json()) == 6
    assert client.get("/api/source/tables/RETAIL_DW/ORDERS").json()["name"] == "ORDERS"
    assert {t["id"] for t in client.get("/api/targets").json()} == {"bigquery", "synapse", "redshift"}
    assert client.get("/api/targets/redshift").json()["config_fields"]
    assert client.get("/api/targets/nope").status_code == 404
    assert client.post("/api/targets/bigquery/test", json={"mode": "simulated", "connection": {}}).json()[
        "ok"
    ]


def test_cors(client):
    r = client.options(
        "/api/runs", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_plan_run_report_flow(client):
    plan = client.post("/api/plans", json={"tables": ["CUSTOMERS", "ORDERS"], "target_id": "redshift"}).json()
    assert plan["status"] == "draft" and len(plan["tables"]) == 2
    assert client.post("/api/runs", json={"plan_id": plan["id"]}).status_code == 409
    ov = client.post(
        f"/api/plans/{plan['id']}/overrides",
        json=[{"table": "CUSTOMERS", "column": "customer_city", "masking": "none"}],
    )
    assert ov.status_code == 200
    bad = client.post(f"/api/plans/{plan['id']}/overrides", json=[{"table": "X", "column": "y"}])
    assert bad.status_code == 422
    assert client.post(f"/api/plans/{plan['id']}/approve").json()["status"] == "approved"
    assert client.get(f"/api/plans/{plan['id']}").json()["status"] == "approved"

    run = client.post("/api/runs", json={"plan_id": plan["id"]}).json()
    run = _wait(client, run["id"])
    assert run["status"] == "succeeded"
    assert [r["id"] for r in client.get("/api/runs").json()] == [run["id"]]

    events = client.get(f"/api/runs/{run['id']}/events", headers={"Accept": "application/json"}).json()
    assert events and events[0]["seq"] == 1
    later = client.get(f"/api/runs/{run['id']}/events?after=5", headers={"Accept": "application/json"}).json()
    assert later[0]["seq"] == 6
    with client.stream("GET", f"/api/runs/{run['id']}/events?after={len(events) - 2}") as r:
        body = "".join(r.iter_text())
    assert r.headers["content-type"].startswith("text/event-stream")
    assert body.count("event: run_event") == 2 and f"id: {len(events)}" in body

    rep = client.get(f"/api/runs/{run['id']}/report").json()
    assert rep["totals"]["passed"] == 2
    csv = client.get(f"/api/runs/{run['id']}/report.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "CUSTOMERS" in csv.text
    rej = client.get(f"/api/runs/{run['id']}/rejects/orders").json()
    assert rej == {"rows": [], "total": 0}
    assert client.get(f"/api/runs/{run['id']}/rejects/NOPE").status_code == 404
    assert client.post(f"/api/runs/{run['id']}/retry", json={"tables": ["NOPE"]}).status_code == 422
    assert client.post(f"/api/runs/{run['id']}/resume").status_code == 200
    _wait(client, run["id"])
    assert client.get("/api/runs/missing").status_code == 404
