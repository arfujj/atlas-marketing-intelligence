"""API contract tests: served numbers equal the metric layer and stored runs, truth stays
hidden unless requested, and the optimizer honours its constraints."""

from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from atlas.api.app import Settings, create_app
from atlas.runs import RUNS_DIR, latest_run

pytestmark = pytest.mark.skipif(latest_run("halden") is None, reason="no Halden model run")


@pytest.fixture(scope="module")
def served_db(serving_db_path, halden_db, tmp_path_factory):
    """A copy: dbt keeps a read-write handle on the original in this process, and DuckDB
    refuses a second, read-only handle on the same file."""
    halden_db.execute("checkpoint")  # flush the WAL so the copy is complete
    dst = tmp_path_factory.mktemp("serve") / "atlas.duckdb"
    shutil.copy(serving_db_path, dst)
    return dst


@pytest.fixture(scope="module")
def client(served_db):
    return TestClient(create_app(Settings(db_path=served_db)))


def _keys(o, prefix=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


def test_metric_groups_sum_to_total(client):
    total = client.get("/halden/metrics/revenue").json()["rows"][0]["value"]
    by_geo = client.get("/halden/metrics/revenue", params={"group_by": "geo"}).json()
    assert sum(r["value"] for r in by_geo["rows"]) == pytest.approx(total)
    assert by_geo["provenance"]["evidence_type"] == "Simulated"


def test_metric_errors_are_client_errors(client):
    assert client.get("/halden/metrics/not_a_metric").status_code == 404
    assert client.get("/halden/metrics/revenue",
                      params={"group_by": "channel"}).status_code == 422


def test_truth_hidden_unless_revealed(client):
    hidden = client.get("/halden/measurement").json()
    assert not any(k.startswith("true") or k in ("truth", "graded", "abs_error")
                   for k in _keys(hidden))
    shown = client.get("/halden/measurement", params={"reveal_truth": True}).json()
    assert "truth" in shown and any(k == "true_roi" for k in _keys(shown["estimates"]))


def test_served_run_matches_stored_file(client):
    body = client.get("/halden/plan").json()
    rid = latest_run("halden")
    stored = json.loads((RUNS_DIR / rid / "summary.json").read_text())
    assert body["optimizer"] == stored["optimizer"]
    assert body["provenance"]["run_id"] == stored["mmm_runs"][stored["recommended_variant"]]


def test_optimizer_respects_budget_and_limits(client):
    mins = {"tiktok": 50_000.0}
    maxs = {"search_brand": 30_000.0}
    r = client.post("/halden/optimize", json={"budget": 420_000, "objective": "profit_first_order",
                                              "mins": mins, "maxs": maxs})
    assert r.status_code == 200
    ch = {c["channel"]: c for c in r.json()["channels"]}
    assert sum(c["proposed"] for c in ch.values()) == pytest.approx(420_000)
    assert ch["tiktok"]["proposed"] >= 50_000
    assert ch["search_brand"]["proposed"] <= 30_000


@pytest.mark.parametrize("body", [
    {"objective": "clicks"},
    {"budget": 100_000, "mins": {"tiktok": 150_000}},
    {"budget": -1},
    {"mins": {"not_a_channel": 1_000}},
])
def test_optimizer_rejects_invalid_requests(client, body):
    assert client.post("/halden/optimize", json=body).status_code == 422


def test_missing_runs_is_503(served_db, tmp_path):
    c = TestClient(create_app(Settings(db_path=served_db, runs_dir=tmp_path)))
    assert c.get("/halden/plan").status_code == 503
    assert c.get("/halden/metrics/revenue").status_code == 200
