"""Шаг «Документация»: черновик выгрузки потока в заметки, запись, повтор и перевод."""

import json
import re

import pytest

from spec_council.api import documents
from spec_council.app import app
from spec_council.deps import get_agents, get_launcher, get_notes_root
from spec_council.models import NotesDraft
from spec_council.notes import Catalog, Note, path_of, rendered
from tests.test_streams import (
    TASK,
    Agents,
    approves,
    client,
    confirm,
    decide,
    decided_c,
    get_store,
    grouped,
    streams_of,
)


@pytest.fixture(name="agents")
def models():
    """Модели без CLI, как в тестах потоков; ходы идут тут же."""
    fake = Agents()
    app.dependency_overrides[get_agents] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    yield fake
    app.dependency_overrides.pop(get_agents)
    app.dependency_overrides.pop(get_launcher)


@pytest.fixture
def notes_dir(tmp_path):
    root = tmp_path / "notes"
    app.dependency_overrides[get_notes_root] = lambda: root
    yield root
    app.dependency_overrides.pop(get_notes_root)


def drafts(council_id, group="C"):
    return client.post(f"/api/councils/{council_id}/streams/{group}/notes/draft",
                       json={"run": "g1", "revision": 0})


def writes(council_id, group="C", draft=None, edits=None, delete=()):
    run = draft or streams_of(council_id)[group].notes_draft.run
    return client.post(f"/api/councils/{council_id}/streams/{group}/notes",
                       json={"run": "g1", "revision": 0, "draft": run, "edits": edits or {},
                             "delete": list(delete)})


def cut_c():
    council_id = grouped()
    confirm(council_id)
    decided_c(council_id)
    approves(council_id, "C")
    return council_id


def test_a_cut_stream_is_drafted_then_written_as_linked_notes(agents, notes_dir):
    council_id = cut_c()
    res = drafts(council_id)
    assert res.status_code == 202
    draft = streams_of(council_id)["C"].notes_draft
    assert draft.state == "done" and draft.steps == []           # язык тот же — без моделей
    assert [(n.type, n.action) for n in draft.notes][:2] == [("idea", "create"),
                                                              ("open_question", "create")]
    assert {n.type for n in draft.notes} == {"idea", "open_question", "proposal", "adr",
                                             "outcome"}
    assert [(n.id, n.issue_id) for n in draft.numbers] == [("ISS-0001", "I1")]
    outcome = next(n for n in draft.notes if n.type == "outcome")
    assert f"ISS-0001: {TASK} O1" in outcome.text
    assert not notes_dir.exists()                                  # черновик файлов не пишет

    idea = draft.notes[0]
    assert writes(council_id, edits={idea.key: "Полезные треды не теряются."}).status_code == 200
    stream = streams_of(council_id)["C"]
    assert stream.notes.run == draft.run
    catalog = Catalog.load(notes_dir)
    assert catalog.problems() == []
    assert catalog.notes["IDEA-0001"].body == "Полезные треды не теряются."
    assert len(catalog.notes) == len(draft.notes)

    drafts(council_id)                                             # снова — ничего нового
    again = streams_of(council_id)["C"].notes_draft
    assert {n.action for n in again.notes} == {"same"}
    assert again.notes[0].text == "Полезные треды не теряются."    # правка человека осталась


def test_without_a_notes_folder_there_is_nothing_to_draft(agents):
    council_id = cut_c()
    res = drafts(council_id)
    assert res.status_code == 422 and "COUNCIL_NOTES" in res.json()["detail"]


def test_issues_must_be_cut_before_drafting(agents, notes_dir):
    council_id = grouped()
    confirm(council_id)
    decided_c(council_id)
    res = drafts(council_id)
    assert res.status_code == 409 and "нарежьте задачи" in res.json()["detail"]


def test_a_stale_draft_or_a_changed_catalog_is_not_written(agents, notes_dir):
    council_id = cut_c()
    drafts(council_id)
    assert writes(council_id, draft="другой").status_code == 409
    # Пока смотрели черновик, в каталог выгрузили другой поток — номер IDEA-0001 занят.
    other = Note("IDEA-0001", "idea", "Чужая идея.")
    path = path_of(notes_dir, other)
    path.parent.mkdir(parents=True)
    path.write_text(rendered(other), encoding="utf-8")
    res = writes(council_id)
    assert res.status_code == 409 and "поменялся" in res.json()["detail"]
    assert path.read_text(encoding="utf-8") == rendered(other)


def test_a_draft_whose_issue_numbers_were_taken_meanwhile_is_not_written(agents, notes_dir):
    council_id = cut_c()
    past = Note("OUT-0001", "outcome", "Чужой итог", ("ADR-0099",))
    path = path_of(notes_dir, past)
    path.parent.mkdir(parents=True)
    path.write_text(rendered(past), encoding="utf-8")
    drafts(council_id)
    assert [n.id for n in streams_of(council_id)["C"].notes_draft.numbers] == ["ISS-0001"]
    # Пока смотрели черновик, в чужой итог дописали задачу: ISS-0001 уже занят.
    taken = Note("OUT-0001", "outcome", "Чужой итог\n\nЗадачи:\n- ISS-0001: Чужая",
                 ("ADR-0099",))
    path.write_text(rendered(taken), encoding="utf-8")
    res = writes(council_id)
    assert res.status_code == 409 and "поменялся" in res.json()["detail"]
    assert not (notes_dir / "ideas").exists()


def test_a_failed_save_of_the_export_puts_the_notes_back(agents, notes_dir, monkeypatch):
    council_id = cut_c()
    drafts(council_id)

    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(get_store(), "update_council", full)
    with pytest.raises(OSError):
        writes(council_id)
    assert [path for path in notes_dir.rglob("*") if path.is_file()] == []


def test_decisions_wait_for_the_notes_translation(agents, notes_dir):
    council_id = cut_c()
    get_store().update_council(council_id, {"streams": [
        s.model_copy(update={"notes_draft": NotesDraft(state="running", run="n1",
                                                       issues=s.issues.run)})
        if s.group == "C" else s for s in get_store().get_council(council_id).streams]})
    res = decide(council_id, "C", [("Q1", None, None), ("Q2", None, None)])
    assert res.status_code == 423


def test_a_draft_that_cannot_be_built_says_why(agents, notes_dir):
    council_id = cut_c()
    # Вопрос пересматривает прошлое решение, а его из каталога уже убрали.
    streams = [s.model_copy(update={"scope": [s.scope[0].model_copy(update={
        "revisits": "ADR-0042"}), *s.scope[1:]]}) if s.group == "C" else s
        for s in get_store().get_council(council_id).streams]
    get_store().update_council(council_id, {"streams": streams})
    res = drafts(council_id)
    assert res.status_code == 422 and "пересматривает ADR-0042" in res.json()["detail"]


class Translating(Agents):
    """Судья переводит заметки: каждый текст — с пометкой EN."""

    def ask(self, model, prompt, key, workspace=None):
        if "-notes_translation-" in key:
            self.prompts["notes_translation"] = prompt
            notes = json.loads(prompt.split("## NOTES\n")[1])
            return json.dumps({"notes": [{"key": n["key"], "text": f"EN {n['text']}"}
                                         for n in notes]})
        return super().ask(model, prompt, key, workspace)


@pytest.fixture
def translating(agents, monkeypatch):
    fake = Translating()
    before = app.dependency_overrides[get_agents]
    app.dependency_overrides[get_agents] = lambda: fake
    monkeypatch.setattr(documents, "notes_language", lambda: "English")
    yield fake
    app.dependency_overrides[get_agents] = before


def test_notes_in_another_language_are_translated_by_the_judge(notes_dir, translating):
    council_id = cut_c()
    assert drafts(council_id).status_code == 202
    draft = streams_of(council_id)["C"].notes_draft
    assert draft.state == "done" and draft.language == "English"
    assert all(n.text.startswith("EN ") for n in draft.notes)
    assert "Polezn" not in translating.prompts["notes_translation"]
    assert re.search(r"translate the notes .* into English", translating.prompts[
        "notes_translation"])
    writes(council_id)
    drafts(council_id)                                             # переведённое — не заново
    again = streams_of(council_id)["C"].notes_draft
    assert {n.action for n in again.notes} == {"same"}
    assert again.steps == []                                       # судью не звали


def test_a_language_the_council_has_no_wording_for_is_finished_by_the_judge(
        notes_dir, translating, monkeypatch):
    monkeypatch.setattr(documents, "language", lambda: "French")
    monkeypatch.setattr(documents, "notes_language", lambda: "French")
    council_id = cut_c()
    drafts(council_id)
    draft = streams_of(council_id)["C"].notes_draft
    assert draft.state == "done" and draft.language == "French"
    assert all(n.text.startswith("EN ") for n in draft.notes)
    assert re.search(r"translate the notes .* into French", translating.prompts[
        "notes_translation"])


def test_without_models_a_translated_draft_is_recorded_failed(notes_dir, translating):
    council_id = cut_c()
    translating.online = set()
    drafts(council_id)
    draft = streams_of(council_id)["C"].notes_draft
    assert draft.state == "failed" and draft.error.startswith("Нет подключения")
    assert writes(council_id).status_code == 409


def test_settings_tell_where_the_notes_go(agents, notes_dir):
    assert client.get("/api/settings").json()["notes"] == str(notes_dir)
    assert get_store() is not None
