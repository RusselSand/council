"""Задачи: разбор ответа участника или судьи, ссылки, зависимости и пробелы."""

import pytest

from spec_council.issues import Context, as_prompt, issue_set, same_issues
from spec_council.slicing import BadAnswer

CONTEXT = Context(outcomes=frozenset({"O1", "O2"}), adrs=frozenset({"ADR-1"}),
                  constraints=frozenset({5}), risks=frozenset({7}),
                  open_questions=frozenset({"Q2"}),
                  questions={"где живёт база": "Q2", "как искать": "Q1"})


def issue(id_="I1", title="Поиск по базе", outcomes=("O1",), **extra):
    return {"id": id_, "title": title,
            "user_story": "As a member, I want to search the base, so that I find answers.",
            "main_entry_points": ["api/search.py"], "current_state": "Поиска нет.",
            "scope": ["Искать по заголовкам.", "Проверить пустой запрос."],
            "outcome_ids": list(outcomes), "adr_ids": ["ADR-1"], "constraint_ids": ["F5"],
            "risk_ids": [], "depends_on": [], "blocked_by": [], **extra}


def test_an_issue_keeps_only_references_it_may_have():
    """Чужие номера — итога, решения, ограничения — отбрасываются, а задача остаётся."""
    answer = issue_set({"issues": [issue(outcomes=("O1", "O9"), adr_ids=["ADR-1", "ADR-4"],
                                         constraint_ids=["F5", "F6"], risk_ids=["F7", "F2"])]},
                       CONTEXT)
    [found] = answer.issues
    assert (found.outcome_ids, found.adr_ids) == (("O1",), ("ADR-1",))
    assert (found.constraint_ids, found.risk_ids) == ((5,), (7,))
    assert found.scope == ("Искать по заголовкам.", "Проверить пустой запрос.")
    assert found.entry_points == ("api/search.py",)


def test_an_issue_without_an_approved_outcome_is_dropped():
    """Задача, которая не реализует ни одного утверждённого итога, — не задача."""
    answer = issue_set({"issues": [issue(), issue("I2", outcomes=("O9",))]}, CONTEXT)
    assert [found.name for found in answer.issues] == ["I1"]
    with pytest.raises(BadAnswer, match="утверждённого итога"):
        issue_set({"issues": [issue(outcomes=())]}, CONTEXT)


def test_an_answer_without_a_list_of_issues_is_refused_and_an_empty_one_is_honest():
    with pytest.raises(BadAnswer, match="issues"):
        issue_set({"gaps": []}, CONTEXT)
    assert issue_set({"issues": []}, CONTEXT).issues == ()


def test_dependencies_point_only_at_other_issues_of_the_answer():
    answer = issue_set({"issues": [
        issue("I1"), issue("I2", "Выдача", depends_on=["I1", "I2", "I9", "x"])]}, CONTEXT)
    assert [found.depends_on for found in answer.issues] == [(), ("I1",)]


def test_a_number_given_to_two_issues_is_no_link_to_either():
    answer = issue_set({"issues": [
        issue("I1"), issue("I1", "Выдача"), issue("I2", "Отчёт", depends_on=["I1"])]}, CONTEXT)
    assert [found.name for found in answer.issues] == ["", "", "I2"]
    assert answer.issues[2].depends_on == ()


def test_dependencies_in_a_circle_make_the_answer_unfit():
    with pytest.raises(BadAnswer, match="по кругу: I1 → I2 → I1"):
        issue_set({"issues": [issue("I1", depends_on=["I2"]),
                              issue("I2", "Выдача", depends_on=["I1"])]}, CONTEXT)


def test_a_gap_blocks_by_its_number_and_one_that_repeats_a_question_by_the_question():
    """Пробел, совпавший с открытым вопросом отбора, — блокировка им; с решённым — уже ответ."""
    answer = issue_set({"issues": [
        issue(blocked_by=["G1", "G2", "G3", "Q2", "Q1", "G9"])],
        "gaps": [{"question": "Где живёт база?", "reason": "нет", "outcome_ids": ["O2"]},
                 {"question": "Как искать?", "reason": "решено"},
                 {"question": "Сколько хранить историю?", "reason": "не решено",
                  "outcome_ids": ["O1", "O9"]}]}, CONTEXT)
    [found] = answer.issues
    assert found.blocked_by == ("G1", "Q2")
    assert [(gap.question, gap.outcome_ids) for gap in answer.gaps] == [
        ("Сколько хранить историю?", ("O1",))]


def test_an_issue_may_be_blocked_by_a_gap_named_by_its_text():
    answer = issue_set({"issues": [issue(blocked_by=["Сколько хранить историю?"])],
                        "gaps": [{"question": "Сколько хранить историю?", "reason": ""}]},
                       CONTEXT)
    assert answer.issues[0].blocked_by == ("G1",)


def test_the_same_issues_in_another_order_are_one_set():
    one = issue_set({"issues": [issue("I1"), issue("I2", "Выдача")]}, CONTEXT)
    other = issue_set({"issues": [issue("I1", "Выдача"), issue("I2")]}, CONTEXT)
    assert same_issues(one) == same_issues(other)
    assert as_prompt(one)["issues"][0]["constraint_ids"] == ["F5"]


def test_issue_sets_with_other_dependency_graphs_are_not_one_set():
    """Номера в ответах свои: «B после I1» — после разных задач, если I1 — разные задачи."""
    one = issue_set({"issues": [issue("I1", "А"), issue("I2", "Б", depends_on=["I1"]),
                                issue("I3", "В")]}, CONTEXT)
    other = issue_set({"issues": [issue("I1", "В"), issue("I2", "Б", depends_on=["I1"]),
                                  issue("I3", "А")]}, CONTEXT)
    assert same_issues(one) != same_issues(other)
    renumbered = issue_set({"issues": [issue("I5", "А"), issue("I7", "Б", depends_on=["I5"]),
                                       issue("I9", "В")]}, CONTEXT)
    assert same_issues(one) == same_issues(renumbered)


def test_an_issue_with_nothing_to_do_is_dropped():
    """Без scope coding agent'у нечего делать и нечем проверить, что готово."""
    answer = issue_set({"issues": [issue(), issue("I2", "Пусто", scope=[]),
                                   issue("I3", "Не список", scope="сделать")]}, CONTEXT)
    assert [found.name for found in answer.issues] == ["I1"]


def test_issues_without_a_number_get_one_nobody_else_has_for_the_judge():
    answer = issue_set({"issues": [issue(None, "Без номера"), issue("I1", "С номером"),
                                   issue("I2", "Ещё", depends_on=["I1"])]}, CONTEXT)
    ids = [item["id"] for item in as_prompt(answer)["issues"]]
    assert ids[1:] == ["I1", "I2"]
    assert ids[0] not in ("I1", "I2")
    assert len(set(ids)) == 3


def test_the_same_gaps_in_another_order_are_one_set():
    """Номер пробела — его место в ответе: одинаковые пробелы в другом порядке — тот же набор."""
    history = {"question": "Сколько хранить историю?", "reason": ""}
    format_ = {"question": "В каком формате отчёт?", "reason": ""}
    def answer(first, second, gaps):
        return issue_set({"issues": [issue(blocked_by=[first]),
                                     issue("I2", "Отчёт", outcomes=("O2",), blocked_by=[second])],
                           "gaps": gaps}, CONTEXT)

    one = answer("G1", "G2", [history, format_])
    assert same_issues(one) == same_issues(answer("G2", "G1", [format_, history]))
    assert same_issues(one) != same_issues(answer("G2", "G1", [history, format_]))


def test_a_gap_of_no_approved_outcome_is_dropped_unless_an_issue_waits_for_it():
    """Пробел ни к одному утверждённому итогу не держит поток; а тот, что держит задачу, — про
    её итоги, даже если модель их не назвала. Номера оставшихся — по порядку."""
    answer = issue_set({"issues": [issue(blocked_by=["G3"]), issue("I2", "Отчёт", outcomes=("O2",),
                                                                   blocked_by=["G2"])],
                        "gaps": [{"question": "Ни о чём?", "outcome_ids": ["O9"]},
                                 {"question": "Где отчёт?", "outcome_ids": []},
                                 {"question": "Сколько хранить?", "outcome_ids": ["O1"]}]},
                       CONTEXT)
    assert [(gap.question, gap.outcome_ids) for gap in answer.gaps] == [
        ("Где отчёт?", ("O2",)), ("Сколько хранить?", ("O1",))]
    assert [found.blocked_by for found in answer.issues] == [("G2",), ("G1",)]


def test_the_same_gap_named_twice_is_one_gap_about_both_outcomes():
    answer = issue_set({"issues": [issue(blocked_by=["G2"])],
                        "gaps": [{"question": "Где отчёт?", "outcome_ids": ["O1"]},
                                 {"question": "где отчёт", "outcome_ids": ["O2"]}]}, CONTEXT)
    assert [(gap.question, gap.outcome_ids) for gap in answer.gaps] == [
        ("Где отчёт?", ("O1", "O2"))]
    assert answer.issues[0].blocked_by == ("G1",)
