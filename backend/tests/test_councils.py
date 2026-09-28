"""Совет: участники, судья и правки с экрана ввода."""

import pytest
from fastapi.testclient import TestClient

from spec_council.app import app
from spec_council.config import DEFAULT_CONFIG

client = TestClient(app)


def new_council() -> str:
    return client.post("/api/councils").json()["id"]


def test_new_council_gets_default_participants_and_judge():
    council = client.get(f"/api/councils/{new_council()}").json()
    assert council["participants"] == DEFAULT_CONFIG.default_participants
    assert council["judge"] == DEFAULT_CONFIG.default_judge
    assert council["brief"] == ""


def test_settings_list_models_with_their_cli():
    settings = client.get("/api/settings").json()
    assert {model["cli"] for model in settings["models"]} == {"codex", "claude", "gemini"}
    assert settings["min_participants"] == 2


def test_patch_changes_only_what_was_sent():
    council_id = new_council()
    res = client.patch(f"/api/councils/{council_id}", json={"brief": "текст", "judge": "sol"})
    assert res.status_code == 200
    council = client.get(f"/api/councils/{council_id}").json()
    assert (council["brief"], council["judge"]) == ("текст", "sol")
    assert council["participants"] == DEFAULT_CONFIG.default_participants
    assert council["name"] == ""


def test_judge_does_not_have_to_take_part():
    council_id = new_council()
    res = client.patch(f"/api/councils/{council_id}",
                       json={"participants": ["sol", "fable"], "judge": "astra"})
    assert res.status_code == 200


def test_null_means_no_change():
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"name": "Проект"})
    client.patch(f"/api/councils/{council_id}", json={"name": None, "brief": "текст"})
    assert client.get(f"/api/councils/{council_id}").json()["name"] == "Проект"


@pytest.mark.parametrize("patch", [
    {"participants": ["sol"]},
    {"participants": ["sol", "sol"]},
    {"participants": ["sol", "nobody"]},
    {"judge": "nobody"},
    {"author": "sol"},
])
def test_invalid_patch_is_refused_and_changes_nothing(patch):
    council_id = new_council()
    before = client.get(f"/api/councils/{council_id}").json()
    assert client.patch(f"/api/councils/{council_id}", json=patch).status_code == 422
    assert client.get(f"/api/councils/{council_id}").json() == before


def test_patch_of_unknown_council_is_404():
    assert client.patch("/api/councils/missing", json={"brief": "текст"}).status_code == 404
