"""Шаг «Документация»: черновик выгрузки потока в заметки, запись, повтор и перевод."""

import hashlib
import json
import re
import threading

import pytest

from spec_council.api import documents
from spec_council.api.councils import council_lock
from spec_council.app import app
from spec_council.deps import (
    get_agents,
    get_launcher,
    get_notes_of,
    get_projects,
    get_repositories,
)
from spec_council.models import ExportedNote, NotesDraft, ProjectDraft
from spec_council.notes import Catalog, Note, path_of, rendered
from spec_council.projects import Projects
from tests.test_project import put
from tests.test_streams import (
    OWN,
    WHY,
    Agents,
    approves,
    chose,
    chosen_c,
    client,
    confirm,
    decide,
    decided_c,
    free_c,
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
    app.dependency_overrides[get_notes_of] = lambda: lambda council: root
    yield root
    app.dependency_overrides.pop(get_notes_of)


def drafts(council_id, group="C"):
    return client.post(f"/api/councils/{council_id}/streams/{group}/notes/draft",
                       json={"run": "g1", "revision": 0})


def writes(council_id, group="C", draft=None, edits=None, delete=()):
    run = draft or streams_of(council_id)[group].notes_draft.run
    return client.post(f"/api/councils/{council_id}/streams/{group}/notes",
                       json={"run": "g1", "revision": 0, "draft": run, "edits": edits or {},
                             "delete": list(delete)})


def approved_c():
    """Поток C, где решены оба вопроса: итог ничто не держит, и его утвердили."""
    council_id = grouped()
    confirm(council_id)
    free_c(council_id)
    assert approves(council_id, "C").status_code == 200
    return council_id


def test_an_approved_stream_is_drafted_then_written_as_linked_notes(agents, notes_dir):
    council_id = approved_c()
    res = drafts(council_id)
    assert res.status_code == 202
    draft = streams_of(council_id)["C"].notes_draft
    assert draft.state == "done" and draft.steps == []           # язык тот же — без моделей
    assert [(n.type, n.action) for n in draft.notes][:2] == [("idea", "create"),
                                                              ("open_question", "create")]
    assert {n.type for n in draft.notes} == {"idea", "open_question", "proposal", "adr",
                                             "outcome"}
    outcome = next(n for n in draft.notes if n.type == "outcome")
    assert "ISS-" not in outcome.text                              # задач в итоге нет
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


def test_marking_what_an_own_option_refines_leaves_the_export_stale(agents, notes_dir):
    council_id = grouped()
    confirm(council_id)
    chosen_c(council_id, (("Q1", None, OWN), ("Q2", "P2")))
    assert decide(council_id, "C", [("Q1", "P3", WHY), ("Q2", "P2", WHY)]).status_code == 200
    assert approves(council_id, "C").status_code == 200
    drafts(council_id)
    assert writes(council_id).status_code == 200
    drafts(council_id)
    assert chose(council_id, "C", [("Q1", None, OWN, "P1"), ("Q2", "P2")]).status_code == 200
    stream = streams_of(council_id)["C"]
    # Проверка и итоги те же, а заметки легли бы иначе: правка встаёт в заметку P1.
    assert stream.decisions is not None and stream.outcomes.approved
    assert stream.notes_draft is None and stream.notes.outcomes == ""
    drafts(council_id)
    vanished = streams_of(council_id)["C"].notes_draft.vanished
    assert [(v.type, v.text) for v in vanished] == [("proposal", OWN)]


def test_without_a_notes_folder_there_is_nothing_to_draft(agents):
    council_id = approved_c()                                             # совет без проекта
    res = drafts(council_id)
    assert res.status_code == 422 and "Папки документации нет" in res.json()["detail"]


def test_notes_go_to_the_documentation_folder_of_the_council_project(agents, tmp_path):
    projects = Projects()
    project = projects.create_project(ProjectDraft(name="Кромка", notes="app/docs"))
    app.dependency_overrides[get_projects] = lambda: projects
    app.dependency_overrides[get_repositories] = lambda: tmp_path
    try:
        council_id = approved_c()
        assert client.patch(f"/api/councils/{council_id}",
                            json={"project": project.id}).status_code == 200
        assert drafts(council_id).status_code == 202
        assert writes(council_id).status_code == 200
    finally:
        app.dependency_overrides.pop(get_projects)
        app.dependency_overrides.pop(get_repositories)
    root = (tmp_path / "app" / "docs").resolve()
    assert streams_of(council_id)["C"].notes.root == str(root)
    assert "IDEA-0001" in Catalog.load(root).notes


def test_a_folder_changed_while_the_write_waits_for_the_lock_is_not_written_into(agents, tmp_path):
    projects = Projects()
    project = projects.create_project(ProjectDraft(name="Кромка", notes="first"))
    app.dependency_overrides[get_projects] = lambda: projects
    app.dependency_overrides[get_repositories] = lambda: tmp_path
    result = []
    try:
        council_id = approved_c()
        client.patch(f"/api/councils/{council_id}", json={"project": project.id})
        assert drafts(council_id).status_code == 202
        with council_lock:
            worker = threading.Thread(target=lambda: result.append(writes(council_id)))
            worker.start()
            worker.join(0.3)                                       # запись ждёт замка
            # А папку проекта тем временем сменили — под тем же замком, что и запись.
            projects.update_project(project.id, ProjectDraft(name="Кромка", notes="second"))
        worker.join(10)
    finally:
        app.dependency_overrides.pop(get_projects)
        app.dependency_overrides.pop(get_repositories)
    assert result[0].status_code == 409 and "другой папки" in result[0].json()["detail"]
    assert not (tmp_path / "first").exists() and not (tmp_path / "second").exists()


def test_a_draft_waiting_for_the_lock_is_built_for_the_folder_it_finds_there(agents, tmp_path):
    projects = Projects()
    project = projects.create_project(ProjectDraft(name="Кромка", notes="first"))
    app.dependency_overrides[get_projects] = lambda: projects
    app.dependency_overrides[get_repositories] = lambda: tmp_path
    result = []
    try:
        council_id = approved_c()
        client.patch(f"/api/councils/{council_id}", json={"project": project.id})
        with council_lock:
            worker = threading.Thread(target=lambda: result.append(drafts(council_id)))
            worker.start()
            worker.join(0.3)                                       # сборка ждёт замка
            projects.update_project(project.id, ProjectDraft(name="Кромка", notes="second"))
        worker.join(10)
        assert result[0].status_code == 202
        assert streams_of(council_id)["C"].notes_draft.root == str((tmp_path / "second").resolve())
        assert writes(council_id).status_code == 200
    finally:
        app.dependency_overrides.pop(get_projects)
        app.dependency_overrides.pop(get_repositories)
    assert (tmp_path / "second").exists() and not (tmp_path / "first").exists()


def test_a_project_with_unselected_decisions_sends_the_stream_back_before_drafting(
        agents, notes_dir, tmp_path):
    council_id = approved_c()                       # вопросы искали без решений: в папке их не было
    # Совету выбрали проект, в папке которого есть прошлые решения: поток их не отбирал.
    other = put(tmp_path / "other")
    app.dependency_overrides[get_notes_of] = lambda: lambda council: other
    res = drafts(council_id)
    assert res.status_code == 409 and "сменили" in res.json()["detail"]
    stream = streams_of(council_id)["C"]
    assert (stream.decisions_search.state, stream.questions, stream.outcomes,
            stream.notes_draft) == ("failed", None, None, None)


def test_outcomes_must_be_approved_before_drafting(agents, notes_dir):
    council_id = grouped()
    confirm(council_id)
    decided_c(council_id)
    res = drafts(council_id)
    assert res.status_code == 409 and "утвердите итоги" in res.json()["detail"]


def test_a_stale_draft_or_a_changed_catalog_is_not_written(agents, notes_dir):
    council_id = approved_c()
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


def test_a_hand_edited_note_deleted_after_the_draft_is_not_recreated(agents, notes_dir):
    council_id = approved_c()
    drafts(council_id)
    assert writes(council_id).status_code == 200
    path = notes_dir / "ideas" / "IDEA-0001.md"
    path.write_text(path.read_text(encoding="utf-8") + "Дописали руками.\n", encoding="utf-8")
    drafts(council_id)
    actions = {n.id: n.action for n in streams_of(council_id)["C"].notes_draft.notes}
    assert actions["IDEA-0001"] == "edited"                       # черновик обещал не трогать
    path.unlink()                                                  # а файл удалили
    res = writes(council_id)
    assert res.status_code == 409 and "поменялся" in res.json()["detail"]
    assert not path.exists()


def test_a_draft_in_the_previous_notes_language_is_not_written(agents, notes_dir, monkeypatch):
    council_id = approved_c()
    drafts(council_id)                                             # по-русски
    monkeypatch.setattr(documents, "notes_language", lambda: "English")   # язык сменили
    res = writes(council_id)
    assert res.status_code == 409 and "English" in res.json()["detail"]
    assert not notes_dir.exists()


def test_a_vanished_note_edited_after_the_draft_is_not_deleted(agents, notes_dir):
    council_id = approved_c()
    drafts(council_id)
    assert writes(council_id).status_code == 200
    # Прежняя выгрузка потока знала и вопрос, которого в потоке больше нет.
    old = Note("OQ-0099", "open_question", "Старый вопрос?", ("IDEA-0001",))
    path = path_of(notes_dir, old)
    path.write_text(rendered(old), encoding="utf-8")
    gone = ExportedNote(key="q:старый", id=old.id, type=old.type, generated=old.body,
                        written=old.body, links=list(old.links),
                        digest=hashlib.sha256(path.read_bytes()).hexdigest())
    store = get_store()
    streams = [s.model_copy(update={"notes": s.notes.model_copy(
                   update={"notes": [*s.notes.notes, gone]})}) if s.group == "C" else s
               for s in store.get_council(council_id).streams]
    store.update_council(council_id, {"streams": streams})
    drafts(council_id)
    assert [v.id for v in streams_of(council_id)["C"].notes_draft.vanished] == ["OQ-0099"]
    edited = Note(old.id, old.type, "Старый вопрос? Дописали после черновика.", old.links)
    path.write_text(rendered(edited), encoding="utf-8")
    res = writes(council_id, delete=["OQ-0099"])
    assert res.status_code == 409 and "поменялся" in res.json()["detail"]
    assert path.read_text(encoding="utf-8") == rendered(edited)       # не удалили не глядя


def test_numbers_of_another_streams_export_are_not_given_again(agents, notes_dir):
    first = approved_c()
    drafts(first)
    assert writes(first).status_code == 200
    for path in list(notes_dir.rglob("*.md")):                       # заметки удалили руками
        path.unlink()
    second = approved_c()
    drafts(second)
    draft = streams_of(second)["C"].notes_draft
    # Номера первой выгрузки всё ещё её: вторая берёт следующие.
    assert draft.notes[0].id == "IDEA-0002"


def test_a_draft_is_not_written_into_another_folder(agents, notes_dir, tmp_path):
    council_id = approved_c()
    drafts(council_id)
    assert streams_of(council_id)["C"].notes_draft.root == str(notes_dir)
    # Папку проекта сменили на другую пустую: номера вышли бы те же, но туда черновик не смотрели.
    other = tmp_path / "other"
    app.dependency_overrides[get_notes_of] = lambda: lambda council: other
    res = writes(council_id)
    assert res.status_code == 409 and "другой папки документации" in res.json()["detail"]
    assert not other.exists()
    assert drafts(council_id).status_code == 202
    assert writes(council_id).status_code == 200
    assert streams_of(council_id)["C"].notes.root == str(other)


def test_an_export_to_another_catalog_is_not_the_previous_one_here(agents, notes_dir, tmp_path):
    council_id = approved_c()
    drafts(council_id)
    assert writes(council_id).status_code == 200
    # Папку документации сменили: в новом каталоге под IDEA-0001 — чужая идея.
    other = tmp_path / "other"
    foreign = Note("IDEA-0001", "idea", "Чужая идея.")
    path = path_of(other, foreign)
    path.parent.mkdir(parents=True)
    path.write_text(rendered(foreign), encoding="utf-8")
    app.dependency_overrides[get_notes_of] = lambda: lambda council: other
    drafts(council_id)
    draft = streams_of(council_id)["C"].notes_draft
    assert (draft.notes[0].id, draft.notes[0].action, draft.vanished) == ("IDEA-0002", "create",
                                                                          [])


def test_a_failed_save_of_the_export_puts_the_notes_back(agents, notes_dir, monkeypatch):
    council_id = approved_c()
    drafts(council_id)

    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(get_store(), "update_council", full)
    with pytest.raises(OSError):
        writes(council_id)
    assert [path for path in notes_dir.rglob("*") if path.is_file()] == []


def test_decisions_wait_for_the_notes_translation(agents, notes_dir):
    council_id = approved_c()
    get_store().update_council(council_id, {"streams": [
        s.model_copy(update={"notes_draft": NotesDraft(state="running", run="n1",
                                                       outcomes=s.outcomes.run)})
        if s.group == "C" else s for s in get_store().get_council(council_id).streams]})
    res = decide(council_id, "C", [("Q1", None, None), ("Q2", None, None)])
    assert res.status_code == 423


def test_a_draft_that_cannot_be_built_says_why(agents, notes_dir):
    council_id = approved_c()
    # Вопрос пересматривает прошлое решение, а его из каталога уже убрали.
    streams = [s.model_copy(update={"scope": [s.scope[0].model_copy(update={
        "revisits": "ADR-0042"}), *s.scope[1:]]}) if s.group == "C" else s
        for s in get_store().get_council(council_id).streams]
    get_store().update_council(council_id, {"streams": streams})
    res = drafts(council_id)
    assert res.status_code == 422 and "пересматривает ADR-0042" in res.json()["detail"]


class Translating(Agents):
    """Судья переводит заметки: каждый текст — с пометкой EN. broken — файл задачи он
    возвращает без перевода. turns — ходы перевода: ключ хода и что в нём переводили."""

    def __init__(self):
        super().__init__()
        self.broken = False
        self.turns = []
        self.forgotten = []

    def ask(self, model, prompt, key, workspace=None):
        if "-notes_translation-" in key:
            self.prompts["notes_translation"] = prompt
            notes = json.loads(prompt.split("## NOTES\n")[1])
            self.turns.append((key, [n["key"] for n in notes]))
            if self.broken and any(n["key"].startswith("i:") for n in notes):
                return json.dumps({"notes": []})
            return json.dumps({"notes": [{"key": n["key"], "text": f"EN {n['text']}"}
                                         for n in notes]})
        return super().ask(model, prompt, key, workspace)

    def forget(self, keys):
        self.forgotten += [key for key in keys if "-notes_translation-" in key]


@pytest.fixture
def translating(agents, monkeypatch):
    fake = Translating()
    before = app.dependency_overrides[get_agents]
    app.dependency_overrides[get_agents] = lambda: fake
    monkeypatch.setattr(documents, "notes_language", lambda: "English")
    yield fake
    app.dependency_overrides[get_agents] = before


def test_notes_in_another_language_are_translated_by_the_judge(notes_dir, translating):
    council_id = approved_c()
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
    council_id = approved_c()
    drafts(council_id)
    draft = streams_of(council_id)["C"].notes_draft
    assert draft.state == "done" and draft.language == "French"
    assert all(n.text.startswith("EN ") for n in draft.notes)
    assert re.search(r"translate the notes .* into French", translating.prompts[
        "notes_translation"])


def test_without_models_a_translated_draft_is_recorded_failed(notes_dir, translating):
    council_id = approved_c()
    translating.online = set()
    drafts(council_id)
    draft = streams_of(council_id)["C"].notes_draft
    assert draft.state == "failed" and draft.error.startswith("Нет подключения")
    assert writes(council_id).status_code == 409


