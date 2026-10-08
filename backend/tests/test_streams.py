"""Потоки: подтверждение групп запускает поиск идеи, утверждение идеи — поиск вопросов;
повторы поисков, утверждение идеи и отбор вопросов."""

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
from spec_council.pipeline import start_idea, start_proposals, start_questions

client = TestClient(app)

TEXTS = {1: "Хочу базу знаний.", 2: "Полнотекстовый поиск.", 3: "Или бот в Slack.",
         4: "Бюджет — до $200.", 5: "Кто решает, что тред полезный?"}
LABELS = {1: "idea", 2: "proposal", 3: "proposal", 4: "constraint", 5: "question"}
IDEA_B = "Команда сама находит ответы"
IDEA_C = "Полезные треды не теряются"
MEASURE = "Как понять, что идея сработала?"
OPTION = "Считать долю вопросов, на которые ответила база"


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
        found = {"text": OPTION, "reason": "мерило идеи", "constraint_ids": ["F4"]}
        if "-proposal_discovery-" in key:
            return json.dumps({"proposals": [found]})
        if "-proposal_judge-" in key:
            return json.dumps({"status": "recommended", "proposal": found})
        if "-question_discovery-" in key:
            # Участники сходятся: недостающий вопрос и вопрос из текста, если он в группе.
            found = [{"text": MEASURE, "source": "discovered", "proposal_ids": [],
                      "reason": "мера"}]
            if TEXTS[5] in prompt:
                found.append({"text": "?", "source": "user", "source_question_id": "F5"})
            return json.dumps({"questions": found})
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


# --- вопросы

def asks(council_id, group):
    return client.post(f"/api/councils/{council_id}/streams/{group}/questions/discovery")


def choose(council_id, group, keep, added=(), revision=0, questions_run=None):
    run = questions_run or streams_of(council_id)[group].questions.run
    return client.post(f"/api/councils/{council_id}/streams/{group}/questions",
                       json={"run": "g1", "revision": revision, "questions_run": run,
                             "keep": list(keep), "added": list(added)})


def test_an_approved_idea_starts_the_search_for_questions(agents):
    council_id = grouped()
    confirm(council_id)
    res = approve(council_id, "C", IDEA_C)
    assert res.status_code == 200
    assert res.json()["streams"][2]["questions"]["state"] == "running"
    questions = streams_of(council_id)["C"].questions
    assert questions.state == "done" and questions.idea == IDEA_C
    assert [(q.id, q.text, q.source) for q in questions.questions] == [
        ("Q1", MEASURE, "discovered"), ("Q2", TEXTS[5], "user")]


def test_the_same_idea_keeps_its_questions_and_another_one_asks_again(agents):
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "B", IDEA_B)
    first = streams_of(council_id)["B"].questions.run
    assert choose(council_id, "B", ["Q1"]).status_code == 200
    approve(council_id, "B", f" {IDEA_B} ")
    assert streams_of(council_id)["B"].questions.run == first
    assert streams_of(council_id)["B"].scope is not None

    approve(council_id, "B", "Другая идея")
    stream = streams_of(council_id)["B"]
    assert stream.questions.run != first and stream.questions.idea == "Другая идея"
    assert stream.scope is None


def test_without_models_the_idea_is_approved_and_the_question_search_can_be_retried(agents):
    council_id = grouped()
    confirm(council_id)
    agents.online = set()
    assert approve(council_id, "A").status_code == 200
    stream = streams_of(council_id)["A"]
    assert stream.idea is not None
    assert stream.questions.state == "failed"
    assert stream.questions.error.startswith("Нет подключения к моделям")

    agents.online = {"sol", "fable"}
    assert asks(council_id, "A").status_code == 202
    assert streams_of(council_id)["A"].questions.state == "done"


def test_the_idea_does_not_change_while_its_questions_are_sought(agents):
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "B", IDEA_B)
    streams = [s.model_copy(update={"questions": start_questions(["sol"], "sol", IDEA_B)})
               if s.group == "B" else s for s in get_store().get_council(council_id).streams]
    get_store().update_council(council_id, {"streams": streams})
    res = approve(council_id, "B", "Другая идея")
    assert res.status_code == 423
    assert streams_of(council_id)["B"].idea.text == IDEA_B
    # Та же идея ничего не меняет — повтор (другая вкладка, потерянный ответ) не отказ.
    assert approve(council_id, "B", IDEA_B).status_code == 200
    assert streams_of(council_id)["B"].questions.state == "running"
    assert choose(council_id, "B", ["Q1"]).status_code == 409
    assert client.post(f"/api/councils/{council_id}/structure").status_code == 423


def test_the_scope_keeps_chosen_questions_and_adds_own_ones(agents):
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "C", IDEA_C)
    res = choose(council_id, "C", ["Q2"], ["  Кто платит за хостинг ", "кто платит за хостинг?",
                                           TEXTS[5]])
    assert res.status_code == 200
    scope = streams_of(council_id)["C"].scope
    assert [(q.id, q.text, q.source) for q in scope] == [
        ("Q2", TEXTS[5], "user"), ("Q3", "Кто платит за хостинг", "added")]
    assert asks(council_id, "C").status_code == 409     # отобранные заново не ищут


@pytest.mark.parametrize(("keep", "added", "problem"), [
    (["Q9"], [], "Нет вопросов: Q9"),
    ([], [], "хотя бы один"),
    ([], ["   "], "пуст"),
    ([], ["x" * 501], "длиннее"),
])
def test_a_senseless_scope_is_refused(agents, keep, added, problem):
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "C", IDEA_C)
    res = choose(council_id, "C", keep, added)
    assert res.status_code == 422
    assert problem in res.json()["detail"]
    assert streams_of(council_id)["C"].scope is None


def test_own_questions_differing_by_case_folding_stay_as_the_screen_shows_them(agents):
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "C", IDEA_C)
    assert choose(council_id, "C", [], ["Straße?", "STRASSE"]).status_code == 200
    assert [q.text for q in streams_of(council_id)["C"].scope] == ["Straße?", "STRASSE"]


def test_a_choice_made_for_an_earlier_search_is_refused(agents):
    # Другая вкладка нашла вопросы заново: их номера снова с Q1, и «Q1» — уже другой вопрос.
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "C", IDEA_C)
    res = choose(council_id, "C", ["Q1"], questions_run="прежний")
    assert res.status_code == 409
    assert "заново" in res.json()["detail"]
    assert streams_of(council_id)["C"].scope is None


def test_no_scope_before_the_idea(agents):
    council_id = grouped()
    confirm(council_id)
    assert choose(council_id, "C", [], ["Свой"], questions_run="нет").status_code == 409
    assert asks(council_id, "C").status_code == 409


# --- варианты и выбор

def chose(council_id, group, choices, revision=0, proposals_run=None):
    run = proposals_run or streams_of(council_id)[group].proposals.run
    return client.post(f"/api/councils/{council_id}/streams/{group}/choices",
                       json={"run": "g1", "revision": revision, "proposals_run": run,
                             "choices": [{"question_id": q, "proposal": p} for q, p in choices]})


def proposes(council_id, group):
    return client.post(f"/api/councils/{council_id}/streams/{group}/proposals/discovery")


def scoped_c(council_id, keep=("Q1", "Q2"), added=()):
    """Поток C: идея утверждена, вопросы отобраны — и совет уже нашёл к ним варианты."""
    approve(council_id, "C", IDEA_C)
    return choose(council_id, "C", list(keep), list(added))


def test_an_approved_scope_starts_the_search_for_proposals(agents):
    council_id = grouped()
    confirm(council_id)
    res = scoped_c(council_id)
    assert res.status_code == 200
    assert res.json()["streams"][2]["proposals"]["state"] == "running"
    proposals = streams_of(council_id)["C"].proposals
    assert proposals.state == "done"
    assert [(o.question_id, o.verdict, [(p.id, p.text, p.recommended, p.constraint_ids)
                                         for p in o.proposals]) for o in proposals.options] == [
        ("Q1", "recommended", [("P1", OPTION, True, [4])]),
        ("Q2", "recommended", [("P2", OPTION, True, [4])])]


def test_the_same_scope_keeps_its_proposals_and_another_one_searches_again(agents):
    council_id = grouped()
    confirm(council_id)
    scoped_c(council_id)
    first = streams_of(council_id)["C"].proposals.run
    assert chose(council_id, "C", [("Q1", "P1"), ("Q2", None)]).status_code == 200
    choose(council_id, "C", ["Q1", "Q2"])
    assert streams_of(council_id)["C"].proposals.run == first
    assert streams_of(council_id)["C"].choices is not None

    choose(council_id, "C", ["Q1"])
    stream = streams_of(council_id)["C"]
    assert stream.proposals.run != first and [o.question_id for o in stream.proposals.options] == [
        "Q1"]
    assert stream.choices is None


def test_another_idea_drops_the_proposals_and_the_choices(agents):
    council_id = grouped()
    confirm(council_id)
    scoped_c(council_id)
    chose(council_id, "C", [("Q1", "P1"), ("Q2", "P2")])
    approve(council_id, "C", "Другая идея")
    stream = streams_of(council_id)["C"]
    assert (stream.scope, stream.proposals, stream.choices) == (None, None, None)


def test_nothing_upstream_changes_while_proposals_are_sought(agents):
    council_id = grouped()
    confirm(council_id)
    scoped_c(council_id)
    stream = streams_of(council_id)["C"]
    sought = start_proposals(["sol"], "sol", stream.scope)
    get_store().update_council(council_id, {"streams": [
        s.model_copy(update={"proposals": sought}) if s.group == "C" else s
        for s in get_store().get_council(council_id).streams]})
    assert choose(council_id, "C", ["Q1"]).status_code == 423
    assert approve(council_id, "C", "Другая идея").status_code == 423
    assert choose(council_id, "C", ["Q1", "Q2"]).status_code == 200   # тот же отбор — повтор
    assert chose(council_id, "C", [("Q1", None), ("Q2", None)]).status_code == 409
    assert client.post(f"/api/councils/{council_id}/structure").status_code == 423


def test_a_choice_per_question_from_its_own_options(agents):
    council_id = grouped()
    confirm(council_id)
    scoped_c(council_id)
    res = chose(council_id, "C", [("Q2", "P2"), ("Q1", None)])
    assert res.status_code == 200
    choices = streams_of(council_id)["C"].choices
    assert [(c.question_id, c.proposal) for c in choices] == [("Q1", None), ("Q2", "P2")]
    assert proposes(council_id, "C").status_code == 409            # выбор уже утверждён


@pytest.mark.parametrize(("choices", "problem"), [
    ([("Q1", "P1")], "Нет выбора по вопросам: Q2"),
    ([("Q1", "P2"), ("Q2", None)], "У вопроса Q1 нет варианта P2"),
    ([("Q1", "F3"), ("Q2", None)], "У вопроса Q1 нет варианта F3"),
    ([("Q1", None), ("Q1", None), ("Q2", None)], "выбран дважды"),
    ([("Q1", None), ("Q2", None), ("Q7", None)], "Нет таких вопросов: Q7"),
])
def test_a_senseless_choice_is_refused(agents, choices, problem):
    council_id = grouped()
    confirm(council_id)
    scoped_c(council_id)
    res = chose(council_id, "C", choices)
    assert res.status_code == 422
    assert problem in res.json()["detail"]
    assert streams_of(council_id)["C"].choices is None


def test_a_choice_for_an_earlier_search_or_before_proposals_is_refused(agents):
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "C", IDEA_C)
    assert chose(council_id, "C", [], proposals_run="нет").status_code == 409
    choose(council_id, "C", ["Q1", "Q2"])
    res = chose(council_id, "C", [("Q1", None), ("Q2", None)], proposals_run="прежний")
    assert res.status_code == 409 and "заново" in res.json()["detail"]


def test_without_models_the_scope_is_approved_and_the_proposal_search_can_be_retried(agents):
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "C", IDEA_C)
    agents.online = set()
    assert choose(council_id, "C", ["Q1"]).status_code == 200
    proposals = streams_of(council_id)["C"].proposals
    assert proposals.state == "failed" and proposals.error.startswith("Нет подключения")
    agents.online = {"sol", "fable"}
    assert proposes(council_id, "C").status_code == 202
    assert streams_of(council_id)["C"].proposals.state == "done"
