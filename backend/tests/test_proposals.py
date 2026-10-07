"""Варианты ответа: разбор ответов участников и судьи, ссылки только на своё, сведение."""

import pytest

from spec_council.proposals import (
    Candidate,
    Context,
    Verdict,
    judged_proposals,
    merged,
    proposal_list,
)
from spec_council.slicing import BadAnswer

CONTEXT = Context(constraints=frozenset({4}), risks=frozenset({5}), questions=frozenset({"Q2"}))


def offer(text="Гибрид: полнотекстовый отбор и переранжирование", reason="точно и дёшево",
          constraints=("F4",), risks=(), depends=()):
    return {"text": text, "reason": reason, "constraint_ids": list(constraints),
            "risk_ids": list(risks), "depends_on_question_ids": list(depends)}


def test_proposals_are_read_with_their_links():
    found = proposal_list({"proposals": [offer(risks=("F5",), depends=("q2",))]}, CONTEXT)
    assert found == [Candidate("Гибрид: полнотекстовый отбор и переранжирование", "точно и дёшево",
                               (4,), (5,), ("Q2",))]


def test_links_go_only_to_what_the_stream_has_and_the_proposal_stays():
    found = proposal_list({"proposals": [offer(constraints=("F4", "F5", "F9"),
                                               risks=("F4", "x"), depends=("Q1", "Q9"))]}, CONTEXT)
    assert (found[0].constraint_ids, found[0].risk_ids, found[0].depends_on) == ((4,), (), ())


@pytest.mark.parametrize(("bad", "problem"), [
    (offer(text="  "), "нет текста"),
    (offer(text="x" * 601), "длиннее"),
    ("вариант", "не объект"),
])
def test_a_bad_proposal_is_dropped_and_only_bad_ones_make_a_bad_answer(bad, problem):
    assert len(proposal_list({"proposals": [bad, offer()]}, CONTEXT)) == 1
    with pytest.raises(BadAnswer, match=problem):
        proposal_list({"proposals": [bad]}, CONTEXT)


def test_no_new_proposals_is_an_honest_answer_but_no_list_is_not():
    assert proposal_list({"proposals": []}, CONTEXT) == []
    with pytest.raises(BadAnswer, match="proposals"):
        proposal_list({"options": []}, CONTEXT)


def test_the_same_proposal_twice_is_one_with_all_its_links():
    one = Candidate("Бот в Slack.", "a", (4,), (), ())
    two = Candidate("бот в  slack", "b", (), (5,), ("Q2",))
    assert merged([one, two]) == [Candidate("Бот в Slack.", "a", (4,), (5,), ("Q2",))]


def test_the_judge_recommends_one_offers_alternatives_or_nothing():
    recommended = judged_proposals({"status": "recommended", "proposal": offer()}, CONTEXT)
    assert (recommended.kind, len(recommended.proposals)) == ("recommended", 1)
    alternatives = judged_proposals({"status": "alternatives", "reason": "зависит от бюджета",
                                     "proposals": [offer(), offer("Векторная база")]}, CONTEXT)
    assert (alternatives.kind, alternatives.reason, len(alternatives.proposals)) == (
        "alternatives", "зависит от бюджета", 2)
    nothing = judged_proposals({"status": "no_recommendation", "reason": "всё есть"}, CONTEXT)
    assert nothing == Verdict("none", (), "всё есть")


@pytest.mark.parametrize(("bad", "problem"), [
    ({"status": "maybe"}, "status"),
    ({"status": "alternatives", "proposals": []}, "без вариантов"),
    ({"status": "recommended", "proposal": "вариант"}, "не объект"),
])
def test_a_judge_answer_out_of_form_is_bad(bad, problem):
    with pytest.raises(BadAnswer, match=problem):
        judged_proposals(bad, CONTEXT)
