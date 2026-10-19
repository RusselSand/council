"""Этап «Задачи»: план на весь совет по утверждённым и выгруженным итогам, сброс кнопкой,
выгрузка плана в папку задач."""

import json
import os
import shutil
from dataclasses import replace

import pytest

from spec_council.api import tasks as tasks_api
from spec_council.app import app
from spec_council.deps import get_agents, get_issues_of, get_launcher, get_notes_of
from spec_council.export import Shelf, words_for
from spec_council.groups import arranged
from spec_council.issue_files import rendered as issue_rendered
from spec_council.models import (
    CouncilStatus,
    Issue,
    NotePlan,
    OpenQuestion,
    Outcome,
    RepositoryFinding,
    RepositoryMap,
    RepositoryScan,
    RepositoryStep,
    Research,
    Slicing,
    Stream,
    Structure,
    StructureProposal,
    TaskPlan,
)
from spec_council.models import LabeledFragment as Fragment
from spec_council.notes import Catalog, Note, NotesError, path_of, rendered
from spec_council.pipeline import start_tasks
from spec_council.tasks import (
    Names,
    adr_entry,
    names_of,
    outcome_entry,
    outcome_names,
    research_texts,
)
from spec_council.tasks_export import aligned, drafted_tasks, issue_text
from tests.test_streams import (
    ALL_DECIDED,
    LABELS,
    RESULT,
    TASK,
    TEXTS,
    Agents,
    approves,
    choose,
    chose,
    client,
    confirm,
    decide,
    free_c,
    get_store,
    grouped,
    grp,
    passes,
    repos,  # noqa: F401 — фикстура
    scans,
    section,
    streams_of,
    takes,
)


@pytest.fixture(name="agents")
def models():
    fake = Agents()
    app.dependency_overrides[get_agents] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    yield fake
    app.dependency_overrides.pop(get_agents)
    app.dependency_overrides.pop(get_launcher)


@pytest.fixture
def folders(tmp_path):
    """Папка документации и папка задач проекта совета."""
    notes, issues = tmp_path / "notes", tmp_path / "issues"
    app.dependency_overrides[get_notes_of] = lambda: lambda council: notes
    app.dependency_overrides[get_issues_of] = lambda: lambda council: issues
    yield notes, issues
    app.dependency_overrides.pop(get_notes_of)
    app.dependency_overrides.pop(get_issues_of)


def single():
    """Совет из одной группы C: план задач — на весь совет, и в нём один поток."""
    council_id = client.post("/api/councils").json()["id"]
    slicing = Slicing(state="done", run="s1", steps=[], fragments=[
        Fragment(id=i, text=TEXTS[i], label=label, reason="", council_label=label)
        for i, label in LABELS.items()])
    groups = arranged([grp("C", [1, 2, 3, 4, 5])])
    structure = Structure(state="done", run="g1", slicing_run="s1", labels=LABELS, steps=[],
                          groups=groups, proposal=StructureProposal(groups=groups, relations=[]))
    get_store().update_council(council_id, {"slicing": slicing, "structure": structure,
                                            "status": CouncilStatus.structure})
    assert confirm(council_id).status_code == 200
    return council_id


def exported(council_id, group="C"):
    """Итоги потока утверждены и выгружены в заметки."""
    assert approves(council_id, group).status_code == 200
    body = {"run": "g1", "revision": 0}
    assert client.post(f"/api/councils/{council_id}/streams/{group}/notes/draft",
                       json=body).status_code == 202
    run = streams_of(council_id)[group].notes_draft.run
    assert client.post(f"/api/councils/{council_id}/streams/{group}/notes",
                       json={**body, "draft": run}).status_code == 200


def all_decided(council_id):
    """Поток C уже начат: оба вопроса отобраны и решены."""
    choose(council_id, "C", ["Q1", "Q2"])
    chose(council_id, "C", [("Q1", "P1"), ("Q2", "P2")])
    assert decide(council_id, "C", ALL_DECIDED).status_code == 200


def ready(council_id=None):
    council_id = council_id or single()
    free_c(council_id)
    exported(council_id)
    return council_id


def council(council_id):
    return get_store().get_council(council_id)


def plans(council_id, revision=0):
    return client.post(f"/api/councils/{council_id}/tasks", json={"run": "g1",
                                                                  "revision": revision})


def resets(council_id):
    return client.post(f"/api/councils/{council_id}/tasks/reset", json={"run": "g1",
                                                                        "revision": 0})


def drafts(council_id):
    return client.post(f"/api/councils/{council_id}/tasks/draft", json={"run": "g1",
                                                                        "revision": 0})


def writes(council_id, draft=None, edits=None):
    run = draft or council(council_id).tasks_draft.run
    return client.post(f"/api/councils/{council_id}/tasks/write",
                       json={"run": "g1", "revision": 0, "draft": run, "edits": edits or {}})


def test_the_council_plans_tasks_by_note_numbers_and_writes_them_as_issue_files(agents, folders):
    notes, issues = folders
    council_id = ready()
    res = plans(council_id)
    assert res.status_code == 202 and res.json()["tasks"]["state"] == "running"
    plan = council(council_id).tasks
    assert plan.state == "done", plan.error
    [issue] = plan.issues
    assert (issue.id, issue.title, issue.outcome_id) == ("I1", f"{TASK} OUT-0001", "OUT-0001")
    assert issue.adr_ids == ["ADR-0001", "ADR-0002"]
    assert issue.open_questions == ["Где хранить долю?"]
    assert (plan.uncovered, plan.skipped, plan.code) == ([], [], False)
    stream = streams_of(council_id)["C"]
    assert plan.basis == {"C": f"{stream.outcomes.run}:{stream.notes.run}",
                          "research": "skipped:|skipped:"}
    # Модели видят итоги и решения номерами заметок, а решения — с их текстом.
    prompt = agents.prompts["task_plan"]
    [outcome] = json.loads(section(prompt, "OUTCOMES"))
    assert (outcome["id"], outcome["group"], outcome["title"]) == ("OUT-0001", "C", RESULT)
    decisions = json.loads(section(prompt, "ACCEPTED DECISIONS").split("\n\n")[-1])
    assert [d["id"] for d in decisions] == ["ADR-0001", "ADR-0002"]
    assert all(d["decision"] for d in decisions)
    assert "C. Группа C:" in section(prompt, "IDEAS")
    assert plans(council_id).status_code == 409                       # план уже есть

    assert drafts(council_id).status_code == 202
    draft = council(council_id).tasks_draft
    assert draft.state == "done"
    [file] = draft.notes
    assert (file.id, file.type, file.action) == ("ISS-0001", "issue", "create")
    assert file.links == ["OUT-0001", "ADR-0001", "ADR-0002"]
    assert "Где хранить долю?" in file.text and "ISS-0001" in file.text
    assert not issues.exists()                                        # черновик файлов не пишет

    assert writes(council_id).status_code == 200
    record = council(council_id).tasks_export
    assert [n.id for n in record.notes] == ["ISS-0001"] and record.plan == plan.run
    [written] = [p for p in issues.rglob("*.md")]
    assert "ISS-0001" in written.read_text(encoding="utf-8")
    # Заметки итогов задач не перечисляют: связь односторонняя.
    assert "ISS-" not in Catalog.load(notes).notes["OUT-0001"].body


def test_the_plan_waits_for_every_stream_to_be_approved_and_exported(agents, folders):
    council_id = grouped()
    confirm(council_id)
    ready(council_id)
    res = plans(council_id)
    assert res.status_code == 409
    assert "Поток A: итоги не утверждены" in res.json()["detail"]
    assert "Поток C" not in res.json()["detail"]
    assert council(council_id).tasks is None


def test_a_stream_exported_before_note_numbers_were_kept_is_exported_again_first(agents,
                                                                                 folders):
    council_id = ready()
    store = get_store()
    # Не помнил номеров вовсе — или помнил только у решений и итогов: тексты задач назвали бы
    # вопросы и варианты не номерами заметок.
    for refs in ({}, {"O1": "OUT-0001", "ADR-1": "ADR-0001"}):
        store.update_council(council_id, {"streams": [
            s.model_copy(update={"notes": s.notes.model_copy(update={"refs": refs})})
            for s in council(council_id).streams]})
        res = plans(council_id)
        assert res.status_code == 409 and "выгрузите его заново" in res.json()["detail"]


def test_approved_outcomes_not_yet_exported_are_not_planned(agents, folders):
    council_id = single()
    free_c(council_id)
    approves(council_id, "C")
    res = plans(council_id)
    assert res.status_code == 409 and "не выгружен" in res.json()["detail"]


def test_a_changed_stream_leaves_the_plan_to_the_human_who_resets_it(agents, folders):
    council_id = ready()
    plans(council_id)
    first = council(council_id).tasks
    decide(council_id, "C", [ALL_DECIDED[0], ("Q2", "P2", "Иначе.")])
    stream = streams_of(council_id)["C"]
    assert not stream.outcomes.approved
    # План не трогается: видно, что он к другим итогам, — сбрасывает человек.
    assert council(council_id).tasks == first
    assert first.basis["C"] != f"{stream.outcomes.run}:{stream.notes.run}"
    assert resets(council_id).status_code == 200
    assert (council(council_id).tasks, council(council_id).tasks_draft) == (None, None)
    assert plans(council_id).status_code == 409                       # итоги не утверждены
    exported(council_id)
    assert plans(council_id).status_code == 202


def test_research_passed_again_after_the_plan_makes_it_stale(agents, folders):
    """План читал карту кода и описание макета исследования: прошли его заново — план к прежнему,
    и его не выгрузить, пока не сбросят."""
    council_id = ready()
    plans(council_id)
    body = {"run": "g1", "revision": 0}
    assert client.post(f"/api/councils/{council_id}/research/reset", json=body).status_code == 200
    res = drafts(council_id)
    assert res.status_code == 409 and "План устарел" in res.json()["detail"]
    assert council(council_id).tasks is not None                       # сам план не сброшен


def test_a_running_plan_is_not_reset_or_started_twice(agents, folders):
    council_id = ready()
    get_store().update_council(council_id, {"tasks": start_tasks(["sol"], "sol", {})})
    assert resets(council_id).status_code == 423
    res = plans(council_id)
    assert res.status_code == 409 and "строится" in res.json()["detail"]


def test_without_models_the_plan_is_recorded_failed_and_can_be_run_again(agents, folders):
    council_id = ready()
    agents.online = set()
    assert plans(council_id).status_code == 202
    plan = council(council_id).tasks
    assert plan.state == "failed" and plan.error.startswith("Нет подключения")
    agents.online = {"sol", "fable"}
    assert plans(council_id).status_code == 202
    assert council(council_id).tasks.state == "done"


def test_a_plan_is_exported_only_into_an_issues_folder(agents, folders):
    council_id = ready()
    assert drafts(council_id).status_code == 409                      # плана ещё нет
    plans(council_id)
    app.dependency_overrides[get_issues_of] = lambda: lambda council: None
    res = drafts(council_id)
    assert res.status_code == 422 and "папки задач" in res.json()["detail"]


def test_a_draft_of_another_plan_is_not_written(agents, folders):
    council_id = ready()
    plans(council_id)
    drafts(council_id)
    stale = council(council_id).tasks_draft.run
    resets(council_id)
    plans(council_id)
    res = writes(council_id, draft=stale)
    assert res.status_code == 409
    assert not folders[1].exists()


def test_writing_again_keeps_the_numbers_and_human_edits(agents, folders):
    council_id = ready()
    plans(council_id)
    drafts(council_id)
    [file] = council(council_id).tasks_draft.notes
    own = "# Своя задача" + file.text[file.text.index("\n"):]       # номера — на месте
    res = writes(council_id, edits={file.key: own})
    assert res.status_code == 200, res.text
    resets(council_id)
    plans(council_id)
    drafts(council_id)
    [again] = council(council_id).tasks_draft.notes
    assert again.id == "ISS-0001" and again.text.startswith("# Своя задача")


def test_a_number_mentioned_in_a_note_stays_with_its_task(agents, folders):
    """Заметка проекта ссылается на выгруженную задачу: номер всё ещё этой задачи."""
    notes, _ = folders
    council_id = ready()
    plans(council_id)
    drafts(council_id)
    writes(council_id)
    mention = Note("IDEA-0099", "idea", "Сделано в ISS-0001.", ())
    path = path_of(notes, mention)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered(mention), encoding="utf-8")
    resets(council_id)
    plans(council_id)
    drafts(council_id)
    assert [n.id for n in council(council_id).tasks_draft.notes] == ["ISS-0001"]


def test_a_note_the_plan_stands_on_deleted_since_is_not_drafted(agents, folders):
    notes, _ = folders
    council_id = ready()
    plans(council_id)
    (notes / "outcomes" / "OUT-0001.md").unlink()
    res = drafts(council_id)
    assert res.status_code == 422 and "OUT-0001" in res.json()["detail"]


def test_a_vanished_task_another_file_still_waits_for_is_not_deleted(agents, folders):
    _, issues = folders
    council_id = ready()
    plans(council_id)
    drafts(council_id)
    writes(council_id)
    # Свою задачу человек положил руками: она ждёт ISS-0001.
    own = Note("ISS-0005", "issue", "# Своя", ("ISS-0001",))
    (issues / "ISS-0005.md").write_text(issue_rendered(own), encoding="utf-8")
    resets(council_id)
    renamed = Agents.task_plan

    def other(prompt):
        found = renamed(prompt)
        for issue in found["issues"]:
            issue["title"], issue["user_story"] = "Другая задача", "As a team, I want other."
        return found

    agents.task_plan = other
    plans(council_id)
    drafts(council_id)
    [gone] = council(council_id).tasks_draft.vanished
    assert (gone.id, gone.linked_from) == ("ISS-0001", ["ISS-0005"])
    res = client.post(
        f"/api/councils/{council_id}/tasks/write",
        json={"run": "g1", "revision": 0, "draft": council(council_id).tasks_draft.run,
              "edits": {}, "delete": ["ISS-0001"]})
    assert res.status_code == 422 and "ISS-0005" in res.json()["detail"]
    assert (issues / "ISS-0001.md").exists()


def test_a_plan_whose_notes_folder_changed_is_not_exported(agents, folders, tmp_path):
    """Папку документации сменили после плана: номера OUT/ADR в плане — из прежнего каталога, и
    файлы задач ссылались бы мимо."""
    council_id = ready()
    plans(council_id)
    app.dependency_overrides[get_notes_of] = lambda: lambda council: tmp_path / "other"
    res = drafts(council_id)
    assert res.status_code == 409 and "План устарел" in res.json()["detail"]
    assert council(council_id).tasks_draft is None


def test_a_plan_whose_stream_was_exported_again_is_not_exported(agents, folders):
    council_id = ready()
    plans(council_id)
    drafts(council_id)
    run = council(council_id).tasks_draft.run
    exported(council_id)                                  # поток выгрузили заново после плана
    assert drafts(council_id).status_code == 409
    res = writes(council_id, draft=run)
    assert res.status_code == 409 and "План устарел" in res.json()["detail"]
    assert not folders[1].exists()


def test_research_changed_while_the_code_was_read_refuses_the_plan(agents, folders, repos,  # noqa: F811
                                                                    monkeypatch):
    council_id = single()
    scans(council_id, "C")
    takes(council_id, "C")
    passes(council_id, "C")
    all_decided(council_id)
    exported(council_id)
    reading = tasks_api.code_of

    def meanwhile(*args):
        found = reading(*args)
        assert client.post(f"/api/councils/{council_id}/research/reset",
                           json={"run": "g1", "revision": 0}).status_code == 200
        return found

    monkeypatch.setattr(tasks_api, "code_of", meanwhile)
    res = plans(council_id)
    assert res.status_code == 409 and "Исследование поменялось" in res.json()["detail"]
    assert council(council_id).tasks is None


def test_with_an_approved_scan_the_plan_reads_the_code_anew(agents, folders, repos):  # noqa: F811
    council_id = single()
    scans(council_id, "C")
    takes(council_id, "C")
    passes(council_id, "C")
    (repos / "later.py").write_text("x = 1\n", encoding="utf-8")       # код после скана
    all_decided(council_id)
    exported(council_id)
    assert plans(council_id).status_code == 202
    plan = council(council_id).tasks
    assert plan.state == "done" and plan.code
    assert [(s.name, s.path, s.dirty) for s in plan.sources] == [("", "project", True)]
    assert agents.seen == ["app.py", "later.py"]                      # снимок — нынешний
    place = agents.workspaces["task_plan"]
    assert place is not None and not place.exists()
    assert "Ответы ищут в app.py" in section(agents.prompts["task_plan"], "REPOSITORY CONTEXT")


def test_a_working_copy_gone_since_the_scan_refuses_the_plan(agents, folders, repos):  # noqa: F811
    council_id = single()
    scans(council_id, "C")
    takes(council_id, "C")
    passes(council_id, "C")
    all_decided(council_id)
    exported(council_id)
    shutil.rmtree(repos, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
    res = plans(council_id)
    assert res.status_code == 422 and "не прочитать" in res.json()["detail"]
    assert council(council_id).tasks is None


def test_an_issue_file_names_other_issues_by_their_project_numbers():
    issue = Issue(id="I2", title="Выдача после I1", user_story="As a team, I want answers.",
                  outcome_id="OUT-0001", scope=["Ждать I1, не трогая I10."],
                  open_questions=["Готова ли I1?"])
    text = issue_text(issue, "ISS-0008", ("OUT-0001", "Итог"), [], [("ISS-0007", "Индекс")], [],
                      [], words_for("Russian"), {"I1": "ISS-0007", "I2": "ISS-0008"})
    assert text.startswith("# Выдача после ISS-0007")
    assert "- Ждать ISS-0007, не трогая I10." in text
    assert "- Готова ли ISS-0007?" in text


def test_stream_numbers_in_issue_files_and_plan_inputs_become_note_numbers():
    names = Names({"Q1": "OQ-0001", "P2": "PRO-0002", "ADR-1": "ADR-0001"},
                  {"F4": "Секреты не уходят в репозиторий."})
    issue = Issue(id="I2", title="Выдача по Q1", user_story="As a team, I want answers.",
                  outcome_id="OUT-0001", scope=["Учесть F4 и `Q1` (F4).", "Как `I2`, но I2."],
                  open_questions=["Хватит ли P2?"])
    # Итог и решения — как в каталоге: номера потока в них ушли при выгрузке, а прошлое решение
    # проекта и правку человека пересчитывать нельзя.
    text = issue_text(issue, "ISS-0008", ("OUT-0001", "Итог по Q1"),
                      [("ADR-0007", "Прошлое решение по Q1")], [], [], [], words_for("Russian"),
                      {"I2": "ISS-0008"}, names)
    assert text.startswith("# Выдача по OQ-0001")
    assert "- Учесть «Секреты не уходят в репозиторий» и `Q1`." in text    # код — как есть
    assert "- Как `I2`, но ISS-0008." in text                    # и номер задачи в коде — тоже
    assert "- OUT-0001: Итог по Q1" in text
    assert "- ADR-0007: Прошлое решение по Q1" in text
    assert "- Хватит ли PRO-0002?" in text
    # Что модели прочтут, то и перепишут в задачи: им — тоже номера заметок.
    outcome = Outcome(id="O1", title="Итог по Q1", behavior="По Q1 (F4).", adr_ids=["ADR-1"],
                      adr_notes={"ADR-1": "Следует из P2"}, acceptance_criteria=["Q1 решён"])
    entry = outcome_entry(outcome, "OUT-0001", "C", {"ADR-1": "ADR-0001"}, names)
    assert (entry["title"], entry["behavior"], entry["acceptance_criteria"], entry["follows"]) == (
        "Итог по OQ-0001", "По OQ-0001.", ["OQ-0001 решён"], {"ADR-0001": "Следует из PRO-0002"})
    # Сочетание из исходных текстов (бакет Cloudflare R2) — их слово, а R2 в другом месте —
    # находка R2.
    termed = Names({"Q1": "OQ-0001"}, {"R2": "Файлы лежат в бакете."},
                   phrases=frozenset({"Cloudflare R2"}))
    assert termed("Хранить в Cloudflare R2 по R2, как в Q1") == (
        "Хранить в Cloudflare R2 по «Файлы лежат в бакете», как в OQ-0001")


class Translating(Agents):
    """Судья переводит файлы задач, каждый своим ходом, — и название задачи всякий раз
    по-своему: «Индекс» — «Index 1», «Index 2»…"""

    def __init__(self):
        super().__init__()
        self.turn = 0

    def ask(self, model, prompt, key, workspace=None):
        if "-notes_translation-" in key:
            self.turn += 1
            notes = json.loads(prompt.split("## NOTES\n")[1])
            return json.dumps({"notes": [
                {"key": n["key"], "text": n["text"].replace("Индекс", f"Index {self.turn}")}
                for n in notes]})
        return super().ask(model, prompt, key, workspace)


def two_tasks(prompt):
    """План: на итог две задачи, вторая — после первой."""
    [issue] = Agents.task_plan(prompt)["issues"]
    return {"issues": [issue | {"id": "I1", "title": "Индекс"},
                       issue | {"id": "I2", "title": "Выдача", "depends_on": ["I1"]}]}


def test_a_task_is_named_alike_in_every_file_after_translation_and_edits(agents, folders,
                                                                        monkeypatch):
    _, issues = folders
    fake = Translating()
    fake.task_plan = two_tasks
    app.dependency_overrides[get_agents] = lambda: fake
    council_id = ready()
    plans(council_id)
    monkeypatch.setattr(tasks_api, "notes_language", lambda: "English")
    drafts(council_id)
    draft = council(council_id).tasks_draft
    assert draft.state == "done", draft.error
    first, second = draft.notes
    # Второй файл переводили своим ходом («Index 2»), а задачу в нём зовут, как в её файле.
    assert first.text.startswith("# Index 1\n")
    assert "- ISS-0001: Index 1" in second.text and "Index 2" not in second.text

    # Человек переименовал задачу в её файле — так её зовут и в файле, что её ждёт.
    renamed = "# Index, renamed" + first.text[first.text.index("\n"):]
    assert writes(council_id, edits={first.key: renamed}).status_code == 200
    assert "- ISS-0001: Index, renamed" in (issues / "ISS-0002.md").read_text(encoding="utf-8")
    drafts(council_id)                                       # переводить нечего — всё на месте
    assert {n.action for n in council(council_id).tasks_draft.notes} == {"same"}


def test_task_names_come_from_the_streams_own_group_and_the_approved_research(agents, folders):
    council_id = ready()
    fragments = {f.id: f for f in council(council_id).slicing.fragments}
    # «P1» — термин в тексте другой группы: в потоке C P1 — его вариант.
    other = Fragment(id=99, text="Метрика P1 у соседней команды.", label="constraint",
                     reason="", council_label="constraint")
    [names] = outcome_names(council(council_id), fragments | {99: other}).values()
    assert names("по P1") == f"по {names.numbers['P1']}"

    # Находки скана, которым шаг «Репозиторий» не прошли, план не читал.
    scan = RepositoryScan(state="done", run="s1", steps=[], result=RepositoryMap(findings=[
        RepositoryFinding(id="R1", statement="Ответы ищут полнотекстом.", status="verified")]))
    skipped = Research(scan=scan, repository=RepositoryStep(by="skipped"))
    assert research_texts(council(council_id).model_copy(update={"research": skipped})) == {}
    approved = Research(scan=scan, repository=RepositoryStep(by="scan", scan_run="s1"))
    assert research_texts(council(council_id).model_copy(update={"research": approved})) == {
        "R1": "Ответы ищут полнотекстом."}


def test_a_dependency_is_retitled_in_its_list_not_in_another_bullet():
    def file(number, generated, text=None, links=()):
        return NotePlan(key=f"i:{number}", id=number, type="issue", text=text or generated,
                        generated=generated, links=list(links), action="create")

    first = file("ISS-0001", "# Индекс\n\nКак команда.", "# Index v1\n\nAs a team.")
    # Ниже списка зависимостей дописали раздел, где тоже «- ISS-0001: …», — он не список.
    second = file("ISS-0002", "# Поиск\n\n## Что сделать\n- Искать\n\n## После задач\n"
                              "- ISS-0001: Индекс\n\nКоммит ISS-0002.",
                  "# Search\n\n## To do\n- Search\n\n## After the issues\n- ISS-0001: Index v2\n\n"
                  "## Notes\n- ISS-0001: reuse its tokenizer\n\nCommit ISS-0002.",
                  ["OUT-0001", "ISS-0001"])
    assert aligned([first, second]) == {second.key: second.text.replace(
        "- ISS-0001: Index v2", "- ISS-0001: Index v1")}


def test_a_finding_of_the_approved_research_is_a_number_not_an_old_term():
    # В копии скана потока «R2» было словом (бакет Cloudflare R2), а в нынешнем исследовании R2 —
    # находка: в задачах это её номер.
    bucket = Fragment(id=1, text="Файлы лежат в Cloudflare R2.", label="constraint", reason="",
                      council_label="constraint")
    names = names_of(Stream(group="C"), {1: bucket}, {"R2": "Ответы ищут полнотекстом."})
    assert names("см. R2") == "см. «Ответы ищут полнотекстом»"


def test_task_files_keep_stream_terms_and_skip_deleted_notes(tmp_path):
    catalog = Catalog({"OUT-0001": Note("OUT-0001", "outcome", "Кэш ответов")})
    # «I1 cache» — сочетание из исходных текстов потока: номером задачи плана оно не становится,
    # а ссылка на задачу I1 — становится. Q1 ведёт на OQ-0001, которой в каталоге уже нет, —
    # встаёт сам вопрос.
    bucket = Fragment(id=1, text="Прогрев I1 cache ускоряет ответы.", label="constraint",
                      reason="", council_label="constraint")
    names = names_of(Stream(group="C"), {1: bucket})
    assert {"I1 cache", "Прогрев I1"} <= names.phrases
    names = replace(names, numbers={"Q1": "OQ-0001", "O1": "OUT-0001"},
                    texts={"Q1": "Где хранить кэш?"})
    issue = Issue(id="I1", title="Прогреть I1 cache", user_story="As a team, I want answers.",
                  outcome_id="OUT-0001", scope=["Ответить на Q1.", "Сверить с I1."])
    plan = TaskPlan(state="done", run="t1", steps=[], issues=[issue])
    [file], _, _ = drafted_tasks(plan, {}, Shelf(catalog, tmp_path, tmp_path / "issues"), None,
                                 words_for("Russian"), "Russian", (), {"OUT-0001": names})
    assert file.text.startswith("# Прогреть I1 cache\n")
    assert "- Ответить на «Где хранить кэш?»." in file.text
    assert "- Сверить с ISS-0001." in file.text


def test_a_dependency_list_is_found_after_its_sections_were_edited():
    def file(number, generated, text=None, links=()):
        return NotePlan(key=f"i:{number}", id=number, type="issue", text=text or generated,
                        generated=generated, links=list(links), action="create")

    first = file("ISS-0001", "# Индекс\n\nКак команда.", "# Index v1\n\nAs a team.")
    # Раздел «Решения» перед списком убрали: список — уже второй раздел, а не третий.
    second = file("ISS-0002", "# Поиск\n\n## Что сделать\n- Искать\n\n"
                              "## Решения\n- ADR-0001: Да\n\n"
                              "## После задач\n- ISS-0001: Индекс\n\nКоммит ISS-0002.",
                  "# Search\n\n## To do\n- Search\n\n## After the issues\n- ISS-0001: Index v2\n\n"
                  "Commit ISS-0002.", ["OUT-0001", "ADR-0001", "ISS-0001"])
    assert aligned([first, second]) == {second.key: second.text.replace(
        "- ISS-0001: Index v2", "- ISS-0001: Index v1")}


def test_a_title_with_note_numbers_does_not_spread_to_other_files():
    # Название задачи поправили руками, и в нём номер заметки: в чужой файл он попал бы без
    # ссылки во frontmatter — такой файл остаётся как был.
    first = NotePlan(key="i:1", id="ISS-0001", type="issue", text="# Индекс",
                     generated="# Индекс", action="edited", current="# Индекс по ADR-9999")
    second = NotePlan(key="i:2", id="ISS-0002", type="issue",
                      text="# Поиск\n\n## После задач\n- ISS-0001: Индекс\n\nКоммит.",
                      generated="# Поиск\n\n## После задач\n- ISS-0001: Индекс\n\nКоммит.",
                      links=["OUT-0001", "ISS-0001"], action="create")
    assert aligned([first, second]) == {}


def test_a_task_title_is_only_its_first_line():
    # Файл правили руками: первая строка уже не заголовок — названия нет, ниже «# …» — не оно.
    first = NotePlan(key="i:1", id="ISS-0001", type="issue", text="# Индекс",
                     generated="# Индекс", action="edited",
                     current="Заметки о задаче.\n\n# Совсем другое")
    second = NotePlan(key="i:2", id="ISS-0002", type="issue",
                      text="# Поиск\n\n## После задач\n- ISS-0001: Индекс\n\nКоммит.",
                      generated="# Поиск\n\n## После задач\n- ISS-0001: Индекс\n\nКоммит.",
                      links=["OUT-0001", "ISS-0001"], action="create")
    assert aligned([first, second]) == {}


def test_a_note_number_the_plan_wrote_must_still_be_in_the_catalog(tmp_path):
    catalog = Catalog({"OUT-0001": Note("OUT-0001", "outcome", "Кэш ответов")})
    issue = Issue(id="I1", title="Кэш", user_story="As a team, I want answers.",
                  outcome_id="OUT-0001", scope=["Ответить на OQ-0009 и OUT-1."])
    plan = TaskPlan(state="done", run="t1", steps=[], issues=[issue])
    with pytest.raises(NotesError, match="больше нет OQ-0009, а задачи плана их называют"):
        drafted_tasks(plan, {}, Shelf(catalog, tmp_path, tmp_path / "issues"), None,
                      words_for("Russian"), "Russian")


def test_the_planner_sees_decisions_and_questions_as_they_were_written():
    # Человек поправил решение при выгрузке: «Q1 reporting» в нём — его слово, а не вопрос Q1.
    stream = Stream(group="C", scope=[OpenQuestion(id="Q1", text="Как считать?",
                                                   source="discovered")])
    written = {"ADR-0001": "Считать по Q1 reporting", "OQ-0001": "Как считать долю?"}
    entry = adr_entry(stream, "ADR-1", "ADR-0001", written, Names({"Q1": "OQ-0001"}, {}))
    assert (entry["question"], entry["decision"]) == ("Как считать долю?",
                                                      "Считать по Q1 reporting")


def test_note_numbers_in_task_code_and_links_are_not_references(tmp_path):
    catalog = Catalog({"OUT-0001": Note("OUT-0001", "outcome", "Кэш ответов")})
    issue = Issue(id="I1", title="Кэш", user_story="As a team, I want answers.",
                  outcome_id="OUT-0001",
                  scope=["Назвать фикстуру `ADR-9999`, как в [примере](/examples/ADR-9999)."])
    plan = TaskPlan(state="done", run="t1", steps=[], issues=[issue])
    [file], _, _ = drafted_tasks(plan, {}, Shelf(catalog, tmp_path, tmp_path / "issues"), None,
                                 words_for("Russian"), "Russian")
    assert "`ADR-9999`" in file.text


def test_a_section_with_more_than_dependencies_is_not_their_list():
    first = NotePlan(key="i:1", id="ISS-0001", type="issue", text="# Index v1",
                     generated="# Индекс", action="create")
    # Списка зависимостей нет, а в «Notes» рядом с пунктом — проза: это не список.
    second = NotePlan(key="i:2", id="ISS-0002", type="issue",
                      text="# Search\n\n## Notes\n- ISS-0001: reuse it\nKeep the old index.\n\n"
                           "Commit ISS-0002.",
                      generated="# Поиск\n\n## После задач\n- ISS-0001: Индекс\n\nКоммит ISS-0002.",
                      links=["OUT-0001", "ISS-0001"], action="create")
    assert aligned([first, second]) == {}


def test_only_the_commit_line_of_the_draft_may_follow_a_dependency_list():
    def file(number, text, links=()):
        return NotePlan(key=f"i:{number}", id=number, type="issue", text=text,
                        generated="# Задача\n\n## После задач\n- ISS-0001: Индекс\n\nКоммит.",
                        links=list(links), action="create")

    # Строка о коммите у файлов одна и та же; «Notes for ISS-0002» — не она, и раздел с ней —
    # не список зависимостей.
    first = file("ISS-0001", "# Index v1\n\nAs a team.\n\nCommit ISS-0001.")
    third = file("ISS-0003", "# Other\n\nAs a team.\n\nCommit ISS-0003.")
    second = file("ISS-0002", "# Search\n\n## Notes\n- ISS-0001: reuse it\n\nNotes for ISS-0002",
                  ["OUT-0001", "ISS-0001"])
    assert aligned([first, second, third]) == {}


def test_a_note_number_that_is_a_stream_term_is_not_a_dead_reference(tmp_path):
    catalog = Catalog({"OUT-0001": Note("OUT-0001", "outcome", "Кэш ответов")})
    source = Fragment(id=1, text="Прогонять на ADR-9999 fixture.", label="constraint",
                      reason="", council_label="constraint")
    names = names_of(Stream(group="C"), {1: source})
    issue = Issue(id="I1", title="Кэш", user_story="As a team, I want answers.",
                  outcome_id="OUT-0001", scope=["Прогнать на ADR-9999 fixture."])
    plan = TaskPlan(state="done", run="t1", steps=[], issues=[issue])
    [file], _, _ = drafted_tasks(plan, {}, Shelf(catalog, tmp_path, tmp_path / "issues"), None,
                                 words_for("Russian"), "Russian", (), {"OUT-0001": names})
    assert "- Прогнать на ADR-9999 fixture." in file.text


def test_dependencies_with_titles_are_aligned_even_if_another_has_none():
    # У ISS-0001 файл правили руками и названия в первой строке нет — его строка как есть, а
    # ISS-0002 в том же списке получает своё нынешнее название.
    first = NotePlan(key="i:1", id="ISS-0001", type="issue", text="# Индекс", generated="# Индекс",
                     action="edited", current="Заметки.\n\n# Другое")
    second = NotePlan(key="i:2", id="ISS-0002", type="issue", text="# Cache v2",
                      generated="# Кэш", action="create")
    third = NotePlan(key="i:3", id="ISS-0003", type="issue",
                     text="# Search\n\n## After\n- ISS-0001: Index\n- ISS-0002: Cache\n",
                     generated="# Поиск\n\n## После задач\n- ISS-0001: Индекс\n- ISS-0002: Кэш\n",
                     links=["OUT-0001", "ISS-0001", "ISS-0002"], action="create")
    assert aligned([first, second, third]) == {
        third.key: third.text.replace("- ISS-0002: Cache", "- ISS-0002: Cache v2")}


def test_a_source_word_in_code_is_not_a_term():
    source = Fragment(id=1, text="Назвать фикстуру `Q1`, а F1 score считать.", label="constraint",
                      reason="", council_label="constraint")
    names = names_of(Stream(group="C"), {1: source})
    assert "F1 score" in names.phrases
    assert not any("Q1" in phrase for phrase in names.phrases)


def test_a_section_naming_only_some_prerequisites_is_not_their_list():
    def file(number, text, links=()):
        return NotePlan(key=f"i:{number}", id=number, type="issue", text=text,
                        generated="# Задача\n\n## После задач\n- ISS-0001: Индекс\n\nКоммит.",
                        links=list(links), action="create")

    first = file("ISS-0001", "# Index v2\n\nAs a team.\n\nCommit ISS-0001.")
    second = file("ISS-0002", "# Cache\n\nAs a team.\n\nCommit ISS-0002.")
    # ISS-0003 ждёт обеих, а список зависимостей убрали: «Notes» с пунктом об одной — не он.
    third = file("ISS-0003", "# Search\n\n## Notes\n- ISS-0001: reuse its tokenizer\n\n"
                             "Commit ISS-0003.", ["OUT-0001", "ISS-0001", "ISS-0002"])
    assert aligned([first, second, third]) == {}


def test_a_task_title_drops_its_closing_hashes():
    # «  #<таб>Index #» — тот же заголовок «Index»: отступ, табуляция после «#» и закрывающие
    # «#» в название не входят.
    first = NotePlan(key="i:1", id="ISS-0001", type="issue", text="  #\tIndex #",
                     generated="# Индекс", action="create")
    second = NotePlan(key="i:2", id="ISS-0002", type="issue",
                      text="# Search\n\n## After\n- ISS-0001: Индекс\n",
                      generated="# Поиск\n\n## После задач\n- ISS-0001: Индекс\n",
                      links=["OUT-0001", "ISS-0001"], action="create")
    assert aligned([first, second]) == {
        second.key: "# Search\n\n## After\n- ISS-0001: Index\n"}


def test_a_hyphenated_word_is_not_a_dead_note_reference(tmp_path):
    catalog = Catalog({"OUT-0001": Note("OUT-0001", "outcome", "Кэш ответов")})
    issue = Issue(id="I1", title="Кэш", user_story="As a team, I want answers.",
                  outcome_id="OUT-0001", scope=["Следовать RFC-ADR-9999."])
    plan = TaskPlan(state="done", run="t1", steps=[], issues=[issue])
    [file], _, _ = drafted_tasks(plan, {}, Shelf(catalog, tmp_path, tmp_path / "issues"), None,
                                 words_for("Russian"), "Russian")
    assert "RFC-ADR-9999" in file.text
