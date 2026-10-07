"""Открытые вопросы: разбор ответов, вопросы из текста дословно, связи только с предложениями."""

import pytest

from spec_council.models import LabeledFragment
from spec_council.questions import Candidate, merged, numbered, question_list, with_user_questions
from spec_council.slicing import BadAnswer

GROUP = {fragment.id: fragment for fragment in [
    LabeledFragment(id=i, text=text, label=label, reason="", council_label=label)
    for i, label, text in [
        (1, "proposal", "Полнотекстовый поиск."),
        (2, "proposal", "Или сразу векторный."),
        (3, "constraint", "Бюджет — до $200."),
        (4, "question", "Кто решает, что тред полезный?"),
    ]]}


def ask(text="Как должен выполняться поиск?", source="inferred", question=None,
        proposals=("F1", "F2"), reason="общая неопределённость"):
    return {"text": text, "source": source, "source_question_id": question,
            "proposal_ids": list(proposals), "reason": reason}


def test_inferred_and_discovered_questions_are_read_with_their_proposals():
    found = question_list({"questions": [
        ask(), ask("Как понять, что идея сработала?", "discovered", proposals=())]}, GROUP)
    assert found == [Candidate("Как должен выполняться поиск?", "inferred", None, (1, 2),
                               "общая неопределённость"),
                     Candidate("Как понять, что идея сработала?", "discovered", None, (),
                               "общая неопределённость")]


def test_a_question_from_the_text_stays_word_for_word():
    found = question_list({"questions": [ask("Кто решает полезность?", "user", "F4", ())]}, GROUP)
    assert [(c.text, c.source, c.source_question_id) for c in found] == [
        ("Кто решает, что тред полезный?", "user", 4)]


def test_links_go_only_to_proposals_of_the_group():
    found = question_list({"questions": [ask(proposals=("F1", "F3", "F9", 2, "первый"))]}, GROUP)
    assert found[0].proposal_ids == (1, 2)


@pytest.mark.parametrize(("bad", "problem"), [
    (ask(proposals=("F3",)), "inferred-вопрос без предложений"),
    (ask(source="user", question="F1"), "не вопрос этой группы"),
    (ask(source="guess"), "source не из"),
    (ask(text="  "), "нет текста"),
    (ask(text="x" * 501), "длиннее"),
    ("вопрос", "не объект"),
])
def test_a_bad_question_is_dropped_and_only_bad_ones_make_a_bad_answer(bad, problem):
    assert [c.text for c in question_list({"questions": [bad, ask()]}, GROUP)] == [
        "Как должен выполняться поиск?"]
    with pytest.raises(BadAnswer, match=problem):
        question_list({"questions": [bad]}, GROUP)


def test_no_questions_is_an_honest_answer_but_no_list_is_not():
    assert question_list({"questions": []}, GROUP) == []
    with pytest.raises(BadAnswer, match="questions"):
        question_list({"options": []}, GROUP)


def test_the_same_question_twice_is_one_with_all_its_proposals():
    found = merged([Candidate("Как искать?", "inferred", None, (1,), "a"),
                    Candidate("как  искать.", "inferred", None, (2,), "b")])
    assert found == [Candidate("Как искать?", "inferred", None, (1, 2), "a")]


def test_questions_from_the_text_are_never_lost_and_are_numbered_in_order():
    judged = [Candidate("Как искать?", "inferred", None, (1, 2), "a")]
    questions = numbered(with_user_questions(judged, GROUP))
    assert [(q.id, q.text, q.source, q.source_question_id) for q in questions] == [
        ("Q1", "Как искать?", "inferred", None),
        ("Q2", "Кто решает, что тред полезный?", "user", 4)]
