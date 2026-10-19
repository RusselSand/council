"""Этап «Задачи»: план на весь совет по утверждённым и выгруженным итогам, сброс кнопкой,
выгрузка плана в папку задач."""

import json
import os
import shutil

import pytest

from spec_council.api import tasks as tasks_api
from spec_council.app import app
from spec_council.deps import get_agents, get_issues_of, get_launcher, get_notes_of
from spec_council.export import words_for
from spec_council.groups import arranged
from spec_council.issue_files import rendered as issue_rendered
from spec_council.models import (
    CouncilStatus,
    Issue,
    Outcome,
    RepositoryFinding,
    RepositoryMap,
    RepositoryScan,
    RepositoryStep,
    Research,
    Slicing,
    Structure,
    StructureProposal,
)
from spec_council.models import LabeledFragment as Fragment
from spec_council.notes import Catalog, Note, path_of, rendered
from spec_council.pipeline import start_tasks
from spec_council.tasks import Names, outcome_entry, outcome_names, research_texts
from spec_council.tasks_export import issue_text
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
                  outcome_id="OUT-0001", scope=["Учесть F4 и `Q1` (F4)."],
                  open_questions=["Хватит ли P2?"])
    text = issue_text(issue, "ISS-0008", ("OUT-0001", "Итог по ADR-1"),
                      [("ADR-0001", "Решение (F4)")], [], [], [], words_for("Russian"),
                      {"I2": "ISS-0008"}, names)
    assert text.startswith("# Выдача по OQ-0001")
    assert "- Учесть «Секреты не уходят в репозиторий» и `Q1`." in text    # код — как есть
    assert "- OUT-0001: Итог по ADR-0001" in text
    assert "- ADR-0001: Решение\n" in text
    assert "- Хватит ли PRO-0002?" in text
    # Что модели прочтут, то и перепишут в задачи: им — тоже номера заметок.
    outcome = Outcome(id="O1", title="Итог по Q1", behavior="По Q1 (F4).", adr_ids=["ADR-1"],
                      adr_notes={"ADR-1": "Следует из P2"}, acceptance_criteria=["Q1 решён"])
    entry = outcome_entry(outcome, "OUT-0001", "C", {"ADR-1": "ADR-0001"}, names)
    assert (entry["title"], entry["behavior"], entry["acceptance_criteria"], entry["follows"]) == (
        "Итог по OQ-0001", "По OQ-0001.", ["OQ-0001 решён"], {"ADR-0001": "Следует из PRO-0002"})
    # Слово из исходных текстов, похожее на номер (находка про бакет Cloudflare R2), — термин.
    termed = Names({"Q1": "OQ-0001"}, {"R2": "Файлы лежат в Cloudflare R2."},
                   frozenset({"R2"}))
    assert termed("Хранить в R2 (R2), как в Q1") == "Хранить в R2 (R2), как в OQ-0001"


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
