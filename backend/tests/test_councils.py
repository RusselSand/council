"""Совет: участники, судья, правки с экрана ввода и запуск нарезки."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

from spec_council.api import councils as councils_api
from spec_council.app import app
from spec_council.config import DEFAULT_CONFIG
from spec_council.deps import get_agents, get_launcher, get_store
from spec_council.pipeline import start, start_structure

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


def test_edited_council_goes_to_the_top_even_on_the_same_day():
    first, second = new_council(), new_council()
    assert [c["id"] for c in client.get("/api/councils").json()][:2] == [second, first]

    client.patch(f"/api/councils/{first}", json={"brief": "правка"})
    assert [c["id"] for c in client.get("/api/councils").json()][:2] == [first, second]


class FakeAgents:
    """Модели совета без CLI: sol и fable подключены, отвечают одинаково."""

    def __init__(self, text):
        self.text = text
        self.asked = []
        self.fresh_under_lock = []
        self.on_probe = None   # что случится, пока идёт проверка входа
        self.online = {"sol", "fable"}
        self.probed = []       # (кого, fresh) — каждая проверка входа

    def availability(self, aliases, *, fresh=False):
        aliases = list(aliases)
        self.probed.append((frozenset(aliases), fresh))
        if fresh:
            self.fresh_under_lock.append(councils_api._starting.locked())
            if self.on_probe:
                self.on_probe()
        return {alias: alias in self.online for alias in aliases}

    def ask(self, model, prompt, key):
        self.asked.append(key)
        if "-slice-" in key:
            return json.dumps({"options": [{"fragments": [self.text], "reason": None}]})
        if "-structure-" in key:
            return json.dumps({"options": [{"groups": [{
                "id": "A", "title": "Воркер", "idea_fragment_ids": [1], "fragment_ids": [1],
                "missing_idea": False, "shared_fragment_ids": []}],
                "relations": [], "reason": None}]})
        return json.dumps({"labels": [{"id": 1, "options": [{"label": "idea", "reason": "цель"}]}]})

    def forget(self, keys):
        pass

    def identity(self, model):
        return model


@pytest.fixture
def agents():
    fake = FakeAgents("Хочу воркер для Codex CLI.")
    app.dependency_overrides[get_agents] = lambda: fake
    # Нарезка идёт тут же, а не в пуле: к возврату из post итог уже есть.
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    yield fake
    app.dependency_overrides.pop(get_agents)
    app.dependency_overrides.pop(get_launcher)


def test_slicing_runs_in_the_background_and_ends_with_labeled_fragments(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": agents.text})
    res = client.post(f"/api/councils/{council_id}/slicing")
    assert res.status_code == 202
    assert res.json()["slicing"]["state"] == "running"
    assert res.json()["status"] == "slices"

    slicing = client.get(f"/api/councils/{council_id}").json()["slicing"]
    assert slicing["state"] == "done"
    assert slicing["text"] == agents.text
    assert slicing["fragments"] == [{
        "id": 1, "text": agents.text, "label": "idea", "reason": "цель",
        "council_label": "idea",
        "decided_by": "agreed", "slice_note": None,
        "votes": [{"model": "sol", "labels": ["idea"]}, {"model": "fable", "labels": ["idea"]}],
    }]
    assert [s["state"] for s in slicing["steps"]] == ["done", "skipped", "done", "skipped"]


def test_empty_text_is_not_sliced(agents):
    res = client.post(f"/api/councils/{new_council()}/slicing")
    assert res.status_code == 422
    assert agents.asked == []


def test_models_without_a_connection_are_named(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": "текст", "judge": "astra"})
    res = client.post(f"/api/councils/{council_id}/slicing")
    assert res.status_code == 422
    assert res.json()["detail"] == "Нет подключения к моделям: Gemini Astra 3"


def test_running_slicing_is_not_started_twice(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": "текст"})
    get_store().update_council(council_id, {"slicing": start(["sol", "fable"], "fable")})
    assert client.post(f"/api/councils/{council_id}/slicing").status_code == 409


def test_slicing_of_unknown_council_is_404(agents):
    assert client.post("/api/councils/missing/slicing").status_code == 404


def test_settings_tell_which_models_can_run(agents):
    models = client.get("/api/settings").json()["models"]
    available = {m["alias"]: m["available"] for m in models}
    assert available == {"sol": True, "fable": True, "astra": False}


def sliced_council(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": agents.text})
    client.post(f"/api/councils/{council_id}/slicing")
    return council_id


def test_person_can_change_a_type_and_the_council_one_stays(agents):
    council_id = sliced_council(agents)
    run = client.get(f"/api/councils/{council_id}").json()["slicing"]["run"]
    res = client.patch(f"/api/councils/{council_id}",
                       json={"labels": {"1": "risk"}, "slicing_run": run})
    assert res.status_code == 200
    fragment = client.get(f"/api/councils/{council_id}").json()["slicing"]["fragments"][0]
    assert (fragment["label"], fragment["council_label"]) == ("risk", "idea")

    client.patch(f"/api/councils/{council_id}", json={"labels": {"1": "idea"}, "slicing_run": run})
    fragment = client.get(f"/api/councils/{council_id}").json()["slicing"]["fragments"][0]
    assert fragment["label"] == fragment["council_label"] == "idea"


@pytest.mark.parametrize(("labels", "status"), [
    ({"7": "risk"}, 422),
    ({"1": "goal"}, 422),
])
def test_bad_labels_are_refused(agents, labels, status):
    council_id = sliced_council(agents)
    run = client.get(f"/api/councils/{council_id}").json()["slicing"]["run"]
    res = client.patch(f"/api/councils/{council_id}", json={"labels": labels, "slicing_run": run})
    assert res.status_code == status


def test_labels_need_a_finished_slicing(agents):
    council_id = new_council()
    res = client.patch(f"/api/councils/{council_id}",
                       json={"labels": {"1": "risk"}, "slicing_run": "x"})
    assert res.status_code == 409


def test_login_check_before_a_start_runs_outside_the_lock(agents):
    sliced_council(agents)
    assert agents.fresh_under_lock == [False]


def test_ordinary_edits_do_not_wait_for_a_slicing_start():
    council_id = new_council()
    done = []
    with councils_api._starting:   # как будто идёт запуск нарезки
        edit = threading.Thread(daemon=True, target=lambda: done.append(
            client.patch(f"/api/councils/{council_id}", json={"name": "Проект"}).status_code))
        edit.start()
        edit.join(5)
    assert done == [200]


def test_labels_for_an_earlier_slicing_do_not_land_on_the_new_one(agents):
    council_id = sliced_council(agents)
    old_run = client.get(f"/api/councils/{council_id}").json()["slicing"]["run"]
    client.post(f"/api/councils/{council_id}/slicing")   # другая вкладка переделала нарезку
    res = client.patch(f"/api/councils/{council_id}",
                       json={"labels": {"1": "risk"}, "slicing_run": old_run})
    assert res.status_code == 409
    fragment = client.get(f"/api/councils/{council_id}").json()["slicing"]["fragments"][0]
    assert fragment["label"] == "idea"


def test_labels_without_their_slicing_run_are_refused(agents):
    council_id = sliced_council(agents)
    res = client.patch(f"/api/councils/{council_id}", json={"labels": {"1": "risk"}})
    assert res.status_code == 422


def test_start_that_lost_the_race_during_the_login_check_is_refused(agents):
    council_id = sliced_council(agents)

    def other_tab_starts_and_finishes():
        agents.on_probe = None
        finished = start(["sol", "fable"], "fable").model_copy(update={"state": "done"})
        get_store().update_council(council_id, {"slicing": finished})

    agents.on_probe = other_tab_starts_and_finishes
    assert client.post(f"/api/councils/{council_id}/slicing").status_code == 409
    assert len([k for k in agents.asked if "-slice-" in k]) == 2   # только первый запуск


def test_start_while_the_server_stops_leaves_a_failed_slicing_not_a_stuck_one(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": agents.text})

    def closed_pool(job):
        raise RuntimeError("cannot schedule new futures after shutdown")

    app.dependency_overrides[get_launcher] = lambda: closed_pool
    assert client.post(f"/api/councils/{council_id}/slicing").status_code == 503
    assert client.get(f"/api/councils/{council_id}").json()["slicing"]["state"] == "failed"


def test_lineup_changed_during_the_login_check_is_checked_again_outside_the_lock(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": agents.text})

    def judge_changes():
        agents.on_probe = None
        get_store().update_council(council_id, {"judge": "astra"})

    agents.on_probe = judge_changes
    res = client.post(f"/api/councils/{council_id}/slicing")
    assert res.status_code == 422
    assert res.json()["detail"] == "Нет подключения к моделям: Gemini Astra 3"
    assert agents.probed == [(frozenset({"sol", "fable"}), True),
                             (frozenset({"sol", "fable", "astra"}), True)]
    assert agents.fresh_under_lock == [False, False]


def test_lineup_that_keeps_changing_gives_up_with_503(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": agents.text})
    agents.online.add("astra")
    judges = iter(["astra", "fable", "astra", "fable"])
    agents.on_probe = lambda: get_store().update_council(council_id, {"judge": next(judges)})
    res = client.post(f"/api/councils/{council_id}/slicing")
    assert res.status_code == 503   # не 409: нарезку никто не запускал
    assert agents.fresh_under_lock == [False] * councils_api.PROBE_ATTEMPTS
    assert agents.asked == []



def test_groups_are_built_from_a_finished_slicing(agents):
    council_id = sliced_council(agents)
    res = client.post(f"/api/councils/{council_id}/structure")
    assert res.status_code == 202
    assert res.json()["status"] == "structure"
    structure = client.get(f"/api/councils/{council_id}").json()["structure"]
    assert structure["state"] == "done"
    assert [(g["id"], g["title"], g["fragment_ids"]) for g in structure["groups"]] == [
        ("A", "Воркер", [1])]
    assert structure["labels"] == {"1": "idea"}


def test_groups_need_a_finished_slicing(agents):
    council_id = new_council()
    client.patch(f"/api/councils/{council_id}", json={"brief": agents.text})
    assert client.post(f"/api/councils/{council_id}/structure").status_code == 422
    get_store().update_council(council_id, {"slicing": start(["sol", "fable"], "fable")})
    assert client.post(f"/api/councils/{council_id}/structure").status_code == 423


def test_slicing_again_drops_the_old_groups_and_waits_for_a_running_grouping(agents):
    council_id = sliced_council(agents)
    client.post(f"/api/councils/{council_id}/structure")
    running = start_structure(["sol", "fable"], "fable",
                              client_council(council_id).slicing)
    get_store().update_council(council_id, {"structure": running})
    assert client.post(f"/api/councils/{council_id}/slicing").status_code == 423

    finished = running.model_copy(update={"state": "done"})
    get_store().update_council(council_id, {"structure": finished})
    assert client.post(f"/api/councils/{council_id}/slicing").status_code == 202
    assert client.get(f"/api/councils/{council_id}").json()["structure"] is None


def client_council(council_id):
    return get_store().get_council(council_id)
