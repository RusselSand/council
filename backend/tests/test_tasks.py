"""Этап «Задачи»: план на весь совет по утверждённым и выгруженным итогам, сброс кнопкой,
выгрузка плана в папку задач."""

import json
import os
import shutil

import pytest

from spec_council.app import app
from spec_council.deps import get_agents, get_issues_of, get_launcher, get_notes_of
from spec_council.groups import arranged
from spec_council.models import CouncilStatus, Slicing, Structure, StructureProposal
from spec_council.models import LabeledFragment as Fragment
from spec_council.notes import Catalog
from spec_council.pipeline import start_tasks
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
    assert plan.basis == {"C": f"{stream.outcomes.run}:{stream.notes.run}"}
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
