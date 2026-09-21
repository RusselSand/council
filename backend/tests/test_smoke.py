import pytest
from fastapi.testclient import TestClient

from spec_council.app import app
from spec_council.spa import STATIC

client = TestClient(app)


def test_runs():
    assert client.get("/api/runs").status_code == 200


def test_settings():
    assert client.get("/api/settings").json()["models"]


def test_run_by_id():
    assert client.get("/api/runs/demo-1").json()["id"] == "demo-1"


def test_unknown_run_is_404():
    assert client.get("/api/runs/missing").status_code == 404


def test_created_run_is_readable():
    run_id = client.post("/api/runs").json()["id"]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "brief"


def test_unknown_api_path_is_json_404():
    for url in ("/api", "/api/runs/demo-1/unknown", "/api/nope"):
        res = client.get(url)
        assert res.status_code == 404, url
        assert res.headers["content-type"].startswith("application/json"), url


@pytest.mark.skipif(not (STATIC / "index.html").exists(), reason="фронт не собран")
def test_spa_fallback_for_page_links():
    res = client.get("/runs/demo-1/brief")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
