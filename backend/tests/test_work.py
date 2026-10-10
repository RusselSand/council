"""Работа, которая переносится через правку отбора: задачи — с номерами ADR по новому отбору."""

from spec_council.models import Decision, Issue, OpenQuestion, Stream
from spec_council.work import with_new_adrs


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
