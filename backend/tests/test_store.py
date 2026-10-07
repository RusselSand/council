"""Советы в файлах: переживают перезапуск, прерванные ходы после него — упавшие."""

import json
import os

import pytest

from spec_council import deps
from spec_council import store as store_module
from spec_council.deps import data_folder
from spec_council.models import (
    CouncilStatus,
    Group,
    LabeledFragment,
    ModelRun,
    Slicing,
    Stream,
    Structure,
)
from spec_council.pipeline import start, start_idea
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
    streams = [Stream(group="A", discovery=start_idea(["sol"], "sol")), Stream(group="B")]
    before.update_council(council.id, {"slicing": slicing, "streams": streams})

    after = FileStore(tmp_path).get_council(council.id)
    assert (after.slicing.state, after.slicing.error) == ("failed", INTERRUPTED)
    first, second = after.slicing.steps[:2]
    assert first.state == "failed"
    assert [(r.model, r.state, r.error) for r in first.runs] == [
        ("sol", "failed", INTERRUPTED), ("fable", "done", None)]
    assert second.state == "waiting"
    assert after.streams[0].discovery.state == "failed"
    assert after.streams[1] == Stream(group="B")
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
