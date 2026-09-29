"""Раскладка по группам: разбор ответов, сравнение по содержанию, проверка итога судьи."""

import pytest

from spec_council.grouping import (
    Decision,
    judged_structure,
    structure_of,
    structure_options,
)
from spec_council.slicing import BadAnswer, JudgeRejected

IDS = [1, 2, 3, 4, 5]


def group(gid, fragments, ideas=(), shared=(), title=None):
    return {"id": gid, "title": title or f"Группа {gid}", "idea_fragment_ids": list(ideas),
            "fragment_ids": list(fragments), "missing_idea": not ideas,
            "shared_fragment_ids": list(shared)}


def option(*groups, relations=()):
    return {"groups": list(groups), "relations": list(relations), "reason": None}


def relation(source, target, kind="related"):
    return {"from": source, "to": target, "type": kind, "reason": "потому что"}


TWO = option(group("A", [1, 2, 3, 4], ideas=[1]), group("B", [5], shared=[4]))


def test_a_valid_structure_is_read_with_shared_fragments():
    parsed = structure_of(TWO, IDS)
    assert [g.members for g in parsed.groups] == [frozenset({1, 2, 3, 4}), frozenset({4, 5})]
    assert parsed.shared() == frozenset({4})
    assert parsed.core(parsed.group("B")) == frozenset({5})


@pytest.mark.parametrize(("data", "problem"), [
    (option(group("A", [1, 2, 3])), "не попали ни в одну группу: 4, 5"),
    (option(group("A", [1, 2, 3, 4, 9]), group("B", [5])), "нет фрагментов 9"),
    (option(group("A", [1, 2]), group("A", [3, 4, 5])), "две группы с одним id"),
    (option(group("A", [1, 2, 3, 4]), group("B", [5]), relations=[relation("A", "C")]),
     "несуществующими группами"),
    (option(group("A", [1, 2, 3, 4]), group("B", [5]), relations=[relation("A", "B", "blocks")]),
     "тип связи"),
    (option(group("A", ["1", 2, 3, 4]), group("B", [5])), "нужен список номеров"),
    ({"groups": []}, "нет списка groups"),
])
def test_bad_structures_are_refused(data, problem):
    with pytest.raises(BadAnswer, match=problem):
        structure_of(data, IDS)


def test_a_bad_option_is_dropped_while_a_good_one_remains():
    parsed = structure_options({"options": [option(group("A", [1])), TWO]}, IDS)
    assert len(parsed) == 1


def test_same_grouping_under_other_letters_and_titles_is_the_same():
    renamed = option(group("X", [5], shared=[4], title="Импорт"),
                     group("Y", [1, 2, 3, 4], ideas=[1], title="Поиск"))
    assert structure_of(TWO, IDS).key() == structure_of(renamed, IDS).key()


def test_a_moved_fragment_or_a_new_relation_is_a_different_grouping():
    moved = option(group("A", [1, 2, 3]), group("B", [4, 5]))
    related = option(group("A", [1, 2, 3, 4], ideas=[1]), group("B", [5], shared=[4]),
                     relations=[relation("B", "A")])
    independent = option(group("A", [1, 2, 3, 4], ideas=[1]), group("B", [5], shared=[4]),
                         relations=[relation("B", "A", "independent")])
    base = structure_of(TWO, IDS).key()
    assert structure_of(moved, IDS).key() != base
    assert structure_of(related, IDS).key() != base
    assert structure_of(independent, IDS).key() == base   # независимость — не связь


def test_judge_may_combine_variants_but_not_invent_groups_or_relations():
    split = structure_of(TWO, IDS)
    moved = structure_of(option(group("A", [1, 2, 3]), group("B", [4, 5]),
                                relations=[relation("B", "A")]), IDS)
    candidates = [split, moved]

    # Разбивка из первого варианта, связь — из второго: обе есть среди кандидатов.
    mixed = option(group("A", [1, 2, 3]), group("B", [4, 5]), relations=[relation("B", "A")])
    chosen, _ = judged_structure({"status": "ok", **mixed}, IDS, candidates)
    assert len(chosen.groups) == 2

    with pytest.raises(BadAnswer, match="группу, которой нет ни в одном варианте: F1, F2"):
        judged_structure({"status": "ok", **option(group("A", [1, 2]), group("B", [3, 4, 5]))},
                         IDS, candidates)
    with pytest.raises(BadAnswer, match="придумал связь"):
        invented = option(group("A", [1, 2, 3, 4]), group("B", [5], shared=[4]),
                          relations=[relation("A", "B", "depends_on")])
        judged_structure({"status": "ok", **invented}, IDS, candidates)


def test_judge_refusal_and_its_decisions():
    with pytest.raises(JudgeRejected, match="не принял ни один вариант: оба теряют F5"):
        judged_structure({"status": "no_valid_option", "problem": "оба теряют F5"}, IDS, [])
    _, decisions = judged_structure({"status": "ok", **TWO, "decisions": [
        {"issue": "F4: A или A+B", "decision": "A+B", "reason": "касается обеих"},
        {"issue": "без решения"},
    ]}, IDS, [structure_of(TWO, IDS)])
    assert decisions == [Decision("F4: A или A+B", "A+B", "касается обеих")]
