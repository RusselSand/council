"""Правки готовых групп человеком: объединить, разделить, переименовать, вернуть как было,
подтвердить."""

import pytest
from fastapi.testclient import TestClient

from spec_council.app import app
from spec_council.deps import get_store
from spec_council.groups import EditRefused, arranged, letter_for, merged, renamed, restored, split
from spec_council.models import (
    CouncilStatus,
    Group,
    GroupRelation,
    LabeledFragment,
    Slicing,
    Structure,
    StructureProposal,
)

client = TestClient(app)


def grp(gid, fragments, ideas=(), title=None):
    return Group(id=gid, title=title or f"Группа {gid}", fragment_ids=list(fragments),
                 idea_fragment_ids=list(ideas), missing_idea=not ideas)


def rel(source, target, kind="related"):
    return GroupRelation(source=source, target=target, type=kind, reason=f"{source}-{target}")


LABELS = {1: "idea", 2: "proposal", 3: "risk", 4: "constraint", 5: "idea"}


def done(groups, relations=()):
    groups, relations = arranged(list(groups)), list(relations)
    return Structure(state="done", run="g1", slicing_run="s1", labels=LABELS, steps=[],
                     groups=groups, relations=relations,
                     proposal=StructureProposal(groups=groups, relations=relations))


def sliced(labels=LABELS):
    return Slicing(state="done", run="s1", steps=[], fragments=[
        LabeledFragment(id=i, text=f"F{i}", label=label, reason="", council_label=label)
        for i, label in labels.items()])


# A = {F1, F2, F3}, B = {F3, F4} (F3 общий), C = {F5}.
BASE = done([grp("A", [1, 2, 3], ideas=[1]), grp("B", [3, 4]), grp("C", [5], ideas=[5])],
            [rel("B", "A", "depends_on"), rel("C", "A"), rel("C", "B", "depends_on")])


def apply(structure, changes):
    return structure.model_copy(update=changes)


def view(structure):
    return [(g.id, g.fragment_ids, g.shared_fragment_ids) for g in structure.groups]


def test_merged_group_keeps_the_letter_and_title_of_the_one_clicked():
    result = apply(BASE, merged(BASE, "A", "B"))
    assert view(result) == [("A", [1, 2, 3, 4], []), ("C", [5], [])]
    assert result.groups[0].title == "Группа A"
    assert result.groups[0].idea_fragment_ids == [1]
    assert result.edited


def test_merge_drops_the_link_between_them_and_keeps_the_clicked_groups_links():
    # C→B переходит к C и расходится со связью C–A группы, где нажали: остаётся та.
    result = apply(BASE, merged(BASE, "C", "B"))
    assert view(result) == [("A", [1, 2, 3], [3]), ("C", [3, 4, 5], [3])]
    assert [(r.source, r.target, r.type) for r in result.relations] == [("C", "A", "related")]


@pytest.mark.parametrize(("group", "other", "problem"), [
    ("A", "A", "с самой собой"),
    ("A", "X", "Нет группы X"),
])
def test_merge_that_makes_no_sense_is_refused(group, other, problem):
    with pytest.raises(EditRefused, match=problem):
        merged(BASE, group, other)


def test_split_takes_the_first_free_letter_and_leaves_links_with_the_old_group():
    result = apply(BASE, split(BASE, "A", [2], "  Хранение "))
    assert view(result) == [("A", [1, 3], [3]), ("D", [2], []), ("B", [3, 4], [3]),
                            ("C", [5], [])]
    new = result.groups[1]
    assert (new.title, new.missing_idea) == ("Хранение", True)
    assert result.relations == BASE.relations


def test_a_shared_fragment_stays_shared_after_a_split():
    result = apply(BASE, split(BASE, "A", [1, 3], "Идея"))
    assert view(result) == [("D", [1, 3], [3]), ("A", [2], []), ("B", [3, 4], [3]),
                            ("C", [5], [])]
    assert result.groups[0].idea_fragment_ids == [1]
    assert result.groups[1].missing_idea


@pytest.mark.parametrize(("fragments", "title", "problem"), [
    ([], "Новая", "Отметьте"),
    ([4], "Новая", "нет F4"),
    ([1, 2, 3], "Новая", "должно что-то остаться"),
    ([2], "   ", "Нужно название"),
    ([2], "я" * 201, "длиннее 200"),
])
def test_split_that_makes_no_sense_is_refused(fragments, title, problem):
    with pytest.raises(EditRefused, match=problem):
        split(BASE, "A", fragments, title)


def test_an_edit_may_not_make_two_groups_of_the_same_fragments():
    structure = done([grp("A", [1, 2], ideas=[1]), grp("B", [2])])
    with pytest.raises(EditRefused, match="совпали бы по составу"):
        split(structure, "A", [2], "Вторая B")


def test_rename_and_restore():
    result = apply(BASE, renamed(BASE, "B", "Хранение"))
    assert result.groups[1].title == "Хранение"
    with pytest.raises(EditRefused, match="Нужно название"):
        renamed(BASE, "B", "")
    back = apply(result, restored(result))
    assert back.groups == BASE.groups
    assert not back.edited


def test_letters_go_on_after_z():
    assert [letter_for(n) for n in (0, 25, 26, 27)] == ["A", "Z", "A2", "B2"]


# --- API

def council_with(structure, slicing=None):
    council_id = client.post("/api/councils").json()["id"]
    get_store().update_council(council_id, {"slicing": slicing or sliced(),
                                            "structure": structure,
                                            "status": CouncilStatus.structure})
    return council_id


def post(council_id, action, revision=0, **body):
    return client.post(f"/api/councils/{council_id}/structure/{action}",
                       json={"revision": revision, **body})


def test_edits_are_saved_and_can_be_undone():
    council_id = council_with(BASE)
    res = post(council_id, "merge", run="g1", group="A", other="B")
    assert res.status_code == 200
    structure = res.json()["structure"]
    assert [g["id"] for g in structure["groups"]] == ["A", "C"]
    assert structure["edited"] is True

    res = post(council_id, "split", 1, run="g1", group="A", fragment_ids=[4], title="Хранение")
    assert [g["id"] for g in res.json()["structure"]["groups"]] == ["A", "B", "C"]
    res = post(council_id, "rename", 2, run="g1", group="C", title="Другое")
    assert res.json()["structure"]["groups"][2]["title"] == "Другое"

    res = post(council_id, "restore", 3, run="g1")
    assert res.json()["structure"]["edited"] is False
    assert res.json()["structure"]["revision"] == 4
    assert get_store().get_council(council_id).structure.groups == BASE.groups


@pytest.mark.parametrize("structure", [
    None,
    BASE.model_copy(update={"run": "g2"}),                       # разложили заново
    BASE.model_copy(update={"state": "running", "groups": []}),  # раскладка идёт
])
def test_an_edit_for_other_groups_is_refused_with_409(structure):
    council_id = council_with(structure)
    res = post(council_id, "merge", run="g1", group="A", other="B")
    assert res.status_code == 409
    assert get_store().get_council(council_id).structure == structure


def test_an_edit_to_an_earlier_revision_is_refused():
    # Другая вкладка объединила A с B и вынесла F4 в новую B: старая «B» — уже не та группа.
    council_id = council_with(BASE)
    post(council_id, "merge", run="g1", group="A", other="B")
    post(council_id, "split", 1, run="g1", group="A", fragment_ids=[4], title="Новая B")
    res = post(council_id, "rename", 0, run="g1", group="B", title="Хранение")
    assert res.status_code == 409
    assert "уже поменяли" in res.json()["detail"]
    assert get_store().get_council(council_id).structure.groups[1].title == "Новая B"


@pytest.mark.parametrize("slicing", [
    sliced({**LABELS, 2: "idea"}),                          # тип поменяли после раскладки
    sliced().model_copy(update={"run": "s2"}),              # нарезку переделали
])
def test_an_outdated_grouping_is_not_edited(slicing):
    council_id = council_with(BASE, slicing)
    res = post(council_id, "split", run="g1", group="A", fragment_ids=[2], title="Новая")
    assert res.status_code == 409
    assert "сначала разложите заново" in res.json()["detail"]
    assert get_store().get_council(council_id).structure == BASE


def test_a_senseless_edit_is_422_and_changes_nothing():
    council_id = council_with(BASE)
    res = post(council_id, "split", run="g1", group="A", fragment_ids=[], title="Новая")
    assert res.status_code == 422
    assert "Отметьте" in res.json()["detail"]
    assert post(council_id, "rename", run="g1", group="A", title="x", extra=1).status_code == 422
    assert get_store().get_council(council_id).structure == BASE


def test_edit_of_unknown_council_is_404():
    assert post("missing", "restore", run="g1").status_code == 404
    assert post("missing", "confirm", run="g1").status_code == 404


def status_of(council_id):
    return get_store().get_council(council_id).status


def test_confirmed_groups_become_streams_and_edits_after_that_keep_them():
    council_id = council_with(BASE)
    res = post(council_id, "confirm", run="g1")
    assert res.status_code == 200
    assert res.json()["status"] == "review"
    assert res.json()["structure"]["revision"] == 0   # подтверждение — не правка групп
    assert post(council_id, "confirm", run="g1").json()["status"] == "review"

    assert post(council_id, "merge", run="g1", group="A", other="B").status_code == 200
    assert status_of(council_id) == "review"


@pytest.mark.parametrize(("run", "revision", "problem"), [
    ("g0", 0, "разложили заново"),
    ("g1", 1, "уже поменяли"),
])
def test_only_the_groups_on_screen_are_confirmed(run, revision, problem):
    council_id = council_with(BASE)
    res = post(council_id, "confirm", revision, run=run)
    assert res.status_code == 409
    assert problem in res.json()["detail"]
    assert status_of(council_id) == "structure"


def test_an_outdated_grouping_is_not_confirmed():
    council_id = council_with(BASE, sliced({**LABELS, 2: "idea"}))
    res = post(council_id, "confirm", run="g1")
    assert res.status_code == 409
    assert "сначала разложите заново" in res.json()["detail"]
    assert status_of(council_id) == "structure"
