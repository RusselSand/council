import pytest
from fastapi.testclient import TestClient

from spec_council.app import app
from spec_council.deps import get_store
from spec_council.spa import STATIC
from spec_council.store import InMemoryStore

client = TestClient(app)


def test_councils():
    assert client.get("/api/councils").status_code == 200


def test_settings():
    assert client.get("/api/settings").json()["models"]


def test_unknown_council_is_404():
    assert client.get("/api/councils/missing").status_code == 404


def test_created_council_is_readable():
    council_id = client.post("/api/councils").json()["id"]
    assert client.get(f"/api/councils/{council_id}").json()["status"] == "brief"


def test_unknown_api_path_is_json_404():
    for url in ("/api", "/api/councils/c1/unknown", "/api/nope"):
        res = client.get(url)
        assert res.status_code == 404, url
        assert res.headers["content-type"].startswith("application/json"), url


@pytest.mark.skipif(not (STATIC / "index.html").exists(), reason="фронт не собран")
def test_spa_fallback_for_page_links():
    res = client.get("/councils/c1/brief")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")


def test_startup_takes_the_store_the_routes_get():
    # Подменённое хранилище — и при старте: настоящий каталог данных тогда не нужен вовсе.
    started = []

    def replaced():
        started.append(True)
        return InMemoryStore()

    app.dependency_overrides[get_store] = replaced
    try:
        with TestClient(app):
            assert started
    finally:
        app.dependency_overrides.pop(get_store)
