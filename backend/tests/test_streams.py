"""Потоки: подтверждение групп запускает поиск идеи, повтор поиска, утверждение идеи."""

import json

import pytest
from fastapi.testclient import TestClient

from spec_council.api.councils import reporter
from spec_council.api.streams import discovery
from spec_council.app import app
from spec_council.deps import get_agents, get_launcher, get_store
from spec_council.groups import arranged
from spec_council.models import (
    CouncilStatus,
    Group,
    LabeledFragment,
    Slicing,
    Structure,
    StructureProposal,
)
from spec_council.pipeline import start_idea

client = TestClient(app)

TEXTS = {1: "Хочу базу знаний.", 2: "Полнотекстовый поиск.", 3: "Или бот в Slack.",
         4: "Бюджет — до $200.", 5: "Кто решает, что тред полезный?"}
LABELS = {1: "idea", 2: "proposal", 3: "proposal", 4: "constraint", 5: "question"}
IDEA_B = "Команда сама находит ответы"
IDEA_C = "Полезные треды не теряются"


def grp(gid, fragments, ideas=()):
    return Group(id=gid, title=f"Группа {gid}", fragment_ids=list(fragments),
                 idea_fragment_ids=list(ideas), missing_idea=not ideas)


# A — с идеей в тексте, B и C — без; F4 общий у B и C.
GROUPS = arranged([grp("A", [1, 2], ideas=[1]), grp("B", [3, 4]), grp("C", [4, 5])])


class Agents:
    """Модели без CLI: идея группы — по её фрагментам, участники сходятся."""

    def __init__(self):
        self.online = {"sol", "fable"}
        self.asked = []

    def availability(self, aliases, *, fresh=False):
        return {alias: alias in self.online for alias in aliases}

    def ask(self, model, prompt, key):
        self.asked.append(key)
        if "-structure-" in key:
            return json.dumps({"options": [{"groups": [{
                "id": "A", "title": "Всё", "fragment_ids": [1, 2, 3, 4, 5]}], "relations": []}]})
        idea, evidence = (IDEA_B, ["F3"]) if TEXTS[3] in prompt else (IDEA_C, ["F5"])
        return json.dumps({"number": 1, "options": [
            {"idea": idea, "evidence": evidence, "reason": "общая цель"}]})

    def forget(self, keys):
        pass

    def identity(self, model):
        return model


@pytest.fixture
def agents():
    fake = Agents()
    app.dependency_overrides[get_agents] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()   # ход идёт тут же
    yield fake
    app.dependency_overrides.pop(get_agents)
    app.dependency_overrides.pop(get_launcher)


def grouped():
    council_id = client.post("/api/councils").json()["id"]
    slicing = Slicing(state="done", run="s1", steps=[], fragments=[
        LabeledFragment(id=i, text=TEXTS[i], label=label, reason="", council_label=label)
        for i, label in LABELS.items()])
    structure = Structure(state="done", run="g1", slicing_run="s1", labels=LABELS, steps=[],
                          groups=GROUPS, proposal=StructureProposal(groups=GROUPS, relations=[]))
    get_store().update_council(council_id, {"slicing": slicing, "structure": structure,
                                            "status": CouncilStatus.structure})
    return council_id


def confirm(council_id, revision=0):
    return client.post(f"/api/councils/{council_id}/structure/confirm",
                       json={"run": "g1", "revision": revision})


def approve(council_id, group, text=None, revision=0):
    body = {"run": "g1", "revision": revision, **({"text": text} if text is not None else {})}
    return client.post(f"/api/councils/{council_id}/streams/{group}/idea", json=body)


def seek(council_id, group):
    return client.post(f"/api/councils/{council_id}/streams/{group}/discovery")


def streams_of(council_id):
    return {s.group: s for s in get_store().get_council(council_id).streams}


def test_confirming_starts_the_search_for_groups_without_an_idea(agents):
    council_id = grouped()
    res = confirm(council_id)
    assert res.status_code == 200
    started = {s["group"]: s["discovery"] for s in res.json()["streams"]}
    assert started["A"] is None
    assert started["B"]["state"] == started["C"]["state"] == "running"

    streams = streams_of(council_id)
    assert streams["B"].discovery.state == "done"
    assert streams["B"].discovery.proposal.idea == IDEA_B
    assert streams["C"].discovery.proposal.idea == IDEA_C
    assert len([key for key in agents.asked if "-idea_discovery-" in key]) == 4


def test_without_models_the_groups_are_confirmed_and_the_search_can_be_retried(agents):
    council_id = grouped()
    agents.online = set()
    res = confirm(council_id)
    assert res.status_code == 200 and res.json()["status"] == "review"
    failed = streams_of(council_id)["B"].discovery
    assert failed.state == "failed"
    assert failed.error.startswith("Нет подключения к моделям")
    assert seek(council_id, "B").status_code == 422      # всё ещё нет подключения

    agents.online = {"sol", "fable"}
    assert seek(council_id, "B").status_code == 202
    assert streams_of(council_id)["B"].discovery.proposal.idea == IDEA_B
    assert streams_of(council_id)["C"].discovery.state == "failed"   # повтор — только у B
    assert seek(council_id, "A").status_code == 422      # идея записана в тексте


def test_the_idea_from_the_text_is_approved_as_is(agents):
    council_id = grouped()
    confirm(council_id)
    assert approve(council_id, "A", "Своя").status_code == 422
    res = approve(council_id, "A")
    assert res.status_code == 200
    idea = streams_of(council_id)["A"].idea
    assert (idea.text, idea.by, idea.evidence) == (TEXTS[1], "text", [1])


def test_the_council_idea_or_ones_own_is_approved_and_can_be_changed(agents):
    council_id = grouped()
    confirm(council_id)
    assert approve(council_id, "B", f"  {IDEA_B} ").status_code == 200
    idea = streams_of(council_id)["B"].idea
    assert (idea.text, idea.by, idea.evidence) == (IDEA_B, "council", [3])

    assert approve(council_id, "B", "Своя формулировка").status_code == 200
    idea = streams_of(council_id)["B"].idea
    assert (idea.text, idea.by, idea.evidence) == ("Своя формулировка", "human", [])
    assert approve(council_id, "B", "   ").status_code == 422
    assert seek(council_id, "B").status_code == 409      # утверждённую не ищут заново


def test_an_idea_is_not_approved_while_the_council_seeks_it(agents):
    council_id = grouped()
    confirm(council_id)
    streams = [s.model_copy(update={"discovery": start_idea(["sol"], "sol")})
               if s.group == "B" else s for s in get_store().get_council(council_id).streams]
    get_store().update_council(council_id, {"streams": streams})
    res = approve(council_id, "B", IDEA_B)
    assert res.status_code == 409 and "ищет" in res.json()["detail"]
    assert seek(council_id, "B").status_code == 409      # уже идёт


def test_an_idea_for_other_groups_is_refused(agents):
    council_id = grouped()
    assert approve(council_id, "A").status_code == 409   # не подтверждены
    confirm(council_id)
    assert approve(council_id, "A", revision=1).status_code == 409
    assert approve(council_id, "X").status_code == 409
    assert seek(council_id, "X").status_code == 409


def test_regrouping_waits_for_the_search_and_takes_the_confirmation_back(agents):
    council_id = grouped()
    confirm(council_id)
    streams = streams_of(council_id)
    running = [s.model_copy(update={"discovery": start_idea(["sol"], "sol")})
               if s.group == "C" else s for s in streams.values()]
    get_store().update_council(council_id, {"streams": running})
    assert client.post(f"/api/councils/{council_id}/structure").status_code == 423
    assert client.post(f"/api/councils/{council_id}/slicing").status_code == 423

    get_store().update_council(council_id, {"streams": list(streams.values())})
    res = client.post(f"/api/councils/{council_id}/structure")
    assert res.status_code == 202
    assert (res.json()["status"], res.json()["streams"]) == ("structure", None)


def test_a_search_whose_stream_is_gone_does_not_write_it_back(agents):
    council_id = grouped()
    agents.online = set()
    confirm(council_id)
    report = reporter(get_store(), council_id, discovery("B"))
    stranger = start_idea(["sol"], "sol").model_copy(update={"state": "done"})
    report(stranger)                                      # не тот ход
    assert streams_of(council_id)["B"].discovery.state == "failed"

    get_store().update_council(council_id, {"streams": None})
    report(stranger)                                      # потоков уже нет
    assert get_store().get_council(council_id).streams is None
