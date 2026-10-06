"""Идея группы: разбор ответов участников и судьи, сведение одинаковых вариантов."""

import pytest

from spec_council.ideas import (
    IdeaAnswer,
    IdeaCandidate,
    IdeaVerdict,
    idea_options,
    judged_idea,
    merged,
)
from spec_council.slicing import BadAnswer

GROUP = {1, 2, 3, 4}
IDEA = "Команда сама находит ответы в базе знаний"


def option(idea=IDEA, evidence=("F1", "F2"), reason="общая цель"):
    return {"idea": idea, "evidence": list(evidence), "reason": reason}


def test_options_take_fragment_numbers_as_f_or_plain():
    answer = idea_options({"number": 1, "options": [option(evidence=["F1", 3, " f2 "])]}, GROUP)
    assert answer == IdeaAnswer((IdeaCandidate(IDEA, (1, 2, 3), "общая цель"),), "")


def test_no_options_is_an_honest_answer_with_a_reason():
    answer = idea_options({"number": 0, "options": [], "reason": "нет  общей цели"}, GROUP)
    assert answer == IdeaAnswer((), "нет общей цели")


@pytest.mark.parametrize(("bad", "problem"), [
    (option(evidence=["F9"]), "F9 нет в группе"),
    (option(evidence=[]), "нет evidence"),
    (option(evidence=["первый"]), "не номер фрагмента"),
    (option(idea="  "), "нет текста идеи"),
    (option(idea="x" * 1001), "длиннее"),
    ("идея", "не объект"),
])
def test_a_bad_option_is_dropped_and_only_bad_ones_make_a_bad_answer(bad, problem):
    kept = idea_options({"options": [bad, option()]}, GROUP)
    assert [o.idea for o in kept.options] == [IDEA]
    with pytest.raises(BadAnswer, match=problem):
        idea_options({"options": [bad]}, GROUP)


def test_answer_without_options_is_bad():
    with pytest.raises(BadAnswer, match="options"):
        idea_options({"number": 1}, GROUP)


def test_judge_may_merge_wordings_but_stands_on_the_group():
    verdict = judged_idea({"status": "ok", **option(idea="Сводная формулировка")}, GROUP)
    assert verdict == IdeaVerdict("Сводная формулировка", (1, 2), "общая цель")
    with pytest.raises(BadAnswer, match="F7 нет в группе"):
        judged_idea({"status": "ok", **option(evidence=["F7"])}, GROUP)
    with pytest.raises(BadAnswer, match="status"):
        judged_idea({"status": "maybe"}, GROUP)


def test_judge_rejecting_all_is_a_result_not_a_failure():
    verdict = judged_idea({"status": "no_valid_option", "reason": "цель не видна"}, GROUP)
    assert verdict == IdeaVerdict(None, (), "цель не видна")


def test_same_wording_from_two_models_is_one_option():
    sol = IdeaAnswer((IdeaCandidate(IDEA, (1,), "у sol"),
                      IdeaCandidate("Другая цель", (4,), "")), "")
    fable = IdeaAnswer((IdeaCandidate(IDEA.upper() + ".", (2, 3), "у fable"),), "")
    options = merged({"sol": sol, "fable": fable})
    assert [(o.idea, o.evidence, o.reason, o.models) for o in options] == [
        (IDEA, {1, 2, 3}, "у sol", ["sol", "fable"]),
        ("Другая цель", {4}, "", ["sol"]),
    ]
