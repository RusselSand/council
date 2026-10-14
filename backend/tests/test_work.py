"""Работа, которая переносится через правку отбора: задачи — с номерами ADR по новому отбору."""

from spec_council.decisions import Analysis, Fix
from spec_council.models import (
    Choice,
    Decision,
    DecisionAnalysis,
    DecisionFix,
    Issue,
    OpenQuestion,
    Outcome,
    OutcomeDiscovery,
    ProjectDecision,
    QuestionAnalysis,
    Stream,
)
from spec_council.pipeline import analysis_of_question
from spec_council.work import carried_analyses, kept_outcomes, with_new_adrs


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
    # Судья велел поправить Q2, а в depends_on его не назвал: проверка опирается и на него.
    fixed = rests.model_copy(update={"depends_on": [], "fixes": [
        DecisionFix(question_id="Q2", change="Решите Q2."),
        DecisionFix(question_id="Q1", change="Уберите «и в облако».")]})
    told = stream.model_copy(update={"analysis": stream.analysis.model_copy(update={
        "analyses": [fixed, alone]})})
    assert carried_analyses(told, choices) == {"Q1": fixed, "Q2": alone}
    assert carried_analyses(told, other) == {}


def test_a_check_remembers_the_choice_of_the_questions_its_fixes_name():
    verdict = Analysis("conflict", "P1", depends_on=("Q2",),
                       fixes=(Fix("Q3", "Решите Q3 раньше."), Fix("Q1", "Уберите «и в облако».")))
    found = analysis_of_question(question(1), verdict,
                                 {"Q1": "Q1: P1", "Q2": "Q2: P2", "Q3": "Q3: -"})
    assert found.context == ["Q2: P2", "Q3: -"]                 # свой вопрос — не в счёт


def test_an_outcome_on_a_project_decision_no_longer_chosen_or_active_is_not_kept():
    """Отметку с решения проекта сняли или оно больше не действует — итог, который на него
    опирался, собирают заново: его решения потока те же, но опора уже не та."""
    decisions = [Decision(question_id="Q1", proposal="P1", rationale="Так.", rationale_by="human")]
    ready = Outcome(id="O1", title="Поиск", behavior="Ищет.", adr_ids=["ADR-1"],
                    adr_notes={"ADR-1": "Ищет по слову."}, acceptance_criteria=["Находит."],
                    project_decision_ids=["ADR-0007"])
    earlier = OutcomeDiscovery(state="done", steps=[], decisions=["Q1: P1: Так."], outcomes=[ready])
    chosen = ProjectDecision(adr_id="ADR-0007", decision="Искать полнотекстом.")
    stream = Stream(group="C", scope=[question(1)], decisions=decisions,
                    earlier_outcomes=earlier, project_decisions=[chosen])
    assert [o.id for o in kept_outcomes(stream, stream.scope, decisions)] == ["O1"]
    unchosen = stream.model_copy(update={"project_decisions": []})
    assert kept_outcomes(unchosen, stream.scope, decisions) == []
    reviewed = stream.model_copy(update={"project_decisions": [
        chosen.model_copy(update={"status": "under_review"})]})
    assert kept_outcomes(reviewed, stream.scope, decisions) == []
