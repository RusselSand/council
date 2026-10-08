"""Анализ решения: проверка выбора человека, рекомендация для unresolved, ссылки только на своё."""

import pytest

from spec_council.decisions import Analysis, Context, analysis_of, as_prompt, judged_analysis
from spec_council.slicing import BadAnswer


def context(selected=None):
    return Context(constraints=frozenset({4}), risks=frozenset({5}),
                   questions=frozenset({"Q2"}), proposals=frozenset({"F3", "P1", "P2"}),
                   selected=selected)


CHOSEN, OPEN = context("P2"), context()


def checked(valid=True, conflicts=(), risks=(), depends=(), **extra):
    return {"status": "user_selected", "selected_proposal_id": "P2",
            "validation": {"valid": valid, "constraint_conflicts": list(conflicts),
                           "risk_ids": list(risks), "depends_on_question_ids": list(depends)},
            "summary": "Требует решённого Q2.",
            "adr_draft": {"decision": "Бот", "rationale": "Бот остаётся интерфейсом.",
                          "rationale_source": "ai_suggested"}, **extra}


def test_a_participant_checks_the_choice_with_its_links():
    found = analysis_of(checked(risks=["F5", "F4"], depends=["q2", "Q9"]), CHOSEN)
    assert found == Analysis("validated", "P2", (), (5,), ("Q2",), "Требует решённого Q2.",
                             "Бот остаётся интерфейсом.")
    assert analysis_of(checked(valid=False), CHOSEN).kind == "conflict"
    assert analysis_of(checked(conflicts=["F4", "F9"]), CHOSEN).conflicts == (4,)


def test_a_participant_recommends_one_of_the_options_or_nothing():
    pick = {"status": "unresolved", "recommendation": {"proposal_id": "p1", "reason": "дешевле"}}
    assert analysis_of(pick, OPEN) == Analysis("recommended", "P1", reason="дешевле")
    nothing = {"status": "unresolved", "recommendation": None, "reason": "зависит от Q2"}
    assert analysis_of(nothing, OPEN) == Analysis("none", None, reason="зависит от Q2")


@pytest.mark.parametrize(("answer", "where", "problem"), [
    (checked(), OPEN, "unresolved"),
    (checked(selected_proposal_id="P1"), CHOSEN, "проверен P1, а выбран P2"),
    ({"status": "unresolved", "recommendation": None}, CHOSEN, "выбран P2"),
    ({"status": "unresolved", "recommendation": {"proposal_id": "P7"}}, OPEN, "нет варианта"),
    ({"status": "maybe"}, OPEN, "status"),
])
def test_a_participant_answer_about_something_else_is_bad(answer, where, problem):
    with pytest.raises(BadAnswer, match=problem):
        analysis_of(answer, where)


def test_the_judge_validates_flags_a_conflict_recommends_or_holds_back():
    validated = judged_analysis({
        "status": "validated", "question_id": "Q1", "proposal_id": "P2",
        "validation": {"constraint_conflicts": [], "risk_ids": ["F5"],
                       "depends_on_question_ids": ["Q2"]},
        "rationale": {"text": "Бот — точка входа.", "source": "ai"}}, CHOSEN)
    assert validated == Analysis("validated", "P2", (), (5,), ("Q2",), "", "Бот — точка входа.")
    conflict = judged_analysis({"status": "conflict", "proposal_id": "P2", "reason": "против F4",
                                "validation": {"constraint_conflicts": ["F4"]},
                                "rationale": None}, CHOSEN)
    assert (conflict.kind, conflict.conflicts, conflict.reason, conflict.rationale) == (
        "conflict", (4,), "против F4", None)
    recommended = judged_analysis({"status": "recommended", "proposal_id": "F3", "reason": "F4",
                                   "rationale": {"text": "Укладывается в бюджет.",
                                                 "source": "ai"}}, OPEN)
    assert recommended == Analysis("recommended", "F3", reason="F4",
                                   rationale="Укладывается в бюджет.")
    held = judged_analysis({"status": "no_recommendation", "reason": "зависит от Q2"}, OPEN)
    assert held == Analysis("none", None, reason="зависит от Q2")


def test_a_problem_the_judge_names_is_a_conflict_whatever_the_status():
    found = judged_analysis({"status": "validated", "proposal_id": "P2",
                             "validation": {"constraint_conflicts": ["F4"]}}, CHOSEN)
    assert found.kind == "conflict"


@pytest.mark.parametrize(("answer", "where", "problem"), [
    ({"status": "validated", "proposal_id": "F3"}, CHOSEN, "проверен F3, а выбран P2"),
    ({"status": "recommended", "proposal_id": "P1"}, CHOSEN, "вместо проверки"),
    ({"status": "no_recommendation", "reason": "x"}, CHOSEN, "вместо проверки"),
    ({"status": "validated", "proposal_id": "P2"}, OPEN, "unresolved"),
    ({"status": "recommended", "proposal_id": "P9"}, OPEN, "нет варианта"),
    ({"status": "recommended", "proposal_id": "P1", "rationale": {"text": "x" * 2001}}, OPEN,
     "длиннее"),
    ({"status": "accepted"}, OPEN, "status"),
])
def test_a_judge_answer_out_of_form_is_bad(answer, where, problem):
    with pytest.raises(BadAnswer, match=problem):
        judged_analysis(answer, where)


def test_the_judge_sees_each_analysis_as_the_participants_were_asked_for_it():
    found = analysis_of(checked(risks=["F5"]), CHOSEN)
    assert as_prompt(found)["validation"] == {"valid": True, "constraint_conflicts": [],
                                              "risk_ids": ["F5"], "depends_on_question_ids": []}
    assert as_prompt(Analysis("recommended", "P1", reason="дешевле")) == {
        "status": "unresolved", "recommendation": {"proposal_id": "P1", "reason": "дешевле"}}
    assert as_prompt(Analysis("none", None, reason="мало данных"))["recommendation"] is None
