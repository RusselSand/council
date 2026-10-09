"""Конвейер нарезки и разметки на поддельных моделях: кто что получает и когда нужен судья."""

import json
import re
from pathlib import Path

import pytest

from spec_council.figma import FigmaError, link_of
from spec_council.models import (
    Choice,
    Decision,
    LabeledFragment,
    OpenQuestion,
    Outcome,
    OutcomeDiscovery,
    OutcomeGap,
    Proposal,
    ProposalDiscovery,
    QuestionOptions,
    StepName,
    Stream,
    StreamIdea,
)
from spec_council.pipeline import (
    DecisionRun,
    DesignRun,
    GroupingRun,
    IdeaRun,
    IssueRun,
    ModelFailed,
    OutcomeRun,
    ProposalRun,
    QuestionRun,
    RepositoryRun,
    SlicingRun,
)
from spec_council.repository import Inventory, RepositoryError, Source
from tests.figma_fake import LINK, FakeFigma

TEXT = ("Хочу воркер для Codex CLI. Состояние держать в файлах, без базы. "
        "Главное — не потерять результат.")
PARTS = ["Хочу воркер для Codex CLI.", "Состояние держать в файлах, без базы.",
         "Главное — не потерять результат."]
STEPS = [name.value for name in StepName]


def sliced(*variants, reason=None):
    options = [{"fragments": v, "reason": reason} for v in variants]
    return {"number": len(variants), "options": options}


def labeled(*labels):
    return {"labels": [{"id": i, "options": [{"label": label, "reason": f"{label} {i}"}]}
                       for i, label in enumerate(labels, 1)]}


class FakeRunner:
    """Ответы по (шаг, модель); ответ-функция получает промпт — когда шаг зовут не раз.
    Исключение в ответах — модель упала."""

    def __init__(self, replies):
        self.replies = replies
        self.asked: dict[tuple[str, str], str] = {}
        self.keys: list[str] = []
        self.forgotten: list[str] = []
        self.identities: dict[str, str] = {}
        self.workspaces: dict[tuple[str, str], object] = {}

    def ask(self, model, prompt, key, workspace=None):
        step = next(s for s in STEPS if f"-{s}-{model}-" in key)
        self.asked[step, model] = prompt
        self.workspaces[step, model] = workspace
        self.keys.append(key)
        reply = self.replies[step, model]
        if callable(reply):
            reply = reply(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)

    def forget(self, keys):
        self.forgotten.extend(keys)

    def identity(self, model):
        return self.identities.get(model, model)


def names_models(prompt):
    """Судья видит имена моделей — словами, а не частью другого слова («solution»)."""
    return re.search(r"\b(sol|fable)\b", prompt) is not None


def run(replies, participants=("sol", "fable"), judge="fable"):
    runner, reports = FakeRunner(replies), []
    result = SlicingRun("c1", TEXT, list(participants), judge, runner, reports.append).run()
    return result, runner, reports


def steps(result):
    return {step.name.value: step.state for step in result.steps}


AGREED = {
    ("slice", "sol"): sliced(PARTS),
    ("slice", "fable"): sliced(PARTS),
    ("label", "sol"): labeled("idea", "proposal", "risk"),
    ("label", "fable"): labeled("idea", "proposal", "risk"),
}


def test_agreeing_council_needs_no_judge():
    result, runner, reports = run(AGREED)
    assert result.state == "done"
    assert [(f.id, f.text, f.label) for f in result.fragments] == [
        (1, PARTS[0], "idea"), (2, PARTS[1], "proposal"), (3, PARTS[2], "risk")]
    assert result.fragments[1].reason == "proposal 2"
    assert steps(result) == {"slice": "done", "slice_judge": "skipped", "label": "done",
                             "label_judge": "skipped"}
    assert TEXT in runner.asked["slice", "sol"]
    assert PARTS[1] in runner.asked["label", "fable"]
    assert sorted(runner.forgotten) == sorted(runner.keys)   # итог сохранён — лоток чистим
    assert reports[-1] == result and reports[0].state == "running"


def test_different_slicing_goes_to_the_judge_without_model_names():
    joined = [PARTS[0], " ".join(PARTS[1:])]
    replies = {**AGREED, ("slice", "fable"): sliced(joined, reason="одна мысль"),
               ("slice_judge", "fable"): {"status": "ok", "fragments": joined, "decisions": []},
               ("label", "sol"): labeled("idea", "proposal"),
               ("label", "fable"): labeled("idea", "proposal")}
    result, runner, _ = run(replies)
    assert [f.text for f in result.fragments] == joined
    judge_prompt = runner.asked["slice_judge", "fable"]
    assert "одна мысль" in judge_prompt and PARTS[2] in judge_prompt
    assert not names_models(judge_prompt)


def test_one_model_seeing_two_variants_is_a_dispute_too():
    joined = [PARTS[0], " ".join(PARTS[1:])]
    replies = {**AGREED, ("slice", "sol"): sliced(PARTS, joined, reason="граница спорная"),
               ("slice_judge", "fable"): {"status": "ok", "fragments": PARTS, "decisions": []}}
    result, _, _ = run(replies)
    assert steps(result)["slice_judge"] == "done"


def test_judge_inventing_a_boundary_fails_the_slicing():
    replies = {**AGREED, ("slice", "fable"): sliced([TEXT]),
               ("slice_judge", "fable"): {"status": "ok", "fragments": ["Хочу воркер", TEXT[12:]]}}
    result, runner, _ = run(replies)
    assert result.state == "failed"
    assert "не было ни в одном варианте" in result.error
    assert steps(result)["slice_judge"] == "failed"
    judge_key = next(k for k in runner.keys if "-slice_judge-" in k)
    # Негодный ответ — из лотка, чтобы повтор спросил заново.
    assert runner.forgotten == [judge_key]


def test_only_disputed_labels_go_to_the_judge():
    replies = {**AGREED, ("label", "fable"): labeled("idea", "constraint", "risk"),
               ("label_judge", "fable"): {"labels": [
                   {"id": 2, "label": "constraint", "reason": "уже задано"}]}}
    result, runner, _ = run(replies)
    assert [f.label for f in result.fragments] == ["idea", "constraint", "risk"]
    assert result.fragments[1].reason == "уже задано"
    judge_prompt = runner.asked["label_judge", "fable"]
    assert PARTS[1] in judge_prompt and PARTS[0] not in judge_prompt


def test_failed_participant_drops_out_and_the_rest_go_on():
    replies = {**AGREED, ("slice", "sol"): ModelFailed("нет входа в подписку")}
    result, _, _ = run(replies)
    assert result.state == "done"
    slice_step = result.steps[0]
    assert [(r.model, r.state, r.error) for r in slice_step.runs] == [
        ("sol", "failed", "нет входа в подписку"), ("fable", "done", None)]


def test_unreadable_answer_is_a_failed_run_and_leaves_the_outbox():
    replies = {**AGREED, ("slice", "sol"): "не знаю, как это нарезать"}
    result, runner, _ = run(replies)
    assert result.steps[0].runs[0].error == "негодный ответ: в ответе нет JSON"
    assert next(k for k in runner.keys if "-slice-sol-" in k) in runner.forgotten


def test_nobody_answering_fails_with_every_reason():
    replies = {("slice", "sol"): ModelFailed("лимит"),
               ("slice", "fable"): ModelFailed("CLI не запускается")}
    result, _, _ = run(replies)
    assert result.state == "failed"
    assert "sol: лимит" in result.error and "fable: CLI не запускается" in result.error
    assert result.fragments == []


def test_same_text_gives_the_same_keys_so_a_retry_is_free():
    _, first, _ = run(AGREED)
    _, second, _ = run(AGREED)
    assert first.keys and sorted(first.keys) == sorted(second.keys)


@pytest.mark.parametrize("judge", ["astra", "sol"])
def test_judge_may_be_outside_the_council(judge):
    joined = [PARTS[0], " ".join(PARTS[1:])]
    replies = {**AGREED, ("slice", "fable"): sliced(joined),
               ("slice_judge", judge): {"status": "ok", "fragments": PARTS}}
    result, runner, _ = run(replies, judge=judge)
    assert result.state == "done" and ("slice_judge", judge) in runner.asked


def test_result_keeps_the_votes_who_decided_and_the_slicing_judges_note():
    joined = [PARTS[0], " ".join(PARTS[1:])]
    replies = {**AGREED, ("slice", "fable"): sliced(joined),
               ("slice_judge", "fable"): {"status": "ok", "fragments": PARTS, "decisions": [
                   {"boundary": "без базы. | Главное", "decision": "split",
                    "reason": "две мысли"}]},
               ("label", "fable"): labeled("idea", "constraint", "risk"),
               ("label_judge", "fable"): {"labels": [
                   {"id": 2, "label": "constraint", "reason": "уже задано"}]}}
    result, _, _ = run(replies)
    first, second, third = result.fragments
    assert result.text == TEXT
    assert (first.decided_by, second.decided_by) == ("agreed", "judge")
    votes = [(v.model, v.labels) for v in second.votes]
    assert votes == [("sol", ["proposal"]), ("fable", ["constraint"])]
    assert second.council_label == second.label == "constraint"
    assert (first.slice_note, third.slice_note) == (None, "две мысли")


def test_judge_with_malformed_decisions_still_gives_a_result():
    replies = {**AGREED, ("slice", "fable"): sliced([TEXT]),
               ("slice_judge", "fable"): {"status": "ok", "fragments": PARTS, "decisions": 1}}
    result, _, _ = run(replies)
    assert result.state == "done"
    assert all(f.slice_note is None for f in result.fragments)


def test_any_parse_crash_is_a_bad_answer_that_leaves_the_outbox(monkeypatch):
    def broken(text, data):
        raise TypeError("недосмотр разбора")
    monkeypatch.setattr("spec_council.pipeline.slice_options", broken)
    replies = {**AGREED}
    result, runner, _ = run(replies)
    assert result.state == "failed"
    assert result.steps[0].runs[0].error == "негодный ответ: недосмотр разбора"
    assert sorted(runner.forgotten) == sorted(k for k in runner.keys if "-slice-" in k)


def test_shuffle_depends_on_the_variants_not_on_who_sent_them_first():
    from spec_council.pipeline import shuffled
    variants = [{"fragments": [str(i)]} for i in range(6)]
    assert shuffled(variants) == shuffled(list(reversed(variants)))
    assert sorted(map(str, shuffled(variants))) == sorted(map(str, variants))


def test_judge_refusing_every_option_makes_a_retry_ask_the_participants_again():
    replies = {**AGREED, ("slice", "fable"): sliced([TEXT]),
               ("slice_judge", "fable"): {"status": "no_valid_option",
                                          "problem": "обе теряют текст"}}
    result, runner, _ = run(replies)
    assert result.state == "failed"
    assert "не принял ни один вариант: обе теряют текст" in result.error
    assert "негодный ответ" not in result.steps[1].runs[0].error   # ответ честный, не мусор
    # Кандидаты из лотка — повтор спросит участников; и отказ судьи тоже: он был про них.
    assert sorted(runner.forgotten) == sorted(k for k in runner.keys if "-slice" in k)


def test_another_model_behind_an_alias_is_a_new_call_not_a_free_retry():
    _, before, _ = run(AGREED)
    runner = FakeRunner(AGREED)
    runner.identities = {"sol": "codex/gpt-5.7-sol"}
    SlicingRun("c1", TEXT, ["sol", "fable"], "fable", runner, lambda _: None).run()
    sol_keys = lambda r: sorted(k for k in r.keys if "-sol-" in k)          # noqa: E731
    fable_keys = lambda r: sorted(k for k in r.keys if "-fable-" in k)      # noqa: E731
    assert set(sol_keys(before)).isdisjoint(sol_keys(runner))
    assert fable_keys(before) == fable_keys(runner)



# --- группы

def grouping(*groups, relations=()):
    return {"groups": list(groups), "relations": list(relations), "reason": None}


def grp(gid, fragments, ideas=(), shared=(), title=None):
    return {"id": gid, "title": title or f"Группа {gid}", "idea_fragment_ids": list(ideas),
            "fragment_ids": list(fragments), "missing_idea": not ideas,
            "shared_fragment_ids": list(shared)}


def sliced_result():
    result, _, _ = run(AGREED)          # фрагменты 1-3: idea, proposal, risk
    result.fragments[2].label = "constraint"   # человек поправил тип
    return result


def group_it(replies, participants=("sol", "fable"), judge="fable"):
    runner, reports = FakeRunner(replies), []
    result = GroupingRun("c1", sliced_result(), list(participants), judge, runner,
                         reports.append).run()
    return result, runner, reports


# Судья у раскладки своя пара шагов: structure, structure_judge.
ONE = grouping(grp("A", [1, 2], ideas=[1], title="Воркер"), grp("B", [3], title="Хранение"))


def test_agreeing_groupings_need_no_judge_and_come_out_lettered_by_first_fragment():
    renamed = grouping(grp("Z", [3]), grp("Y", [1, 2], ideas=[1]))
    result, runner, _ = group_it({("structure", "sol"): {"options": [ONE]},
                                  ("structure", "fable"): {"options": [renamed]}})
    assert result.state == "done"
    assert [(g.id, g.title, g.fragment_ids, g.missing_idea) for g in result.groups] == [
        ("A", "Воркер", [1, 2], False), ("B", "Хранение", [3], True)]
    assert {s.name.value: s.state for s in result.steps}["structure_judge"] == "skipped"
    prompt = runner.asked["structure", "sol"]
    assert '"type": "constraint"' in prompt                  # тип с правкой человека
    assert result.labels == {1: "idea", 2: "proposal", 3: "constraint"}
    assert sorted(runner.forgotten) == sorted(runner.keys)


def test_different_groupings_go_to_the_judge_and_shared_fragments_are_marked():
    merged = grouping(grp("A", [1, 2, 3], ideas=[1]))
    judged = {"status": "ok", **grouping(grp("A", [1, 2, 3], ideas=[1]), grp("B", [3], shared=[3]),
                                         relations=[{"from": "B", "to": "A", "type": "related",
                                                     "reason": "пишет туда же"}]),
              "decisions": [{"issue": "F3: A или A+B", "decision": "A+B",
                             "reason": "касается обеих"}]}
    candidate = grouping(grp("A", [1, 2, 3], ideas=[1]), grp("B", [3], shared=[3]),
                         relations=[{"from": "B", "to": "A", "type": "related",
                                     "reason": "туда же"}])
    result, runner, _ = group_it({("structure", "sol"): {"options": [merged]},
                                  ("structure", "fable"): {"options": [candidate]},
                                  ("structure_judge", "fable"): judged})
    assert [(g.id, g.fragment_ids, g.shared_fragment_ids) for g in result.groups] == [
        ("A", [1, 2, 3], [3]), ("B", [3], [3])]
    assert [(r.source, r.target, r.type) for r in result.relations] == [("B", "A", "related")]
    assert result.decisions[0].decision == "A+B"
    prompt = runner.asked["structure_judge", "fable"]
    assert not names_models(prompt)


def test_structure_judge_refusal_makes_a_retry_ask_the_participants_again():
    result, runner, _ = group_it({
        ("structure", "sol"): {"options": [ONE]},
        ("structure", "fable"): {"options": [grouping(grp("A", [1, 2, 3], ideas=[1]))]},
        ("structure_judge", "fable"): {"status": "no_valid_option", "problem": "обе теряют смысл"}})
    assert result.state == "failed" and "обе теряют смысл" in result.error
    assert sorted(runner.forgotten) == sorted(k for k in runner.keys if "-structure" in k)


# --- идея потока

GROUP_FRAGMENTS = [
    LabeledFragment(id=2, text="Полнотекстовый поиск по базе.", label="proposal", reason="",
                    council_label="proposal"),
    LabeledFragment(id=3, text="Или бот в Slack.", label="proposal", reason="",
                    council_label="proposal"),
    LabeledFragment(id=5, text="Бюджет — до $200.", label="constraint", reason="",
                    council_label="constraint"),
]
FIND = "Команда сама находит ответы в базе знаний"


def ideas(*options, reason=None):
    return {"number": len(options), "options": [
        {"idea": idea, "evidence": evidence, "reason": f"почему: {idea}"}
        for idea, evidence in options], **({"reason": reason} if reason else {})}


def seek(replies, participants=("sol", "fable"), judge="fable"):
    runner, reports = FakeRunner(replies), []
    result = IdeaRun("c1", GROUP_FRAGMENTS, list(participants), judge, runner,
                     reports.append).run()
    return result, runner


def test_one_idea_from_everyone_needs_no_judge():
    result, runner = seek({("idea_discovery", "sol"): ideas((FIND, ["F2", "F3"])),
                           ("idea_discovery", "fable"): ideas((FIND + ".", ["F3"]))})
    assert result.state == "done"
    assert [(o.idea, o.evidence, o.models) for o in result.options] == [
        (FIND, [2, 3], ["sol", "fable"])]
    assert (result.proposal.idea, result.proposal.decided_by, result.proposal.option) == (
        FIND, "agreed", 0)
    assert {s.name.value: s.state for s in result.steps}["idea_judge"] == "skipped"
    prompt = runner.asked["idea_discovery", "sol"]
    assert '"id": "F5"' in prompt and '"type": "constraint"' in prompt
    assert sorted(runner.forgotten) == sorted(runner.keys)


def test_different_ideas_go_to_the_judge_without_model_names():
    other = "Ответы на вопросы приходят без #help"
    result, runner = seek({
        ("idea_discovery", "sol"): ideas((FIND, ["F2"])),
        ("idea_discovery", "fable"): ideas((other, ["F3"])),
        ("idea_judge", "fable"): {"status": "ok", "idea": other, "evidence": ["F2", "F3"],
                                  "reason": "шире"}})
    assert (result.proposal.idea, result.proposal.evidence, result.proposal.decided_by) == (
        other, [2, 3], "judge")
    assert result.options[result.proposal.option].idea == other
    prompt = runner.asked["idea_judge", "fable"]
    assert FIND in prompt and other in prompt
    assert not names_models(prompt)


def test_judge_may_merge_wordings_and_may_reject_them_all():
    two = {("idea_discovery", "sol"): ideas((FIND, ["F2"])),
           ("idea_discovery", "fable"): ideas(("Другое", ["F3"]))}
    result, _ = seek({**two, ("idea_judge", "fable"): {
        "status": "ok", "idea": "Сводная", "evidence": ["F2"], "reason": "из обеих"}})
    assert (result.proposal.idea, result.proposal.option) == ("Сводная", None)

    result, runner = seek({**two, ("idea_judge", "fable"): {
        "status": "no_valid_option", "reason": "обе додумывают цель"}})
    assert result.state == "done"   # варианты остаются человеку
    assert (result.proposal.idea, result.proposal.reason) == (None, "обе додумывают цель")
    assert len(result.options) == 2
    assert sorted(runner.forgotten) == sorted(runner.keys)


def test_nobody_restoring_the_idea_leaves_it_to_the_person():
    result, _ = seek({("idea_discovery", "sol"): ideas(reason="одни ограничения"),
                      ("idea_discovery", "fable"): ideas(reason="цели нет")})
    assert result.state == "done" and result.options == []
    assert (result.proposal.idea, result.proposal.reason) == (None, "одни ограничения; цели нет")
    assert {s.name.value: s.state for s in result.steps}["idea_judge"] == "skipped"


def test_judge_leaning_on_a_fragment_outside_the_group_fails_the_search():
    result, runner = seek({
        ("idea_discovery", "sol"): ideas((FIND, ["F2"])),
        ("idea_discovery", "fable"): ideas(("Другое", ["F3"])),
        ("idea_judge", "fable"): {"status": "ok", "idea": FIND, "evidence": ["F1"]}})
    assert result.state == "failed"
    assert "F1 нет в группе" in result.steps[1].runs[0].error
    assert runner.forgotten == [k for k in runner.keys if "-idea_judge-" in k]


# --- вопросы потока

QUESTION_FRAGMENTS = [*GROUP_FRAGMENTS,
                      LabeledFragment(id=6, text="Кто платит за хостинг?", label="question",
                                      reason="", council_label="question")]
HOW = "Как должен выполняться поиск?"


def asked(*questions):
    return {"questions": [{"text": text, "source": source, "source_question_id": question,
                           "proposal_ids": proposals, "reason": f"почему: {text}"}
                          for text, source, question, proposals in questions]}


def question_it(replies):
    runner = FakeRunner(replies)
    result = QuestionRun("c1", FIND, QUESTION_FRAGMENTS, ["sol", "fable"], "fable", runner,
                         lambda _: None).run()
    return result, runner


def test_same_questions_from_everyone_need_no_judge_and_text_questions_stay_word_for_word():
    same = asked((HOW, "inferred", None, ["F2", "F3"]), ("Кто платит?", "user", "F6", []))
    result, runner = question_it({("question_discovery", "sol"): same,
                                  ("question_discovery", "fable"): same})
    assert result.state == "done"
    assert [(q.id, q.text, q.source, q.proposal_ids) for q in result.questions] == [
        ("Q1", HOW, "inferred", [2, 3]), ("Q2", "Кто платит за хостинг?", "user", [])]
    assert {s.name.value: s.state for s in result.steps}["question_judge"] == "skipped"
    prompt = runner.asked["question_discovery", "sol"]
    assert FIND in prompt and '"id": "F6"' in prompt
    assert result.idea == FIND


def test_different_lists_go_to_the_judge_and_a_dropped_text_question_comes_back():
    result, runner = question_it({
        ("question_discovery", "sol"): asked((HOW, "inferred", None, ["F2", "F3"])),
        ("question_discovery", "fable"): asked(("Где искать?", "inferred", None, ["F2"]),
                                               ("Кто платит?", "user", "F6", [])),
        ("question_judge", "fable"): asked(("Где человек ищет ответ?", "inferred", None,
                                            ["F2", "F3"]))})
    assert [(q.id, q.text, q.source) for q in result.questions] == [
        ("Q1", "Где человек ищет ответ?", "inferred"), ("Q2", "Кто платит за хостинг?", "user")]
    prompt = runner.asked["question_judge", "fable"]
    assert HOW in prompt and "Где искать?" in prompt
    assert not names_models(prompt)


def test_a_judge_answer_without_a_list_fails_the_search():
    result, _ = question_it({
        ("question_discovery", "sol"): asked((HOW, "inferred", None, ["F2"])),
        ("question_discovery", "fable"): asked(("Где искать?", "discovered", None, [])),
        ("question_judge", "fable"): {"status": "ok"}})
    assert result.state == "failed"
    assert "questions" in result.steps[1].runs[0].error


# --- варианты потока

SEARCH = OpenQuestion(id="Q1", text="Как должен выполняться поиск?", source="inferred",
                      proposal_ids=[2, 3])
WHERE = OpenQuestion(id="Q2", text="Где живёт база?", source="discovered")
HYBRID = "Гибрид: полнотекстовый отбор и переранжирование"


def offered(*texts, constraints=(), depends=()):
    return {"proposals": [{"text": text, "reason": f"почему: {text}",
                           "constraint_ids": list(constraints),
                           "depends_on_question_ids": list(depends)} for text in texts]}


def by_question(on_search, on_where):
    """Ответ модели — по тому, о каком вопросе её спросили: по номеру вопроса верхнего уровня.
    Текст не годится: другие вопросы потока тоже в промпте, в other_open_questions."""
    top = f'\n  "id": "{SEARCH.id}"'   # отступ верхнего уровня: вложенные — глубже
    return lambda prompt: on_search if top in prompt else on_where


def propose(replies, scope=(SEARCH, WHERE)):
    runner, reports = FakeRunner(replies), []
    result = ProposalRun("c1", FIND, list(scope), GROUP_FRAGMENTS, ["sol", "fable"], "fable",
                         runner, reports.append).run()
    return result, runner, reports


def test_each_question_gets_new_proposals_and_numbers_run_through_the_stream():
    judge = by_question({"status": "recommended", "proposal": offered(HYBRID, constraints=["F5"])
                         ["proposals"][0]},
                        {"status": "alternatives", "reason": "зависит от бюджета",
                         "proposals": offered("Notion", "Своя база", depends=["Q1"])["proposals"]})
    discovery = by_question(offered(HYBRID, constraints=["F5", "F9"]),
                            offered("Notion", "Своя база", depends=["Q1"]))
    result, runner, reports = propose({("proposal_discovery", "sol"): discovery,
                                       ("proposal_discovery", "fable"): discovery,
                                       ("proposal_judge", "fable"): judge})
    assert result.state == "done"
    first, second = result.options
    assert [(p.id, p.text, p.recommended, p.constraint_ids) for p in first.proposals] == [
        ("P1", HYBRID, True, [5])]
    assert (second.verdict, second.reason) == ("alternatives", "зависит от бюджета")
    assert [(p.id, p.depends_on) for p in second.proposals] == [("P2", ["Q1"]), ("P3", ["Q1"])]
    # Готовый вопрос виден до конца поиска.
    assert any(len(r.options) == 1 and r.state == "running" for r in reports)
    prompt = runner.asked["proposal_discovery", "sol"]      # последний — про Q2
    assert WHERE.text in prompt and '"type": "constraint"' in prompt
    judge_prompt = runner.asked["proposal_judge", "fable"]
    assert '"sol"' not in judge_prompt and '"fable"' not in judge_prompt   # «unresolved» — не имя


def test_existing_proposals_go_into_the_prompt_and_no_new_ones_need_no_judge():
    nothing = offered()
    result, runner, _ = propose({("proposal_discovery", "sol"): nothing,
                                 ("proposal_discovery", "fable"): nothing}, scope=[SEARCH])
    assert [(o.question_id, o.verdict, o.proposals) for o in result.options] == [("Q1", "none", [])]
    assert {s.name.value: s.state for s in result.steps}["proposal_judge"] == "skipped"
    prompt = runner.asked["proposal_discovery", "sol"]
    assert '"id": "F2"' in prompt and "Или бот в Slack." in prompt


def test_a_question_nobody_could_answer_fails_the_search_and_keeps_what_was_found():
    discovery = by_question(offered(HYBRID), ModelFailed("лимит"))
    recommended = {"status": "recommended", "proposal": offered(HYBRID)["proposals"][0]}
    result, _, _ = propose({("proposal_discovery", "sol"): discovery,
                            ("proposal_discovery", "fable"): discovery,
                            ("proposal_judge", "fable"): recommended})
    assert result.state == "failed"
    assert [o.question_id for o in result.options] == ["Q1"]


def test_a_repeat_of_a_group_proposal_is_not_a_new_option():
    # F3 «Или бот в Slack.» — участник повторил его иначе написанным, судья его же рекомендовал.
    repeat = "ИЛИ БОТ В SLACK"
    discovery = offered(HYBRID, repeat)
    judge = {"status": "recommended", "proposal": offered("или бот в  slack!")["proposals"][0]}
    result, runner, _ = propose({("proposal_discovery", "sol"): discovery,
                                 ("proposal_discovery", "fable"): discovery,
                                 ("proposal_judge", "fable"): judge}, scope=[SEARCH])
    [found] = result.options
    assert (found.verdict, found.proposals) == ("none", [])
    assert "F3" in found.reason
    assert repeat not in runner.asked["proposal_judge", "fable"]   # судье — только новое

    only_repeats = offered(repeat)
    result, _, _ = propose({("proposal_discovery", "sol"): only_repeats,
                            ("proposal_discovery", "fable"): only_repeats}, scope=[SEARCH])
    assert result.options[0].verdict == "none"
    assert {s.name.value: s.state for s in result.steps}["proposal_judge"] == "skipped"


def test_the_other_questions_of_the_scope_are_in_both_prompts():
    discovery = by_question(offered(HYBRID), offered("Notion"))
    judge = {"status": "recommended", "proposal": offered(HYBRID)["proposals"][0]}
    _, runner, _ = propose({("proposal_discovery", "sol"): discovery,
                            ("proposal_discovery", "fable"): discovery,
                            ("proposal_judge", "fable"): judge})
    for step in ("proposal_discovery", "proposal_judge"):
        prompt = runner.asked[step, "fable"]                     # последний — про Q2
        assert '"id": "Q1"' in prompt and SEARCH.text in prompt  # Q1 — среди других вопросов


def test_a_model_that_failed_on_one_question_stays_failed_after_the_next():
    sol = by_question(ModelFailed("лимит"), offered("Своя база"))
    fable = by_question(offered(HYBRID), offered("Notion"))
    judge = by_question({"status": "recommended", "proposal": offered(HYBRID)["proposals"][0]},
                        {"status": "alternatives", "reason": "по бюджету",
                         "proposals": offered("Своя база", "Notion")["proposals"]})
    result, _, _ = propose({("proposal_discovery", "sol"): sol,
                            ("proposal_discovery", "fable"): fable,
                            ("proposal_judge", "fable"): judge})
    assert result.state == "done"
    runs = {run.model: (run.state, run.error) for run in result.steps[0].runs}
    assert runs == {"sol": ("failed", "Q1: лимит"), "fable": ("done", None)}


# --- проверка выбора

FOUND = ProposalDiscovery(state="done", run="p1", steps=[], options=[
    QuestionOptions(question_id="Q1", verdict="recommended",
                    proposals=[Proposal(id="P1", text=HYBRID, reason="точно", constraint_ids=[5])]),
    QuestionOptions(question_id="Q2", verdict="recommended",
                    proposals=[Proposal(id="P2", text="Notion", reason="уже есть")])])


def checked_by(proposal, depends=(), valid=True):
    return {"status": "user_selected", "selected_proposal_id": proposal,
            "validation": {"valid": valid, "constraint_conflicts": [], "risk_ids": [],
                           "depends_on_question_ids": list(depends)},
            "summary": "Противоречий нет.",
            "adr_draft": {"rationale": "Точный поиск без новой базы.",
                          "rationale_source": "ai_suggested"}}


def recommends(proposal, reason="дешевле"):
    return {"status": "unresolved", "recommendation": {"proposal_id": proposal, "reason": reason}}


def section(prompt, title):
    """Раздел промпта под заголовком «## title» — до следующего заголовка."""
    return prompt.split(f"## {title}\n")[1].split("\n## ")[0].strip()


def check(replies, choices=(("Q1", "P1"), ("Q2", None)), scope=(SEARCH, WHERE), found=FOUND):
    runner, reports = FakeRunner(replies), []
    result = DecisionRun("c1", FIND, list(scope),
                         [Choice(question_id=q, proposal=p) for q, p in choices], found,
                         GROUP_FRAGMENTS, ["sol", "fable"], "fable", runner, reports.append).run()
    return result, runner, reports


def test_a_choice_is_checked_and_an_unresolved_question_gets_a_recommendation():
    analysis = by_question(checked_by("P1", depends=["Q2"]), recommends("P2"))
    judge = by_question(
        {"status": "validated", "proposal_id": "P1",
         "validation": {"constraint_conflicts": [], "risk_ids": [],
                        "depends_on_question_ids": ["Q2"]},
         "rationale": {"text": "Точный поиск без новой базы.", "source": "ai"}},
        {"status": "recommended", "proposal_id": "P2", "reason": "уже есть у команды",
         "rationale": {"text": "Ничего не разворачивать.", "source": "ai"}})
    result, runner, reports = check({("decision_analysis", "sol"): analysis,
                                     ("decision_analysis", "fable"): analysis,
                                     ("decision_judge", "fable"): judge})
    assert result.state == "done"
    assert [(a.question_id, a.verdict, a.proposal, a.depends_on, a.reason, a.rationale)
            for a in result.analyses] == [
        ("Q1", "validated", "P1", ["Q2"], None, "Точный поиск без новой базы."),
        ("Q2", "recommended", "P2", [], "уже есть у команды", "Ничего не разворачивать.")]
    assert result.choices == ["Q1: P1", "Q2: -"]
    assert any(len(r.analyses) == 1 and r.state == "running" for r in reports)
    prompt = runner.asked["decision_analysis", "sol"]           # последний — про Q2
    assert "Notion" in section(prompt, "PROPOSALS")
    assert section(prompt, "USER SELECTION") == "null"                  # Q2 — unresolved
    related = section(prompt, "RELATED QUESTIONS")
    assert '"status": "selected"' in related and HYBRID in related   # по Q1 выбран P1
    judge_prompt = runner.asked["decision_judge", "fable"]
    assert '"sol"' not in judge_prompt and '"fable"' not in judge_prompt
    assert '"recommendation"' in judge_prompt


def test_the_options_of_a_question_are_its_group_proposals_and_what_the_council_found():
    analysis = checked_by("P1")
    judge = {"status": "validated", "proposal_id": "P1", "validation": {}}
    _, runner, _ = check({("decision_analysis", "sol"): analysis,
                          ("decision_analysis", "fable"): analysis,
                          ("decision_judge", "fable"): judge}, choices=[("Q1", "P1")],
                         scope=[SEARCH])
    prompt = runner.asked["decision_analysis", "sol"]
    options = section(prompt, "PROPOSALS")
    assert '"id": "F2"' in options and '"id": "F3"' in options and HYBRID in options
    assert '"proposal_id": "P1"' in section(prompt, "USER SELECTION")
    # Одинаковые анализы судья видит одним.
    analyses = section(runner.asked["decision_judge", "fable"], "INDEPENDENT DECISION ANALYSES")
    assert '"analysis": 1' in analyses and '"analysis": 2' not in analyses


def test_an_unresolved_question_without_options_goes_to_nobody():
    result, runner, _ = check({}, choices=[("Q2", None)], scope=[WHERE], found=None)
    assert result.state == "done"
    assert [(a.question_id, a.verdict, a.proposal) for a in result.analyses] == [
        ("Q2", "none", None)]
    assert runner.keys == []
    assert {s.name.value: s.state for s in result.steps} == {
        "decision_analysis": "skipped", "decision_judge": "skipped"}


def test_a_judge_that_checks_another_option_fails_the_check():
    analysis = checked_by("P1")
    result, _, _ = check({("decision_analysis", "sol"): analysis,
                          ("decision_analysis", "fable"): analysis,
                          ("decision_judge", "fable"): {"status": "validated",
                                                        "proposal_id": "F2"}},
                         choices=[("Q1", "P1")], scope=[SEARCH])
    assert result.state == "failed"
    assert "проверен F2, а выбран P1" in result.error


def test_a_model_that_failed_one_check_stays_failed_after_the_next():
    sol = by_question(ModelFailed("лимит"), recommends("P2"))
    fable = by_question(checked_by("P1"), recommends("P2"))
    judge = by_question({"status": "validated", "proposal_id": "P1"},
                        {"status": "no_recommendation", "reason": "мало данных"})
    result, _, _ = check({("decision_analysis", "sol"): sol,
                          ("decision_analysis", "fable"): fable,
                          ("decision_judge", "fable"): judge})
    assert result.state == "done"
    assert result.analyses[1].verdict == "none"
    runs = {run.model: (run.state, run.error) for run in result.steps[0].runs}
    assert runs == {"sol": ("failed", "Q1: лимит"), "fable": ("done", None)}


# --- итоги потока

DECIDED = [Decision(question_id="Q1", proposal="F2", rationale="Уже есть в тексте.",
                    rationale_by="human"), Decision(question_id="Q2")]


def result_of(title, adrs=(), blocked=(), criteria=("Видно сразу.",)):
    return {"title": title, "behavior": f"{title}: так работает.", "adr_ids": list(adrs),
            "constraint_ids": ["F5"], "risk_ids": [], "acceptance_criteria": list(criteria),
            "blocked_by": list(blocked), "gaps": []}


def assemble(replies, decisions=DECIDED):
    runner, reports = FakeRunner(replies), []
    result = OutcomeRun("c1", FIND, [SEARCH, WHERE], decisions, FOUND, GROUP_FRAGMENTS,
                        ["sol", "fable"], "fable", runner, reports.append).run()
    return result, runner


def test_outcomes_stand_on_the_decisions_and_an_open_question_blocks():
    judge = {"outcomes": [result_of("Поиск по базе", adrs=["ADR-1"]),
                          result_of("Хранение базы", adrs=["ADR-2"], blocked=["Q2", "Q1"])],
             "coverage": {"covered_adr_ids": ["ADR-1"], "uncovered_adr_ids": []}}
    result, runner = assemble({
        ("outcome_discovery", "sol"): {"outcomes": [result_of("Поиск", adrs=["ADR-1"])]},
        ("outcome_discovery", "fable"): {"outcomes": [result_of("Хранение", blocked=["Q2"])]},
        ("outcome_judge", "fable"): judge})
    assert result.state == "done"
    found = [(o.id, o.title, o.adr_ids, o.blocked_by, o.constraint_ids) for o in result.outcomes]
    assert found == [("O1", "Поиск по базе", ["ADR-1"], [], [5]),
                     ("O2", "Хранение базы", [], ["Q2"], [5])]
    assert result.uncovered_adr_ids == []
    assert result.decisions == ["Q1: F2: Уже есть в тексте.", "Q2: -: "]
    prompt = runner.asked["outcome_discovery", "sol"]
    adrs = section(prompt, "ACCEPTED ADRS")
    assert '"id": "ADR-1"' in adrs and "Полнотекстовый поиск по базе." in adrs
    assert "Уже есть в тексте." in adrs and "ADR-2" not in adrs        # Q2 открыт — решения нет
    questions = section(prompt, "OPEN QUESTIONS AND PROPOSALS")
    assert '"status": "open"' in questions and HYBRID in questions
    judge_prompt = runner.asked["outcome_judge", "fable"]
    assert "Поиск" in section(judge_prompt, "INDEPENDENT OUTCOME CANDIDATES")
    assert '"sol"' not in judge_prompt and '"fable"' not in judge_prompt


def test_the_same_sets_need_no_judge_and_an_uncovered_decision_is_named():
    same = {"outcomes": [result_of("Поиск", blocked=["Q2"])]}
    result, runner = assemble({("outcome_discovery", "sol"): same,
                               ("outcome_discovery", "fable"): same})
    assert {s.name.value: s.state for s in result.steps}["outcome_judge"] == "skipped"
    assert [o.blocked_by for o in result.outcomes] == [["Q2"]]
    assert result.uncovered_adr_ids == ["ADR-1"]
    assert sorted(runner.forgotten) == sorted(runner.keys)


def test_a_judge_answer_without_a_list_fails_the_assembly():
    result, _ = assemble({("outcome_discovery", "sol"): {"outcomes": [result_of("Поиск")]},
                          ("outcome_discovery", "fable"): {"outcomes": []},
                          ("outcome_judge", "fable"): {"coverage": {}}})
    assert result.state == "failed"
    assert "outcomes" in result.error


def test_the_same_outcomes_in_another_order_need_no_judge():
    search, store = result_of("Поиск", blocked=["Q2"]), result_of("Хранение", criteria=("Б.", "А."))
    result, _ = assemble({
        ("outcome_discovery", "sol"): {"outcomes": [search, store]},
        ("outcome_discovery", "fable"): {"outcomes": [result_of("Хранение", criteria=("А.", "Б.")),
                                                      search]}})
    assert result.state == "done"
    assert {s.name.value: s.state for s in result.steps}["outcome_judge"] == "skipped"
    assert [o.title for o in result.outcomes] == ["Поиск", "Хранение"]


def test_a_gap_that_repeats_an_open_question_of_the_scope_blocks_by_it():
    gap = result_of("Хранение базы") | {"gaps": [{"question": "где живёт база", "reason": "нет"}]}
    result, _ = assemble({("outcome_discovery", "sol"): {"outcomes": [gap]},
                          ("outcome_discovery", "fable"): {"outcomes": [gap]}})
    [found] = result.outcomes
    assert (found.blocked_by, found.gaps) == (["Q2"], [])



# --- скан репозитория

FOUND_REPO = Inventory(root=Path("/repos/project"), commit_sha="abc123", dirty=False,
                       files=("api/deps.py", "api/routes.py"))
PROJECT = [Source("", "project", FOUND_REPO)]
# Бэкенд и фронтенд — в разных репозиториях: каждый в своей папке снимка.
TWO_REPOS = [Source("back", "back", FOUND_REPO),
             Source("front", "web/front", Inventory(root=Path("/repos/web/front"),
                                                    commit_sha="def456", dirty=True,
                                                    files=("src/App.tsx",)))]
FACT = {"id": "R1", "statement": "Контекст запроса — из зависимостей.", "status": "verified",
        "evidence": [{"path": "api/deps.py", "symbol": "get_context"}], "relevance": "вход"}
CHECK_PROXY = {"objective": "Проверить авторизацию в прокси", "targets": ["Caddyfile"]}


def copy_as(fingerprint):
    """Снимок без файлов: каталог настоящий, а отпечаток и состав — какие скажут."""
    return lambda sources, into: (fingerprint, frozenset(
        source.prefix + name for source in sources for name in source.found.files))


def scan(replies, copy=None, sources=PROJECT):
    runner, reports = FakeRunner(replies), []
    result = RepositoryRun("c1", FIND, sources, GROUP_FRAGMENTS, ["sol", "fable"],
                           "fable", runner, reports.append,
                           copy=copy or copy_as("снимок-1")).run()
    return result, runner, reports


def judge_until(rounds_needed):
    """Судья просит доисследовать, пока не увидит столько прежних находок."""
    def reply(prompt):
        earlier = section(prompt, "PREVIOUS FINDINGS")
        done = earlier != "[]" if rounds_needed == 2 else False
        return {"status": "complete" if done else "needs_investigation", "findings": [FACT],
                "follow_up": [] if done else [CHECK_PROXY]}
    return reply


def test_a_scan_reads_the_working_copy_and_follows_up_on_the_judges_gaps():
    found = {"findings": [FACT], "flows": [], "coverage": [], "unknowns": []}
    result, runner, reports = scan({("repository_discovery", "sol"): found,
                                    ("repository_discovery", "fable"): found,
                                    ("repository_judge", "fable"): judge_until(2)})
    assert result.state == "done"
    assert (result.rounds, result.complete, result.follow_up) == (2, True, [])
    assert [f.id for f in result.result.findings] == ["R1"]
    assert [(r.name, r.path, r.root, r.commit_sha, r.files) for r in result.repositories] == [
        ("", "project", str(FOUND_REPO.root), "abc123", 2)]
    # Второй проход участников — по заданиям судьи; судья видит прежнюю карту.
    assert "Проверить авторизацию в прокси" in section(
        runner.asked["repository_discovery", "sol"], "ADDITIONAL INVESTIGATION REQUESTS")
    assert "get_context" in section(runner.asked["repository_judge", "fable"], "PREVIOUS FINDINGS")
    assert "api/routes.py" in section(runner.asked["repository_discovery", "sol"],
                                      "REPOSITORY INVENTORY")
    # Модели — и участники, и судья — читают один снимок, а не саму рабочую копию; после скана
    # его нет.
    [place] = set(runner.workspaces.values())
    assert place != FOUND_REPO.root
    assert place.name.startswith("council-scan-")
    assert not place.exists()
    judge_prompt = runner.asked["repository_judge", "fable"]
    assert '"sol"' not in judge_prompt and '"fable"' not in judge_prompt
    assert any(r.rounds == 1 and r.state == "running" for r in reports)   # проход виден сразу


def test_after_three_rounds_the_scan_ends_with_what_it_has():
    found = {"findings": [FACT]}
    result, _, _ = scan({("repository_discovery", "sol"): found,
                         ("repository_discovery", "fable"): found,
                         ("repository_judge", "fable"): judge_until(None)})
    assert result.state == "done"
    assert (result.rounds, result.complete) == (3, False)
    assert [f.objective for f in result.follow_up] == ["Проверить авторизацию в прокси"]


def test_the_repository_map_reaches_the_next_steps():
    same = asked((HOW, "inferred", None, ["F2"]))
    _, runner = question_it_with({("question_discovery", "sol"): same,
                                  ("question_discovery", "fable"): same})
    assert section(runner.asked["question_discovery", "sol"], "REPOSITORY CONTEXT").endswith(
        "КАРТА РЕПОЗИТОРИЯ")
    assert runner.workspaces["question_discovery", "sol"] is None    # дальше код не читают
    same_set = {"outcomes": [result_of("Поиск")]}
    runner = FakeRunner({("outcome_discovery", "sol"): same_set,
                         ("outcome_discovery", "fable"): same_set})
    OutcomeRun("c1", FIND, [SEARCH, WHERE], DECIDED, FOUND, GROUP_FRAGMENTS, ["sol", "fable"],
               "fable", runner, lambda _: None, repository="КАРТА РЕПОЗИТОРИЯ").run()
    assert section(runner.asked["outcome_discovery", "sol"], "REPOSITORY CONTEXT").endswith(
        "КАРТА РЕПОЗИТОРИЯ")


def question_it_with(replies):
    runner = FakeRunner(replies)
    result = QuestionRun("c1", FIND, QUESTION_FRAGMENTS, ["sol", "fable"], "fable", runner,
                         lambda _: None, repository="r1",
                         repository_map="КАРТА РЕПОЗИТОРИЯ").run()
    return result, runner


def test_several_repositories_are_scanned_together_each_in_its_folder():
    """Бэкенд и фронтенд в разных репозиториях: модели видят оба, файлы — с папкой копии, и
    подтверждением годится файл любой из них."""
    front = {"id": "R2", "statement": "Экран — React.", "status": "verified",
             "evidence": [{"path": "front/src/App.tsx"}]}
    back = {**FACT, "evidence": [{"path": "back/api/deps.py"}]}
    found = {"findings": [back, front]}
    result, runner, _ = scan({("repository_discovery", "sol"): found,
                              ("repository_discovery", "fable"): found,
                              ("repository_judge", "fable"): {"status": "complete",
                                                              "findings": [back, front]}},
                             sources=TWO_REPOS)
    assert result.state == "done"
    assert [(r.name, r.path, r.commit_sha, r.dirty, r.files) for r in result.repositories] == [
        ("back", "back", "abc123", False, 2), ("front", "web/front", "def456", True, 1)]
    assert [(f.status, [e.path for e in f.evidence]) for f in result.result.findings] == [
        ("verified", ["back/api/deps.py"]), ("verified", ["front/src/App.tsx"])]
    prompt = runner.asked["repository_discovery", "sol"]
    inventory = section(prompt, "REPOSITORY INVENTORY")
    assert "back/ — back" in inventory and "front/ — web/front" in inventory
    assert "back/api/routes.py" in inventory and "front/src/App.tsx" in inventory
    commits = section(prompt, "COMMIT SHA")
    assert "back: abc123" in commits and "front: def456" in commits


def test_another_snapshot_is_a_new_call_not_a_free_retry():
    """Промпт тот же (коммит, inventory), а код в снимке другой — оплаченный ответ к прежнему
    коду не годится; тот же код — тот же ключ."""
    found = {"findings": [FACT]}
    replies = {("repository_discovery", "sol"): found, ("repository_discovery", "fable"): found,
               ("repository_judge", "fable"): {"status": "complete", "findings": [FACT]}}
    _, first, _ = scan(replies)
    _, same, _ = scan(replies)
    _, other, _ = scan(replies, copy=copy_as("снимок-2"))
    assert first.keys == same.keys
    assert set(first.keys).isdisjoint(other.keys)


def test_evidence_counts_only_files_that_made_it_into_the_snapshot():
    """Файл из inventory, который не скопировался (пропал, не читается), модели не видели."""
    replies = {("repository_discovery", "sol"): {"findings": [FACT]},
               ("repository_discovery", "fable"): {"findings": [FACT]},
               ("repository_judge", "fable"): {"status": "complete", "findings": [FACT]}}
    result, _, _ = scan(replies, copy=lambda found, into: ("снимок", frozenset({"api/routes.py"})))
    assert [(f.status, f.evidence) for f in result.result.findings] == [("inferred", [])]


# --- скан макета

SCREEN = {"id": "D1", "statement": "Экран тредов с поиском", "status": "verified",
          "evidence": [{"page_id": "1:0", "node_id": "2:1", "name": "Threads"}]}
CHECK_EMPTY = {"objective": "Проверить пустой результат поиска",
               "targets": [{"page_id": "1:0", "node_id": "2:3"}]}


def design(replies, fetch=None):
    runner, reports = FakeRunner(replies), []
    fetch = fetch or FakeFigma()
    result = DesignRun("c1", FIND, [link_of(LINK)], GROUP_FRAGMENTS, ["sol", "fable"], "fable",
                       runner, reports.append, fetch=fetch).run()
    return result, runner, reports


def design_judge_until(rounds_needed):
    def reply(prompt):
        done = section(prompt, "PREVIOUS FINDINGS") != "[]" if rounds_needed == 2 else False
        return {"status": "complete" if done else "needs_investigation", "findings": [SCREEN],
                "follow_up": [] if done else [CHECK_EMPTY]}
    return reply


def test_the_design_scan_reads_one_snapshot_of_the_figma_file_and_follows_up():
    found = {"findings": [SCREEN], "screens": [{"name": "Threads", "node_id": "2:1"}]}
    result, runner, reports = design({("design_discovery", "sol"): found,
                                      ("design_discovery", "fable"): found,
                                      ("design_judge", "fable"): design_judge_until(2)})
    assert result.state == "done"
    assert (result.rounds, result.complete, result.follow_up) == (2, True, [])
    assert [(f.id, f.status) for f in result.result.findings] == [("D1", "verified")]
    assert (result.source.name, result.source.version, result.source.images) == (
        "Billing", "v1", 2)
    assert result.links == [LINK]
    source = section(runner.asked["design_discovery", "sol"], "FIGMA SOURCE")
    assert "2:1 «Threads»" in source and "frames/2-1 Threads.png" in source
    assert "Проверить пустой результат поиска" in section(
        runner.asked["design_discovery", "sol"], "ADDITIONAL INVESTIGATION REQUESTS")
    # И участники, и судья читают один снимок; после скана его нет.
    [place] = set(runner.workspaces.values())
    assert place.name.startswith("council-design-")
    assert not place.exists()
    # Что легло в снимок, видно раньше, чем ответили модели.
    assert any(r.source is not None and r.rounds == 0 for r in reports)


def test_another_version_of_the_file_is_a_new_call_and_the_same_one_is_free():
    replies = {("design_discovery", "sol"): {"findings": [SCREEN]},
               ("design_discovery", "fable"): {"findings": [SCREEN]},
               ("design_judge", "fable"): {"status": "complete", "findings": [SCREEN]}}
    _, first, _ = design(replies)
    _, same, _ = design(replies)
    _, other, _ = design(replies, fetch=FakeFigma(version="v2"))
    assert first.keys == same.keys
    assert set(first.keys).isdisjoint(other.keys)


def test_a_figma_refusal_fails_the_scan_before_any_model_is_asked():
    result, runner, _ = design({}, fetch=FakeFigma(fail=FigmaError("Токен Figma не подходит")))
    assert result.state == "failed"
    assert "Токен Figma не подходит" in result.error
    assert runner.keys == [] and result.source is None


# --- нарезка на задачи

APPROVED = OutcomeDiscovery(state="done", run="o1", steps=[], outcomes=[
    Outcome(id="O1", title="Поиск по базе", behavior="Ответ находится поиском.",
            adr_ids=["ADR-1"], constraint_ids=[5], acceptance_criteria=["Находит по слову."]),
    Outcome(id="O2", title="Хранение базы", behavior="База где-то живёт.", blocked_by=["Q2"])])


def task(id_, title, outcomes=("O1",), **extra):
    return {"id": id_, "title": title,
            "user_story": f"As a member, I want {title}, so that I find answers.",
            "main_entry_points": ["api/deps.py"], "current_state": "Поиска нет.",
            "scope": [f"{title}: сделать."], "outcome_ids": list(outcomes), "adr_ids": ["ADR-1"],
            "constraint_ids": ["F5"], "risk_ids": [], "depends_on": [], "blocked_by": [],
            **extra}


def cut(replies, sources=PROJECT, copy=None, outcomes=APPROVED):
    runner, reports = FakeRunner(replies), []
    stream = Stream(group="A", idea=StreamIdea(text=FIND, by="human"), scope=[SEARCH, WHERE],
                    decisions=DECIDED, proposals=FOUND, outcomes=outcomes)
    result = IssueRun("c1", stream, GROUP_FRAGMENTS,
                      ["sol", "fable"], "fable", runner, reports.append, sources=sources,
                      repository="КАРТА РЕПОЗИТОРИЯ", copy=copy or copy_as("снимок-1")).run()
    return result, runner


def test_approved_outcomes_are_cut_into_numbered_issues_reading_the_code():
    judge = {"issues": [task("I7", "Индекс базы"),
                        task("I3", "Выдача ответа", depends_on=["I7"], blocked_by=["G1"])],
             "gaps": [{"question": "Сколько хранить историю?", "reason": "не решено",
                       "outcome_ids": ["O1"]}]}
    result, runner = cut({("issue_discovery", "sol"): {"issues": [task("I1", "Поиск")]},
                          ("issue_discovery", "fable"): {"issues": [task("I1", "Индекс")]},
                          ("issue_judge", "fable"): judge})
    assert result.state == "done"
    assert [(i.id, i.title, i.depends_on, i.blocked_by) for i in result.issues] == [
        ("I1", "Индекс базы", [], ["G1"]),            # пробел назван для O1 — держит и её
        ("I2", "Выдача ответа", ["I1"], ["G1"])]
    assert [(g.id, g.question) for g in result.gaps] == [("G1", "Сколько хранить историю?")]
    assert result.uncovered_outcome_ids == ["O2"]                  # считает код, не модель
    assert (result.outcomes, result.code) == ("o1", True)
    assert [(s.name, s.commit_sha) for s in result.sources] == [("", "abc123")]
    prompt = runner.asked["issue_discovery", "sol"]
    assert '"id": "O2"' in section(prompt, "OUTCOMES")
    # Открытый вопрос, держащий итог, виден текстом и с вариантами, а не одним номером.
    outcomes = section(prompt, "OUTCOMES")
    assert WHERE.text in outcomes and "Notion" in outcomes
    assert '"id": "ADR-1"' in section(prompt, "ACCEPTED ADRS")
    assert "Бюджет — до $200." in section(prompt, "CONSTRAINTS AND RISKS")
    context = section(prompt, "REPOSITORY CONTEXT")
    assert "abc123" in context and context.endswith("КАРТА РЕПОЗИТОРИЯ")
    assert "Индекс" in section(runner.asked["issue_judge", "fable"],
                               "INDEPENDENT ISSUE CANDIDATES")
    # Модели — и участники, и судья — читают один свежий снимок рабочей копии.
    [place] = set(runner.workspaces.values())
    assert place.name.startswith("council-scan-")
    assert not place.exists()


def test_without_a_scan_the_issues_are_cut_without_code_and_the_same_sets_need_no_judge():
    same = {"issues": [task("I1", "Поиск")]}
    result, runner = cut({("issue_discovery", "sol"): same, ("issue_discovery", "fable"): same},
                         sources=[])
    assert result.state == "done"
    assert {s.name.value: s.state for s in result.steps}["issue_judge"] == "skipped"
    assert (result.code, result.sources) == (False, [])
    assert set(runner.workspaces.values()) == {None}
    assert "abc123" not in section(runner.asked["issue_discovery", "sol"], "REPOSITORY CONTEXT")


def test_a_snapshot_that_cannot_be_made_fails_the_cut_with_its_reason():
    def broken(found, into):
        raise RepositoryError("Рабочая копия менялась")

    result, _ = cut({}, copy=broken)
    assert result.state == "failed"
    assert "менялась" in result.error
    assert (result.code, result.sources) == (False, [])         # снимка нет — кода не читали


def test_issues_read_every_scanned_repository():
    same = {"issues": [task("I1", "Поиск")]}
    result, runner = cut({("issue_discovery", "sol"): same, ("issue_discovery", "fable"): same},
                         sources=TWO_REPOS)
    assert [(s.name, s.commit_sha, s.dirty) for s in result.sources] == [
        ("back", "abc123", False), ("front", "def456", True)]
    context = section(runner.asked["issue_discovery", "sol"], "REPOSITORY CONTEXT")
    assert "back: abc123" in context and "front: def456" in context


def test_an_issue_inherits_what_blocks_its_outcomes():
    """Модель забыла, что итог держит открытый вопрос или пробел: задача по нему не «можно
    брать» — блокировки итога переходят к ней, пробел итога становится пробелом нарезки."""
    gap = OutcomeGap(question="Сколько хранить историю?", reason="нет решения")
    outcomes = APPROVED.model_copy(update={"outcomes": [
        APPROVED.outcomes[0].model_copy(update={"gaps": [gap]}), APPROVED.outcomes[1]]})
    same = {"issues": [task("I1", "Индекс"), task("I2", "Хранение", outcomes=("O2",))],
            "gaps": [{"question": "Сколько хранить историю?", "reason": "свой"}]}
    result, _ = cut({("issue_discovery", "sol"): same, ("issue_discovery", "fable"): same},
                    sources=[], outcomes=outcomes)
    assert [(i.id, i.blocked_by) for i in result.issues] == [("I1", ["G1"]), ("I2", ["Q2"])]
    assert [(g.id, g.question, g.outcome_ids) for g in result.gaps] == [
        ("G1", "Сколько хранить историю?", ["O1"])]


def test_a_gap_found_for_an_outcome_holds_every_issue_of_it():
    """Пробел назван для O1, а задачу по O1 модель им не пометила: он держит и её."""
    same = {"issues": [task("I1", "Индекс")],
            "gaps": [{"question": "Сколько хранить историю?", "reason": "",
                      "outcome_ids": ["O1"]}]}
    result, _ = cut({("issue_discovery", "sol"): same, ("issue_discovery", "fable"): same},
                    sources=[])
    assert [(i.id, i.blocked_by) for i in result.issues] == [("I1", ["G1"])]


def test_an_issue_inherits_the_decisions_and_limits_of_its_outcomes():
    """Модель не повторила решение и ограничение итога — задача стоит на них всё равно: иначе
    агент сделал бы ей наперекор."""
    bare = task("I1", "Индекс", adr_ids=[], constraint_ids=[])
    same = {"issues": [bare]}
    result, _ = cut({("issue_discovery", "sol"): same, ("issue_discovery", "fable"): same},
                    sources=[])
    [issue] = result.issues
    assert (issue.adr_ids, issue.constraint_ids) == (["ADR-1"], [5])


def test_what_holds_an_outcome_left_out_of_every_issue_stays_in_sight():
    """Итог, по которому не нарезали ни одной задачи (его держит пробел): пробел не теряется —
    он среди пробелов нарезки, его несут в вопросы."""
    gap = OutcomeGap(question="Сколько хранить историю?", reason="нет решения")
    outcomes = APPROVED.model_copy(update={"outcomes": [
        APPROVED.outcomes[0], APPROVED.outcomes[1].model_copy(update={"gaps": [gap]})]})
    same = {"issues": [task("I1", "Индекс")]}
    result, _ = cut({("issue_discovery", "sol"): same, ("issue_discovery", "fable"): same},
                    sources=[], outcomes=outcomes)
    assert result.uncovered_outcome_ids == ["O2"]
    assert [(g.id, g.question, g.outcome_ids) for g in result.gaps] == [
        ("G1", "Сколько хранить историю?", ["O2"])]
    assert result.issues[0].blocked_by == []                     # I1 — про O1, его не держит


def test_answers_that_differ_only_in_what_the_outcomes_give_need_no_judge():
    """Один участник повторил решение и ограничение итога, другой — нет: после наследования это
    одна и та же нарезка, судья не нужен."""
    full = {"issues": [task("I1", "Индекс")]}
    bare = {"issues": [task("I1", "Индекс", adr_ids=[], constraint_ids=[])]}
    result, _ = cut({("issue_discovery", "sol"): full, ("issue_discovery", "fable"): bare},
                    sources=[])
    assert {s.name.value: s.state for s in result.steps}["issue_judge"] == "skipped"


def test_an_issue_carries_the_acceptance_criteria_of_its_outcomes():
    """Критерии готовности итога доходят до агента вместе с задачей, а не на усмотрение модели."""
    same = {"issues": [task("I1", "Индекс")]}
    result, _ = cut({("issue_discovery", "sol"): same, ("issue_discovery", "fable"): same},
                    sources=[])
    assert result.issues[0].acceptance_criteria == ["Находит по слову."]
