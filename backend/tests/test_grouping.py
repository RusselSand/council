"""Раскладка по группам: разбор ответов, сравнение по содержанию, проверка итога судьи."""

import pytest

from spec_council.grouping import (
    JudgeDecision,
    judged_structure,
    structure_of,
    structure_options,
)
from spec_council.slicing import BadAnswer, JudgeRejected

LABELS = {1: "idea", 2: "proposal", 3: "question", 4: "risk", 5: "constraint"}


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
    parsed = structure_of(TWO, LABELS)
    assert [g.members for g in parsed.groups] == [frozenset({1, 2, 3, 4}), frozenset({4, 5})]
    assert parsed.shared() == frozenset({4})
    assert parsed.group("A").ideas == frozenset({1}) and not parsed.group("B").ideas


def test_ideas_come_from_fragment_types_not_from_the_answer():
    claimed = option(group("A", [1, 2, 3], ideas=[2]), group("B", [4, 5], ideas=[5]))
    parsed = structure_of(claimed, LABELS)
    assert parsed.group("A").ideas == frozenset({1})
    assert parsed.group("B").ideas == frozenset()


@pytest.mark.parametrize(("data", "problem"), [
    (option(group("A", [1, 2, 3])), "не попали ни в одну группу: 4, 5"),
    (option(group("A", [1, 2, 3, 4, 9]), group("B", [5])), "нет фрагментов 9"),
    (option(group("A", [1, 2]), group("A", [3, 4, 5])), "две группы с одним id"),
    (option(group("A", [1, 2, 3, 4, 5]), group("B", [1, 2, 3, 4, 5])), "одинаковым составом"),
    (option(group("A", [1, 2, 3, 4]), group("B", [5]), relations=[relation("A", "C")]),
     "несуществующими группами"),
    (option(group("A", [1, 2, 3, 4]), group("B", [5]), relations=[relation("A", "B", "blocks")]),
     "тип связи"),
    (option(group("A", [1, 2, 3, 4]), group("B", [5]),
            relations=[relation("A", "B"), relation("A", "B", "depends_on")]), "две разные связи"),
    (option(group("A", [1, 2, 3, 4]), group("B", [5]),
            relations=[relation("A", "B", "depends_on"), relation("B", "A", "depends_on")]),
     "две разные связи"),
    (option(group("A", ["1", 2, 3, 4]), group("B", [5])), "нужен список номеров"),
    ({"groups": []}, "нет списка groups"),
])
def test_bad_structures_are_refused(data, problem):
    with pytest.raises(BadAnswer, match=problem):
        structure_of(data, LABELS)


def test_a_bad_option_is_dropped_while_a_good_one_remains():
    parsed = structure_options({"options": [option(group("A", [1])), TWO]}, LABELS)
    assert len(parsed) == 1


def test_same_grouping_under_other_letters_and_titles_is_the_same():
    renamed = option(group("X", [5], shared=[4], title="Импорт"),
                     group("Y", [1, 2, 3, 4], ideas=[1], title="Поиск"))
    assert structure_of(TWO, LABELS).key() == structure_of(renamed, LABELS).key()


def test_a_moved_fragment_or_a_new_relation_is_a_different_grouping():
    moved = option(group("A", [1, 2, 3]), group("B", [4, 5]))
    related = option(group("A", [1, 2, 3, 4], ideas=[1]), group("B", [5], shared=[4]),
                     relations=[relation("B", "A")])
    independent = option(group("A", [1, 2, 3, 4], ideas=[1]), group("B", [5], shared=[4]),
                         relations=[relation("B", "A", "independent")])
    base = structure_of(TWO, LABELS).key()
    assert structure_of(moved, LABELS).key() != base
    assert structure_of(related, LABELS).key() != base
    assert structure_of(independent, LABELS).key() == base   # независимость — не связь


def test_a_repeated_relation_is_kept_once():
    twice = option(group("A", [1, 2, 3, 4]), group("B", [5]),
                   relations=[relation("A", "B"), relation("B", "A")])
    assert len(structure_of(twice, LABELS).relations) == 1


def test_related_has_no_direction_but_depends_on_has():
    def linked(source, target, kind):
        return structure_of(option(group("A", [1, 2, 3, 4]), group("B", [5], shared=[4]),
                                   relations=[relation(source, target, kind)]), LABELS).key()
    assert linked("A", "B", "related") == linked("B", "A", "related")
    assert linked("A", "B", "depends_on") != linked("B", "A", "depends_on")


def test_judge_may_combine_variants_but_not_invent_groups_or_relations():
    split = structure_of(TWO, LABELS)
    moved = structure_of(option(group("A", [1, 2, 3]), group("B", [4, 5]),
                                relations=[relation("B", "A")]), LABELS)
    candidates = [split, moved]

    # Разбивка из первого варианта, связь — из второго (у related направления нет).
    mixed = option(group("A", [1, 2, 3, 4], ideas=[1]), group("B", [5], shared=[4]),
                   relations=[relation("A", "B")])
    chosen, _ = judged_structure({"status": "ok", **mixed}, LABELS, candidates)
    assert len(chosen.groups) == 2

    with pytest.raises(BadAnswer, match="группу, которой нет ни в одном варианте: F1, F2"):
        judged_structure({"status": "ok", **option(group("A", [1, 2]), group("B", [3, 4, 5]))},
                         LABELS, candidates)
    with pytest.raises(BadAnswer, match="придумал связь"):
        invented = option(group("A", [1, 2, 3, 4]), group("B", [5], shared=[4]),
                          relations=[relation("A", "B", "depends_on")])
        judged_structure({"status": "ok", **invented}, LABELS, candidates)


def test_judge_may_share_a_fragment_only_where_some_variant_placed_it():
    only_a = structure_of(option(group("A", [1, 2, 4]), group("B", [3, 5])), LABELS)
    only_b = structure_of(option(group("A", [1, 2]), group("B", [3, 4, 5])), LABELS)
    both = option(group("A", [1, 2], shared=[4]), group("B", [3, 5], shared=[4]))
    chosen, _ = judged_structure({"status": "ok", **both}, LABELS, [only_a, only_b])
    assert chosen.shared() == frozenset({4})

    # F4 общий у A и B, C = {F3}: отдать F4 ещё и C не предлагал никто.
    shared = structure_of(option(group("A", [1], shared=[4]), group("B", [2], shared=[4]),
                                 group("C", [3, 5])), LABELS)
    apart = structure_of(option(group("A", [1, 4]), group("B", [2]), group("C", [3, 5])), LABELS)
    wider = option(group("A", [1], shared=[4]), group("B", [2], shared=[4]),
                   group("C", [3, 5], shared=[4]))
    with pytest.raises(BadAnswer, match="поместил F4 в группу C"):
        judged_structure({"status": "ok", **wider}, LABELS, [shared, apart])


def test_a_group_of_shared_fragments_only_must_match_a_variant_whole():
    # Группы {F1}, {F2} — из одних общих фрагментов: их нельзя слить в новую {F1, F2}.
    loose = structure_of(option(group("A", [1]), group("B", [2]), group("C", [3], shared=[1]),
                                group("D", [4], shared=[2]), group("E", [5])), LABELS)
    merged = option(group("X", [1, 2]), group("C", [3], shared=[1]), group("D", [4], shared=[2]),
                    group("E", [5]))
    with pytest.raises(BadAnswer, match="группу, которой нет ни в одном варианте: F1, F2"):
        judged_structure({"status": "ok", **merged}, LABELS, [loose])


def test_judge_may_not_undo_what_every_variant_agreed_on():
    # Оба варианта ставят риск F3 в A и B и спорят только о связи.
    both = option(group("A", [1], shared=[3]), group("B", [2], shared=[3]), group("C", [4, 5]))
    linked = {**both, "relations": [relation("A", "B")]}
    candidates = [structure_of(both, LABELS), structure_of(linked, LABELS)]
    dropped = option(group("A", [1, 3]), group("B", [2]), group("C", [4, 5]))
    with pytest.raises(BadAnswer, match="убрал F3 из группы B"):
        judged_structure({"status": "ok", **dropped}, LABELS, candidates)

    # Оба варианта связывают B с A и спорят только о том, общий ли F4.
    depends = [relation("B", "A", "depends_on")]
    apart = option(group("A", [1, 2]), group("B", [3]), group("C", [4, 5]), relations=depends)
    shared = option(group("A", [1, 2], shared=[4]), group("B", [3]), group("C", [5], shared=[4]),
                    relations=depends)
    candidates = [structure_of(apart, LABELS), structure_of(shared, LABELS)]
    unlinked = {**apart, "relations": []}
    with pytest.raises(BadAnswer, match="убрал связь, которая есть во всех вариантах"):
        judged_structure({"status": "ok", **unlinked}, LABELS, candidates)
    chosen, _ = judged_structure({"status": "ok", **apart}, LABELS, candidates)
    assert len(chosen.relations) == 1


def test_judge_refusal_and_its_decisions():
    with pytest.raises(JudgeRejected, match="не принял ни один вариант: оба теряют F5"):
        judged_structure({"status": "no_valid_option", "problem": "оба теряют F5"}, LABELS, [])
    _, decisions = judged_structure({"status": "ok", **TWO, "decisions": [
        {"issue": "F4: A или A+B", "decision": "A+B", "reason": "касается обеих"},
        {"issue": "без решения"},
    ]}, LABELS, [structure_of(TWO, LABELS)])
    assert decisions == [JudgeDecision("F4: A или A+B", "A+B", "касается обеих")]
