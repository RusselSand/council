"""Конвейер нарезки и разметки на поддельных моделях: кто что получает и когда нужен судья."""

import json

import pytest

from spec_council.models import SlicingStepName
from spec_council.pipeline import ModelFailed, Pipeline

TEXT = ("Хочу воркер для Codex CLI. Состояние держать в файлах, без базы. "
        "Главное — не потерять результат.")
PARTS = ["Хочу воркер для Codex CLI.", "Состояние держать в файлах, без базы.",
         "Главное — не потерять результат."]
STEPS = [name.value for name in SlicingStepName]


def sliced(*variants, reason=None):
    options = [{"fragments": v, "reason": reason} for v in variants]
    return {"number": len(variants), "options": options}


def labeled(*labels):
    return {"labels": [{"id": i, "options": [{"label": label, "reason": f"{label} {i}"}]}
                       for i, label in enumerate(labels, 1)]}


class FakeRunner:
    """Ответы по (шаг, модель). Исключение в ответах — модель упала."""

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
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)

    def forget(self, keys):
        self.forgotten.extend(keys)

    def identity(self, model):
        return self.identities.get(model, model)


def run(replies, participants=("sol", "fable"), judge="fable"):
    runner, reports = FakeRunner(replies), []
    result = Pipeline("c1", TEXT, list(participants), judge, runner, reports.append).run()
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
    Pipeline("c1", TEXT, ["sol", "fable"], "fable", runner, lambda _: None).run()
    sol_keys = lambda r: sorted(k for k in r.keys if "-sol-" in k)          # noqa: E731
    fable_keys = lambda r: sorted(k for k in r.keys if "-fable-" in k)      # noqa: E731
    assert set(sol_keys(before)).isdisjoint(sol_keys(runner))
    assert fable_keys(before) == fable_keys(runner)
