"""Открытые вопросы: разбор ответов, вопросы из текста дословно, связи только с предложениями."""

import pytest

from spec_council.models import LabeledFragment
from spec_council.questions import (
    Candidate,
    merged,
    numbered,
    question_list,
    same_question,
    with_user_questions,
)
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


def test_an_inferred_question_whose_links_all_go_astray_stays_as_discovered():
    # Ссылки вторичны: чужие отброшены, а сам вопрос остаётся. Без них он уже не «восстановлен
    # по предложениям», а просто недостающий.
    found = question_list({"questions": [ask(proposals=("F3", "F9", "первый"))]}, GROUP)
    assert found == [Candidate("Как должен выполняться поиск?", "discovered", None, (),
                               "общая неопределённость")]


def test_questions_compare_like_the_screen_does():
    # Экран сравнивает через toLowerCase(): то же стандартное приведение, что lower(). casefold
    # склеил бы «Straße» и «STRASSE», которые экран считает разными, — и отбор после сервера
    # разошёлся бы с тем, что человек видел.
    assert same_question("  Как  искать? ") == same_question("как искать.")
    assert same_question("Straße?") != same_question("STRASSE")


@pytest.mark.parametrize(("bad", "problem"), [
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


@pytest.mark.parametrize("order", [1, -1])
def test_a_question_answered_by_proposals_stays_inferred_whichever_came_first(order):
    pair = [Candidate("Как искать?", "discovered", None, (), "не хватает"),
            Candidate("как искать", "inferred", None, (1, 2), "F1 и F2 отвечают")][::order]
    [found] = merged(pair)
    assert (found.source, found.proposal_ids, found.reason) == (
        "inferred", (1, 2), "F1 и F2 отвечают")


def test_a_generated_question_that_is_the_text_question_is_it_and_not_a_second_one():
    # Судья опустил вопрос из текста, но вернул ту же неопределённость как inferred.
    judged = [Candidate("Как искать?", "inferred", None, (1, 2), "a"),
              Candidate("кто решает, что тред полезный", "inferred", None, (1,), "b")]
    questions = numbered(with_user_questions(judged, GROUP))
    assert [(q.id, q.text, q.source, q.source_question_id, q.proposal_ids) for q in questions] == [
        ("Q1", "Как искать?", "inferred", None, [1, 2]),
        ("Q2", "Кто решает, что тред полезный?", "user", 4, [1])]


def test_questions_from_the_text_are_never_lost_and_are_numbered_in_order():
    judged = [Candidate("Как искать?", "inferred", None, (1, 2), "a")]
    questions = numbered(with_user_questions(judged, GROUP))
    assert [(q.id, q.text, q.source, q.source_question_id) for q in questions] == [
        ("Q1", "Как искать?", "inferred", None),
        ("Q2", "Кто решает, что тред полезный?", "user", 4)]


# --- формулировка заметки и пересмотр решений проекта

DECIDED = frozenset({"ADR-0007", "ADR-0012"})


def test_a_user_question_keeps_its_text_and_gets_an_atomic_note():
    """Вопрос пользователя дословен, а для заметки — своя формулировка: без вариантов внутри."""
    [user] = question_list({"questions": [
        {**ask(question="F4", source="user", proposals=()), "text": "что угодно",
         "note": "  Кто решает,   полезен ли тред? "}]}, GROUP)
    assert (user.text, user.note) == ("Кто решает, что тред полезный?",
                                      "Кто решает, полезен ли тред?")
    [blank] = question_list({"questions": [
        {**ask(question="F4", source="user", proposals=()), "note": "  "}]}, GROUP)
    assert blank.note is None                                 # нет — и не беда: вопрос остаётся
    [asked] = question_list({"questions": [{**ask(), "note": "лишнее"}]}, GROUP)
    assert asked.note is None                                 # у своего вопроса note не нужен


def test_a_question_revisits_only_a_decision_selected_for_the_stream():
    found = question_list({"questions": [
        {**ask("Откуда брать платежи?", "discovered", proposals=()), "revisits": "ADR-7"},
        {**ask("Где хранить чеки?", "discovered", proposals=()), "revisits": "ADR-0099"},
        {**ask("Как считать налог?", "discovered", proposals=()), "revisits": None}]},
        GROUP, DECIDED)
    assert [c.revisits for c in found] == ["ADR-0007", None, None]
    [question] = numbered(found[:1])
    assert question.revisits == "ADR-0007"


def test_merged_questions_keep_the_note_and_the_revisited_decision():
    first = Candidate("Кто решает, что тред полезный?", "user", 4, (), None)
    second = Candidate("Кто решает, что тред полезный?", "user", 4, (1,), None,
                       "Кто решает, полезен ли тред?", "ADR-0012")
    [both] = merged([first, second])
    assert (both.note, both.revisits, both.proposal_ids) == (
        "Кто решает, полезен ли тред?", "ADR-0012", (1,))
