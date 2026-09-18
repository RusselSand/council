from fastapi.testclient import TestClient

from spec_council.app import app

client = TestClient(app)


def test_runs():
    assert client.get("/api/runs").status_code == 200


def test_settings():
    assert client.get("/api/settings").json()["models"]
