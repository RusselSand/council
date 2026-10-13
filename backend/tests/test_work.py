"""Работа, которая переносится через правку отбора: задачи — с номерами ADR по новому отбору."""

from spec_council.models import (
    Choice,
    Decision,
    DecisionAnalysis,
    Issue,
    OpenQuestion,
    QuestionAnalysis,
    Stream,
)
from spec_council.work import carried_analyses, with_new_adrs


def question(n):
    return OpenQuestion(id=f"Q{n}", text=f"Вопрос {n}?", source="added")


def test_a_carried_issue_gets_the_adr_numbers_of_the_new_scope():
    # Q1 убрали: решение по Q2 было ADR-2, теперь оно первое — ADR-1.
    stream = Stream(group="C", scope=[question(2), question(3)], decisions=[
        Decision(question_id="Q2", proposal="P2", rationale="Так.", rationale_by="human"),
        Decision(question_id="Q3", proposal="P3", rationale="Иначе.", rationale_by="human")])
    issue = Issue(id="I1", title="Задача", user_story="As a team, I want it.", adr_ids=["ADR-2"])
    moved = with_new_adrs(issue, ["Q1: P1: Было.", "Q2: P2: Так."], stream)
    assert moved is not None and moved.adr_ids == ["ADR-1"]
    # Решение по Q2 с тех пор другое — задача уже не та.
    assert with_new_adrs(issue, ["Q1: P1: Было.", "Q2: P2: Раньше иначе."], stream) is None


def test_a_check_is_carried_while_the_choice_it_rests_on_is_the_same():
    choices = [Choice(question_id="Q1", proposal="P1"), Choice(question_id="Q2", proposal="P2")]
    rests = QuestionAnalysis(question_id="Q1", verdict="conflict", proposal="P1",
                             depends_on=["Q2"], context=["Q2: P2"])
    alone = QuestionAnalysis(question_id="Q2", verdict="validated", proposal="P2")
    stream = Stream(group="C", scope=[question(1), question(2)], choices=choices,
                    analysis=DecisionAnalysis(state="done", choices=["Q1: P1", "Q2: P2"], steps=[],
                                              analyses=[rests, alone]))
    assert carried_analyses(stream, choices) == {"Q1": rests, "Q2": alone}
    # По Q2 выбрали другое: проверка Q1 стояла на прежнем выборе — её повторяют.
    other = [choices[0], Choice(question_id="Q2", proposal="P3")]
    assert carried_analyses(stream, other) == {}
    # Проверка, которая выбора не запомнила, а от вопроса зависит, — тоже заново.
    blind = stream.model_copy(update={"analysis": stream.analysis.model_copy(update={
        "analyses": [rests.model_copy(update={"context": []}), alone]})})
    assert carried_analyses(blind, choices) == {"Q2": alone}
    # А вопрос, который просят перепроверить, не переносится, что бы ни было.
    assert carried_analyses(stream, choices, anew={"Q2"}) == {"Q1": rests}
