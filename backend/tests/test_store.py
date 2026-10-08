"""Советы в файлах: переживают перезапуск, прерванные ходы после него — упавшие."""

import json
import os

import pytest

from spec_council import deps
from spec_council import store as store_module
from spec_council.config import config_of, fitted
from spec_council.deps import data_folder
from spec_council.models import (
    CouncilStatus,
    Group,
    LabeledFragment,
    ModelRun,
    Slicing,
    Stream,
    StreamIdea,
    Structure,
)
from spec_council.pipeline import (
    start,
    start_analysis,
    start_idea,
    start_outcomes,
    start_proposals,
    start_questions,
    start_scan,
)
from spec_council.repository import Inventory
from spec_council.store import INTERRUPTED, FileStore


def done_slicing():
    return Slicing(state="done", run="s1", text="Хочу воркер.", steps=[], fragments=[
        LabeledFragment(id=1, text="Хочу воркер.", label="idea", reason="", council_label="idea")])


def test_councils_survive_a_restart_in_the_same_order(tmp_path):
    before = FileStore(tmp_path)
    first = before.create_council(participants=["sol", "fable"], judge="fable")
    second = before.create_council(participants=["sol", "fable"], judge="sol")
    structure = Structure(state="done", run="g1", slicing_run="s1", labels={1: "idea"}, steps=[],
                          groups=[Group(id="A", title="Воркер", fragment_ids=[1],
                                        idea_fragment_ids=[1], missing_idea=False)])
    before.update_council(first.id, {"name": "Проект", "slicing": done_slicing(),
                                     "structure": structure, "status": CouncilStatus.review,
                                     "streams": [Stream(group="A")]})
    before.update_council(second.id, {"brief": "черновик"}, touch=False)

    after = FileStore(tmp_path)
    assert after.list_councils() == before.list_councils()
    assert [c.id for c in after.list_councils()] == [first.id, second.id]
    assert after.get_council(first.id).structure.labels == {1: "idea"}
    assert after.get_council(second.id).brief == "черновик"


def test_runs_that_were_going_on_come_back_failed_and_can_be_started_again(tmp_path):
    before = FileStore(tmp_path)
    council = before.create_council(participants=["sol", "fable"], judge="fable")
    slicing = start(["sol", "fable"], "fable", "Хочу воркер.")
    slicing.steps[0].state = "running"
    slicing.steps[0].runs = [ModelRun(model="sol", state="running"),
                             ModelRun(model="fable", state="done")]
    found = Inventory(root=tmp_path, commit_sha="abc", dirty=False, files=())
    streams = [Stream(group="A", discovery=start_idea(["sol"], "sol"),
                      scan=start_scan(["sol"], "sol", "Идея", "project", found)),
               Stream(group="B", questions=start_questions(["sol"], "sol", "Идея"),
                      proposals=start_proposals(["sol"], "sol", []),
                      analysis=start_analysis(["sol"], "sol", []),
                      outcomes=start_outcomes(["sol"], "sol", []))]
    before.update_council(council.id, {"slicing": slicing, "streams": streams})

    after = FileStore(tmp_path).get_council(council.id)
    assert (after.slicing.state, after.slicing.error) == ("failed", INTERRUPTED)
    first, second = after.slicing.steps[:2]
    assert first.state == "failed"
    assert [(r.model, r.state, r.error) for r in first.runs] == [
        ("sol", "failed", INTERRUPTED), ("fable", "done", None)]
    assert second.state == "waiting"
    assert after.streams[0].discovery.state == "failed"
    assert after.streams[0].scan.state == "failed"
    assert (after.streams[1].questions.state, after.streams[1].questions.error) == (
        "failed", INTERRUPTED)
    assert after.streams[1].proposals.state == "failed"
    assert after.streams[1].analysis.state == "failed"
    assert after.streams[1].outcomes.state == "failed"
    # Отметка записана: следующий старт читает уже упавшие.
    saved = json.loads((tmp_path / f"{council.id}.json").read_text(encoding="utf-8"))
    assert saved["slicing"]["state"] == "failed"


def test_a_council_with_nothing_running_is_read_as_it_was(tmp_path):
    council = FileStore(tmp_path).create_council(participants=["sol", "fable"], judge="fable")
    assert FileStore(tmp_path).get_council(council.id) == council
    assert store_module.interrupted(council) is council


def test_an_unreadable_file_is_left_alone_and_skipped(tmp_path):
    kept = FileStore(tmp_path).create_council(participants=["sol", "fable"], judge="fable")
    broken = tmp_path / "broken.json"
    broken.write_text("{не json", encoding="utf-8")
    assert [c.id for c in FileStore(tmp_path).list_councils()] == [kept.id]
    assert broken.read_text(encoding="utf-8") == "{не json"


def test_a_change_that_did_not_reach_the_disk_did_not_happen(tmp_path, monkeypatch):
    files = FileStore(tmp_path)
    council = files.create_council(participants=["sol", "fable"], judge="fable")

    def full_disk(*_):
        raise OSError("нет места")

    monkeypatch.setattr(store_module.os, "replace", full_disk)
    with pytest.raises(OSError):
        files.update_council(council.id, {"name": "Проект"})
    assert files.get_council(council.id).name == ""
    monkeypatch.undo()
    assert FileStore(tmp_path).get_council(council.id).name == ""


def test_data_folder_comes_from_the_environment_or_next_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNCIL_DATA", str(tmp_path / "где-то"))
    assert data_folder() == tmp_path / "где-то"

    monkeypatch.delenv("COUNCIL_DATA")
    (tmp_path / ".env").write_text("COUNCIL_DATA=councils\n", encoding="utf-8")
    (tmp_path / "backend").mkdir()
    monkeypatch.chdir(tmp_path / "backend")
    assert data_folder() == (tmp_path / "councils").resolve()

    (tmp_path / ".env").write_text("AGENT_WORKERS_TOKEN=x\n", encoding="utf-8")
    assert data_folder() == (tmp_path / ".data").resolve()


def test_a_custom_folder_inside_the_repository_is_refused(tmp_path, monkeypatch):
    # Внутри репозитория прикрыт только .data: другой каталог попал бы в git и в сборку докера.
    monkeypatch.setattr(deps, "repository", lambda: tmp_path)
    monkeypatch.setenv("COUNCIL_DATA", str(tmp_path / "councils"))
    with pytest.raises(RuntimeError, match="внутри репозитория"):
        data_folder()
    monkeypatch.setenv("COUNCIL_DATA", str(tmp_path / ".data"))
    assert data_folder() == tmp_path / ".data"
    monkeypatch.setenv("COUNCIL_DATA", str(tmp_path.parent / "elsewhere"))
    assert data_folder() == tmp_path.parent / "elsewhere"


def test_a_folder_that_cannot_be_written_stops_the_start_with_a_reason(tmp_path, monkeypatch):
    # Каталог, созданный docker от root, а бэкенд под COUNCIL_UID: прочитать можно, писать нет.
    def refused(*_, dir=None, **__):
        raise PermissionError(13, "Permission denied", str(dir))

    monkeypatch.setattr(store_module.tempfile, "mkstemp", refused)
    with pytest.raises(RuntimeError, match="нельзя писать"):
        FileStore(tmp_path)


def test_the_write_check_leaves_other_files_alone(tmp_path):
    other = tmp_path / ".write-check"
    other.write_text("чужое", encoding="utf-8")
    FileStore(tmp_path)
    assert other.read_text(encoding="utf-8") == "чужое"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".write-check"]


@pytest.mark.skipif(os.name == "nt", reason="права файлов — только на Unix")
def test_council_files_are_for_the_owner_only(tmp_path):
    # Обычный umask на общей машине: без особой заботы файл открыт всем на чтение.
    before = os.umask(0o022)
    try:
        files = FileStore(tmp_path)
        council = files.create_council(participants=["sol", "fable"], judge="fable")
        path = tmp_path / f"{council.id}.json"
        assert path.stat().st_mode & 0o777 == 0o600
        files.update_council(council.id, {"brief": "текст"})
        assert path.stat().st_mode & 0o777 == 0o600
        assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]   # временных нет
    finally:
        os.umask(before)


def test_streams_saved_before_the_repository_step_passed_it_by_skipping(tmp_path):
    """Совет, сохранённый до шага «Репозиторий»: у потока с вопросами шаг считается
    пропущенным — иначе «Пропустить» пересчитало бы всё, что ниже, и стёрло бы работу."""
    before = FileStore(tmp_path)
    council = before.create_council(participants=["sol", "fable"], judge="fable")
    questions = start_questions(["sol"], "sol", "Идея").model_copy(update={"state": "done",
                                                                            "repository": ""})
    before.update_council(council.id, {"streams": [
        Stream(group="A", idea=StreamIdea(text="Идея", by="human"), questions=questions),
        Stream(group="B", idea=StreamIdea(text="Другая", by="human"))]})
    after = FileStore(tmp_path).get_council(council.id)
    first, second = after.streams
    assert (first.repository.by, first.questions.repository) == ("skipped", "skipped")
    assert second.repository is None                    # вопросов не было — шаг впереди


def test_councils_are_read_under_the_models_of_today(tmp_path):
    """fit подгоняет совет при чтении — и подогнанный записывается: следующий старт его так и
    прочитает."""
    before = FileStore(tmp_path)
    council = before.create_council(participants=["sol", "fable"], judge="sol")
    config = config_of("fable=claude/claude-fable-5-1", "opus=claude/claude-opus-5-5")
    after = FileStore(tmp_path, fit=lambda c: fitted(c, config)).get_council(council.id)
    assert (after.participants, after.judge) == (["fable", "opus"], "opus")
    saved = json.loads((tmp_path / f"{council.id}.json").read_text(encoding="utf-8"))
    assert saved["participants"] == ["fable", "opus"]
