"""Конвейер нарезки и разметки на поддельных моделях: кто что получает и когда нужен судья."""

import json

import pytest

from spec_council.models import (
    Choice,
    LabeledFragment,
    OpenQuestion,
    Proposal,
    ProposalDiscovery,
    QuestionOptions,
    StepName,
)
from spec_council.pipeline import (
    DecisionRun,
    GroupingRun,
    IdeaRun,
    ModelFailed,
    ProposalRun,
    QuestionRun,
    SlicingRun,
)

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

    def ask(self, model, prompt, key):
        step = next(s for s in STEPS if f"-{s}-{model}-" in key)
        self.asked[step, model] = prompt
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
    assert "sol" not in judge_prompt and "fable" not in judge_prompt


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
    assert "sol" not in prompt and "fable" not in prompt


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
    assert "sol" not in prompt and "fable" not in prompt


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
    assert "sol" not in prompt and "fable" not in prompt


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
