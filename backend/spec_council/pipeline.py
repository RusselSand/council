"""Ход совета: участники работают по отдельности, судья решает только там, где разошлись.

Нарезка (SlicingRun):
1. slice — каждый участник нарезает текст (prompts/slice.md);
2. slice_judge — если нарезки разошлись или кто-то видит несколько вариантов, судья
   выбирает итоговую (slice_judge.md); если все сошлись, шаг пропускается;
3. label — каждый участник размечает итоговые фрагменты (label.md);
4. label_judge — фрагменты, где типы разошлись, решает судья (label_judge.md).

Группы (GroupingRun):
1. structure — каждый участник раскладывает фрагменты готовой нарезки по группам (structure.md);
2. structure_judge — если раскладки разошлись, судья выбирает итоговую (structure_judge.md).

Идея потока (IdeaRun) — у подтверждённой группы, в тексте которой идеи нет:
1. idea_discovery — каждый участник восстанавливает идею по фрагментам группы
   (idea_discovery.md);
2. idea_judge — если вариантов несколько, судья выбирает или сводит их (idea_judge.md).

Вопросы потока (QuestionRun) — к утверждённой идее:
1. question_discovery — каждый участник ищет открытые вопросы: из текста, восстановленные
   по предложениям и недостающие (question_discovery.md);
2. question_judge — судья сводит списки в канонический (question_judge.md); если списки
   совпали, он не нужен.

Варианты потока (ProposalRun) — к отобранным вопросам, по вопросу за раз:
1. proposal_discovery — каждый участник ищет новые варианты ответа, которых ещё нет среди
   предложений группы (proposal_discovery.md);
2. proposal_judge — если новые варианты есть, судья сводит их и решает, что показать:
   одну рекомендацию, равноправные альтернативы или ничего (proposal_judge.md).

Судья не знает, какая модель что предложила, а варианты идут в перемешанном порядке:
иначе он охотнее выбирает своё и первое. Перемешивание детерминированное: у одного и
того же текста один и тот же промпт.

Каждый вызов модели идёт с ключом из совета, шага, модели и хеша промпта. Повтор после
сбоя берёт уже оплаченный ответ даром, изменённый текст — это новый вызов. Негодный
ответ из лотка выбрасывается сразу, иначе повтор получал бы его же.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from .grouping import StructureOption, judged_structure, structure_options
from .groups import letter_for
from .ideas import MergedOption, as_ids, declined, idea_options, judged_idea, merged, same_idea
from .models import (
    Group,
    GroupRelation,
    IdeaDiscovery,
    IdeaOption,
    IdeaProposal,
    LabeledFragment,
    ModelRun,
    OpenQuestion,
    Proposal,
    ProposalDiscovery,
    QuestionDiscovery,
    QuestionOptions,
    Slicing,
    Step,
    StepName,
    Structure,
    StructureDecision,
    StructureProposal,
    Vote,
)
from .prompts import PromptError, render
from .proposals import Context, Verdict, judged_proposals, proposal_list
from .proposals import as_prompt as proposal_prompt
from .proposals import merged as merged_proposals
from .questions import (
    as_prompt,
    numbered,
    question_list,
    same_lists,
    same_question,
    with_user_questions,
)
from .slicing import (
    BadAnswer,
    BoundaryNote,
    JudgeRejected,
    LabelOption,
    SliceOption,
    agreed_label,
    boundary_notes,
    cut,
    judged_bounds,
    judged_labels,
    label_options,
    note_places,
    parse_json,
    slice_options,
)

log = logging.getLogger(__name__)

# Судья отверг всех кандидатов шага — чьи ответы при этом выбросить из лотка.
CANDIDATES = {StepName.slice_judge: StepName.slice, StepName.structure_judge: StepName.structure}


class ModelFailed(RuntimeError):
    """Модель не ответила: нет входа, лимит, CLI упала. Текст — для человека."""


class StageFailed(RuntimeError):
    """Шаг не дал результата, дальше идти не с чем."""


class Runner(Protocol):
    def ask(self, model: str, prompt: str, key: str) -> str:
        """Текст ответа модели или ModelFailed."""

    def forget(self, keys: Iterable[str]) -> None:
        """Убрать оплаченные ответы из лотка: они больше не нужны."""

    def identity(self, model: str) -> str:
        """Провайдер и модель за alias: сменились — это другой ответ, а не повтор."""


def steps(participants: list[str], judge: str, *pairs: tuple[StepName, StepName]) -> list[Step]:
    """Шаги хода: для каждой пары — участники, потом судья."""
    return [step
            for work, judging in pairs
            for step in (Step(name=work, runs=[ModelRun(model=m) for m in participants]),
                         Step(name=judging, runs=[ModelRun(model=judge)]))]


def start(participants: list[str], judge: str, text: str = "") -> Slicing:
    return Slicing(state="running", run=uuid4().hex[:8], text=text,
                   steps=steps(participants, judge, (StepName.slice, StepName.slice_judge),
                               (StepName.label, StepName.label_judge)))


def start_structure(participants: list[str], judge: str, slicing: Slicing) -> Structure:
    return Structure(state="running", run=uuid4().hex[:8], slicing_run=slicing.run,
                     labels={f.id: f.label for f in slicing.fragments},
                     steps=steps(participants, judge,
                                 (StepName.structure, StepName.structure_judge)))


def start_idea(participants: list[str], judge: str) -> IdeaDiscovery:
    return IdeaDiscovery(state="running", run=uuid4().hex[:8],
                         steps=steps(participants, judge,
                                     (StepName.idea_discovery, StepName.idea_judge)))


def start_questions(participants: list[str], judge: str, idea: str) -> QuestionDiscovery:
    return QuestionDiscovery(state="running", run=uuid4().hex[:8], idea=idea,
                             steps=steps(participants, judge,
                                         (StepName.question_discovery, StepName.question_judge)))


def scope_key(scope: list[OpenQuestion]) -> list[str]:
    """Отбор вопросов, как его помнит поиск вариантов: поменялся — искать заново."""
    return [f"{question.id}: {question.text}" for question in scope]


def start_proposals(participants: list[str], judge: str,
                    scope: list[OpenQuestion]) -> ProposalDiscovery:
    return ProposalDiscovery(state="running", run=uuid4().hex[:8], scope=scope_key(scope),
                             steps=steps(participants, judge,
                                         (StepName.proposal_discovery, StepName.proposal_judge)))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def shuffled[T](items: list[T]) -> list[T]:
    """Порядок, не связанный с моделями: сортировка по хешу содержимого. Зависит только от
    набора вариантов, а не от того, кто и в каком порядке их прислал, поэтому у одного
    текста всегда один и тот же промпт. Случайность тут не нужна — нужна независимость."""
    def text(item: T) -> str:
        return json.dumps(item, ensure_ascii=False, default=str, sort_keys=True)
    salt = "".join(sorted(text(item) for item in items))
    return sorted(items, key=lambda item: digest(salt + text(item)))


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class CouncilRun[S: (Slicing, Structure, IdeaDiscovery, QuestionDiscovery, ProposalDiscovery)]:
    """Общий ход совета: вызовы участников и судьи, ключи ответов, лоток, состояние шагов.
    Что именно делают шаги — в work() наследника; он возвращает поля итога."""

    what = "ход"

    def __init__(self, council_id: str, participants: list[str], judge: str,
                 runner: Runner, report: Callable[[S], None], state: S) -> None:
        self.council_id = council_id
        self.participants = participants
        self.judge = judge
        self.runner = runner
        self.report = report
        self.state = state
        self._lock = Lock()
        self._keys: dict[StepName, list[str]] = {}  # принятые ответы по шагам

    def run(self) -> S:
        try:
            result = self.work()
        except (StageFailed, PromptError) as exc:
            self._finish(error=str(exc))
            return self.state
        except Exception as exc:
            log.exception("%s совета %s упал", self.what, self.council_id)
            self._finish(error=f"внутренняя ошибка: {exc}")
            return self.state
        self._finish(**result)
        # Итог уже сохранён report'ом — оплаченные ответы больше не нужны.
        self.runner.forget([key for keys in self._keys.values() for key in keys])
        return self.state

    def work(self) -> dict[str, Any]:
        raise NotImplementedError

    # --- вызовы моделей

    def _ask_all[T](self, step: StepName, prompt: str, parse: Callable[[dict], T]) -> dict[str, T]:
        """Все участники параллельно. Упавший выбывает из шага, остальные идут дальше."""
        self._set_step(step, "running")
        with ThreadPoolExecutor(max_workers=len(self.participants)) as pool:
            futures = {m: pool.submit(self._ask, step, m, prompt, parse) for m in self.participants}
        answers = {m: f.result() for m, f in futures.items() if f.result() is not None}
        if not answers:
            self._set_step(step, "failed")
            errors = "; ".join(f"{run.model}: {run.error}" for run in self._step(step).runs)
            raise StageFailed(f"ни один участник не справился с шагом {step}: {errors}")
        self._set_step(step, "done")
        return answers

    def _ask_judge[T](self, step: StepName, prompt: str, parse: Callable[[dict], T]) -> T:
        self._set_step(step, "running")
        answer = self._ask(step, self.judge, prompt, parse)
        if answer is None:
            self._set_step(step, "failed")
            raise StageFailed(f"судья {self.judge}: {self._step(step).runs[0].error}")
        self._set_step(step, "done")
        return answer

    def _ask[T](self, step: StepName, model: str, prompt: str,
                parse: Callable[[dict], T]) -> T | None:
        # Повтор с тем же ключом берёт оплаченный ответ даром — только если отвечает та же
        # модель: провайдер и модель за alias тоже в ключе.
        key = f"{self.council_id}-{step}-{model}-{digest(self.runner.identity(model) + prompt)}"
        self._set_run(step, model, "running")
        try:
            reply = self.runner.ask(model, prompt, key)
        except ModelFailed as exc:
            self._set_run(step, model, "failed", str(exc))
            return None
        try:
            answer = parse(parse_json(reply))
        except JudgeRejected as exc:
            # Судья честно отверг всех кандидатов. Их ответы — из лотка, иначе повтор взял бы
            # тех же кандидатов даром и снова заплатил бы судье за тот же отказ.
            with self._lock:
                candidates = self._keys.pop(CANDIDATES[step], [])
            self.runner.forget([*candidates, key])
            self._set_run(step, model, "failed", str(exc))
            return None
        except Exception as exc:
            # Любая ошибка разбора — негодный ответ, и из лотка его вон: иначе повтор взял бы
            # тот же ответ даром и упал бы на нём снова. Не BadAnswer — это недосмотр разбора.
            if not isinstance(exc, BadAnswer):
                log.exception("разбор ответа %s на шаге %s упал", model, step)
            self.runner.forget([key])
            self._set_run(step, model, "failed", f"негодный ответ: {exc}")
            return None
        with self._lock:
            self._keys.setdefault(step, []).append(key)
        self._set_run(step, model, "done")
        return answer

    # --- состояние

    def _step(self, name: StepName) -> Step:
        return next(step for step in self.state.steps if step.name == name)

    def _set_step(self, name: StepName, state: str) -> None:
        with self._lock:
            self._step(name).state = state
            self._publish()

    def _skip(self, name: StepName) -> None:
        with self._lock:
            step = self._step(name)
            step.state = "skipped"
            step.runs = []
            self._publish()

    def _set_run(self, name: StepName, model: str, state: str, error: str | None = None) -> None:
        with self._lock:
            run = next(run for run in self._step(name).runs if run.model == model)
            run.state, run.error = state, error
            self._publish()

    def _finish(self, *, error: str | None = None, **result: Any) -> None:
        with self._lock:
            self.state.state = "failed" if error else "done"
            self.state.error = error
            for field, value in result.items():
                setattr(self.state, field, value)
            self._publish()

    def _publish(self) -> None:
        self.report(self.state.model_copy(deep=True))


class SlicingRun(CouncilRun[Slicing]):
    """Нарезка текста на смысловые фрагменты и их разметка."""

    what = "нарезка"

    def __init__(self, council_id: str, brief: str, participants: list[str], judge: str,
                 runner: Runner, report: Callable[[Slicing], None]) -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start(participants, judge, brief))
        self.brief = brief

    def work(self) -> dict[str, Any]:
        bounds, notes = self._slice()
        fragments = cut(self.brief, bounds)
        return {"fragments": self._label(fragments, note_places(fragments, notes))}

    def _slice(self) -> tuple[tuple[int, ...], list[BoundaryNote]]:
        prompt = render("slice", input=self.brief)
        answers = self._ask_all(StepName.slice, prompt,
                                lambda data: slice_options(self.brief, data))
        distinct: dict[tuple[int, ...], list[str]] = {}
        for options in answers.values():
            for option in options:
                reasons = distinct.setdefault(option.bounds, [])
                if option.reason and option.reason not in reasons:
                    reasons.append(option.reason)
        if len(distinct) == 1:
            self._skip(StepName.slice_judge)
            return next(iter(distinct)), []

        candidates = [SliceOption(bounds, "; ".join(reasons) or None)
                      for bounds, reasons in distinct.items()]
        variants = shuffled([{"fragments": cut(self.brief, option.bounds), "reason": option.reason}
                             for option in candidates])
        prompt = render("slice_judge", input=self.brief,
                        options=as_json([{"variant": n, **v} for n, v in enumerate(variants, 1)]))
        return self._ask_judge(StepName.slice_judge, prompt, lambda data: (
            judged_bounds(self.brief, data, candidates), boundary_notes(data)))

    def _label(self, fragments: list[str], notes: dict[int, str]) -> list[LabeledFragment]:
        """notes — пояснения судьи нарезки по индексу фрагмента."""
        ids = list(range(1, len(fragments) + 1))
        texts = dict(zip(ids, fragments, strict=True))
        prompt = render("label", input=self.brief,
                        fragments=as_json([{"id": i, "text": texts[i]} for i in ids]))
        answers = self._ask_all(StepName.label, prompt, lambda data: label_options(data, ids))

        final: dict[int, LabelOption] = {}
        disputed: dict[int, list[LabelOption]] = {}
        for i in ids:
            per_model = [options[i] for options in answers.values()]
            agreed = agreed_label(per_model)
            if agreed:
                final[i] = agreed
            else:
                disputed[i] = list(dict.fromkeys(o for options in per_model for o in options))

        if not disputed:
            self._skip(StepName.label_judge)
        else:
            prompt = render(
                "label_judge", input=self.brief,
                fragments=as_json([{"id": i, "text": texts[i]} for i in disputed]),
                label_options=as_json([
                    {"id": i, "options": shuffled([{"label": o.label, "reason": o.reason}
                                                  for o in options])}
                    for i, options in disputed.items()
                ]),
            )
            final |= self._ask_judge(StepName.label_judge, prompt,
                                     lambda data: judged_labels(data, list(disputed)))

        return [
            LabeledFragment(
                id=i, text=texts[i], label=final[i].label, reason=final[i].reason,
                council_label=final[i].label,
                decided_by="judge" if i in disputed else "agreed",
                votes=[Vote(model=model, labels=[o.label for o in options[i]])
                       for model, options in answers.items()],
                slice_note=notes.get(i - 1),
            )
            for i in ids
        ]


class GroupingRun(CouncilRun[Structure]):
    """Раскладка фрагментов готовой нарезки по группам — вокруг идей. Типы берутся как есть
    сейчас, с правками человека: они и есть итог нарезки."""

    what = "группировка"

    def __init__(self, council_id: str, slicing: Slicing, participants: list[str], judge: str,
                 runner: Runner, report: Callable[[Structure], None]) -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start_structure(participants, judge, slicing))
        self.slicing = slicing

    def work(self) -> dict[str, Any]:
        labels = {f.id: f.label for f in self.slicing.fragments}
        fragments = as_json([{"id": f.id, "text": f.text, "type": f.label}
                             for f in self.slicing.fragments])
        prompt = render("structure", input=self.slicing.text, fragments=fragments)
        answers = self._ask_all(StepName.structure, prompt,
                                lambda data: structure_options(data, labels))

        # Одинаковые по содержанию раскладки — одна; первая встреченная даёт названия.
        distinct: dict[object, StructureOption] = {}
        for options in answers.values():
            for option in options:
                distinct.setdefault(option.key(), option)
        if len(distinct) == 1:
            self._skip(StepName.structure_judge)
            return final_structure(next(iter(distinct.values())), [])

        candidates = list(distinct.values())
        variants = shuffled([as_variant(option) for option in candidates])
        numbered = [{"variant": n, **v} for n, v in enumerate(variants, 1)]
        prompt = render("structure_judge", input=self.slicing.text, fragments=fragments,
                        structure_options=as_json(numbered))
        chosen, decisions = self._ask_judge(StepName.structure_judge, prompt,
                                            lambda data: judged_structure(data, labels, candidates))
        return final_structure(chosen, [
            StructureDecision(issue=d.issue, decision=d.decision, reason=d.reason)
            for d in decisions
        ])


def as_variant(option: StructureOption) -> dict[str, Any]:
    """Раскладка для судьи — в той же форме, в какой её прислал участник."""
    shared = option.shared()
    return {
        "groups": [{"id": g.id, "title": g.title, "idea_fragment_ids": sorted(g.ideas),
                    "fragment_ids": sorted(g.members - shared), "missing_idea": not g.ideas,
                    "shared_fragment_ids": sorted(g.members & shared)} for g in option.groups],
        "relations": [{"from": r.source, "to": r.target, "type": r.type, "reason": r.reason}
                      for r in option.relations],
        "reason": option.reason,
    }


def final_structure(option: StructureOption, decisions: list[StructureDecision]) -> dict[str, Any]:
    """Итог для экрана: группы по порядку первого фрагмента под буквами A, B, C…, связи — между
    ними, независимость — просто отсутствие связи."""
    ordered = sorted(option.groups, key=lambda group: min(group.members))
    letters = {group.id: letter_for(n) for n, group in enumerate(ordered)}
    shared = option.shared()
    groups = [Group(id=letters[g.id], title=g.title or letters[g.id],
                    fragment_ids=sorted(g.members), idea_fragment_ids=sorted(g.ideas),
                    missing_idea=not g.ideas, shared_fragment_ids=sorted(g.members & shared))
              for g in ordered]
    relations = [GroupRelation(source=letters[r.source], target=letters[r.target], type=r.type,
                               reason=r.reason)
                 for r in option.relations if r.type != "independent"]
    return {"groups": groups, "relations": relations, "decisions": decisions,
            "proposal": StructureProposal(groups=groups, relations=relations)}


class IdeaRun(CouncilRun[IdeaDiscovery]):
    """Идея группы, которой нет в тексте: участники восстанавливают её по фрагментам группы,
    судья выбирает, если вариантов несколько. Название группы модели не видят: это лишь
    метка для навигации, а идея должна опираться на фрагменты."""

    what = "поиск идеи"

    def __init__(self, council_id: str, fragments: list[LabeledFragment], participants: list[str],
                 judge: str, runner: Runner, report: Callable[[IdeaDiscovery], None]) -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start_idea(participants, judge))
        self.fragments = fragments

    def work(self) -> dict[str, Any]:
        known = {f.id for f in self.fragments}
        group = as_json({"fragments": [{"id": f"F{f.id}", "type": f.label, "text": f.text}
                                       for f in self.fragments]})
        answers = self._ask_all(StepName.idea_discovery, render("idea_discovery", group=group),
                                lambda data: idea_options(data, known))
        options = merged(answers)
        found = [as_option(option) for option in options]
        if len(options) <= 1:
            self._skip(StepName.idea_judge)
            if not options:
                proposal = IdeaProposal(idea=None, reason=declined(answers), decided_by="agreed")
            else:
                proposal = IdeaProposal(idea=found[0].idea, evidence=found[0].evidence,
                                        reason=found[0].reason, decided_by="agreed", option=0)
            return {"options": found, "proposal": proposal}

        variants = shuffled([{"idea": o.idea, "evidence": as_ids(o.evidence), "reason": o.reason}
                             for o in options])
        numbered = [{"variant": n, **v} for n, v in enumerate(variants, 1)]
        prompt = render("idea_judge", group=group, idea_options=as_json(numbered))
        verdict = self._ask_judge(StepName.idea_judge, prompt,
                                  lambda data: judged_idea(data, known))
        chosen = None if verdict.idea is None else next(
            (n for n, option in enumerate(options)
             if same_idea(option.idea) == same_idea(verdict.idea)), None)
        return {"options": found, "proposal": IdeaProposal(
            idea=verdict.idea, evidence=list(verdict.evidence), reason=verdict.reason,
            decided_by="judge", option=chosen)}


def as_option(option: MergedOption) -> IdeaOption:
    return IdeaOption(idea=option.idea, evidence=sorted(option.evidence), reason=option.reason,
                      models=option.models)


class QuestionRun(CouncilRun[QuestionDiscovery]):
    """Открытые вопросы к утверждённой идее потока: участники по отдельности ищут их по идее
    и фрагментам группы, судья сводит списки в канонический. Вопросы из текста остаются
    дословно и все — что бы ни ответили модели."""

    what = "поиск вопросов"

    def __init__(self, council_id: str, idea: str, fragments: list[LabeledFragment],
                 participants: list[str], judge: str, runner: Runner,
                 report: Callable[[QuestionDiscovery], None]) -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start_questions(participants, judge, idea))
        self.idea = idea
        self.fragments = {fragment.id: fragment for fragment in fragments}

    def work(self) -> dict[str, Any]:
        group = as_json([{"id": f"F{f.id}", "type": f.label, "text": f.text}
                         for f in self.fragments.values()])
        prompt = render("question_discovery", idea=self.idea, fragments=group)
        answers = self._ask_all(StepName.question_discovery, prompt,
                                lambda data: question_list(data, self.fragments))
        lists = list(answers.values())
        if len(lists) > 1 and same_lists(lists):
            self._skip(StepName.question_judge)
            chosen = lists[0]
        else:
            candidates = shuffled([{"questions": as_prompt(questions)} for questions in lists])
            numbered_lists = [{"agent": n, **c} for n, c in enumerate(candidates, 1)]
            prompt = render("question_judge", idea=self.idea, fragments=group,
                            question_candidates=as_json(numbered_lists))
            chosen = self._ask_judge(StepName.question_judge, prompt,
                                     lambda data: question_list(data, self.fragments))
        return {"questions": numbered(with_user_questions(chosen, self.fragments))}


class ProposalRun(CouncilRun[ProposalDiscovery]):
    """Новые варианты ответа на отобранные вопросы потока. Вопросы — по очереди: модель всё
    равно отвечает по одному запросу за раз. По каждому участники ищут варианты, которых нет
    среди предложений группы, судья сводит их и решает, что показать. Готовый вопрос сразу
    в отчёте: человек видит варианты по мере поиска. Варианты нумеруются сквозь поток: P1, P2…
    Принятых решений на этом шаге ещё нет — их фиксирует следующий.

    Вопрос модели видят вместе с другими вопросами потока (other_open_questions): без них не
    указать, от какого вопроса вариант зависит. Повтор предложения группы, как бы его ни
    написали, — не новый вариант: он отсеивается и у участников, и у судьи. Модель, упавшая
    на одном вопросе, так и числится упавшей, хоть следующие она и ответила."""

    what = "поиск вариантов"

    def __init__(self, council_id: str, idea: str, scope: list[OpenQuestion],
                 fragments: list[LabeledFragment], participants: list[str], judge: str,
                 runner: Runner, report: Callable[[ProposalDiscovery], None]) -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start_proposals(participants, judge, scope))
        self.idea = idea
        self.scope = scope
        self.fragments = {fragment.id: fragment for fragment in fragments}

    def work(self) -> dict[str, Any]:
        limits = [f for f in self.fragments.values() if f.label in ("constraint", "risk")]
        known = as_json([{"id": f"F{f.id}", "type": f.label, "text": f.text} for f in limits])
        numbers = iter(range(1, 10_000))
        failures: dict[str, list[str]] = {}
        judged = False
        for question in self.scope:
            context = Context(
                frozenset(f.id for f in limits if f.label == "constraint"),
                frozenset(f.id for f in limits if f.label == "risk"),
                frozenset(q.id for q in self.scope if q.id != question.id))
            values = {
                "idea": self.idea,
                "question": as_json({
                    "id": question.id, "text": question.text,
                    "other_open_questions": [{"id": q.id, "text": q.text}
                                             for q in self.scope if q.id != question.id]}),
                "existing_proposals": as_json([{"id": f"F{i}", "text": self.fragments[i].text}
                                               for i in question.proposal_ids
                                               if i in self.fragments]),
                "constraints_and_risks": known,
            }
            answers = self._ask_all(
                StepName.proposal_discovery,
                render("proposal_discovery", **values, accepted_decisions="[]"),
                partial(proposal_list, context=context))
            self._keep_failures(question, failures)
            existing = {same_question(self.fragments[i].text): i for i in question.proposal_ids
                        if i in self.fragments}
            offered = merged_proposals(c for found in answers.values() for c in found)
            candidates = [c for c in offered if same_question(c.text) not in existing]
            if candidates:
                judged = True
                variants = shuffled([proposal_prompt(c) for c in candidates])
                prompt = render("proposal_judge", **values, accepted_adrs="[]",
                                proposal_candidates=as_json(
                                    [{"candidate": n, **v} for n, v in enumerate(variants, 1)]))
                verdict = without_repeats(self._ask_judge(
                    StepName.proposal_judge, prompt, partial(judged_proposals, context=context)),
                    existing)
            else:
                verdict = Verdict("none", (), None)
            with self._lock:
                self.state.options.append(options_of(question, verdict, numbers))
                self._publish()
        if not judged:
            self._skip(StepName.proposal_judge)
        return {"options": self.state.options}

    def _keep_failures(self, question: OpenQuestion, failures: dict[str, list[str]]) -> None:
        """Шаг участников один на все вопросы, и каждый следующий перезаписал бы, кто упал на
        прежнем. Копим: упавшая хоть на одном вопросе модель так и числится упавшей — с тем,
        на каком и почему."""
        with self._lock:
            runs = list(self._step(StepName.proposal_discovery).runs)
        for run in runs:
            if run.state == "failed":
                failures.setdefault(run.model, []).append(f"{question.id}: {run.error}")
        for model, errors in failures.items():
            self._set_run(StepName.proposal_discovery, model, "failed", "; ".join(errors))


def without_repeats(verdict: Verdict, existing: dict[str, int]) -> Verdict:
    """Судья вернул повтор предложения группы — это не новый вариант. Рекомендовал повтор —
    новых вариантов нет, и сказано, с чем он совпал; из альтернатив повтор просто выпадает:
    выбор между оставшимися и предложением группы остаётся."""
    kept = tuple(c for c in verdict.proposals if same_question(c.text) not in existing)
    if kept or verdict.kind == "none":
        return Verdict(verdict.kind, kept, verdict.reason)
    repeats = sorted({existing[same_question(c.text)] for c in verdict.proposals})
    return Verdict("none", (), "рекомендованный вариант уже есть в тексте группы: "
                   + ", ".join(f"F{i}" for i in repeats))


def options_of(question: OpenQuestion, verdict: Verdict, numbers) -> QuestionOptions:
    return QuestionOptions(
        question_id=question.id, verdict=verdict.kind, reason=verdict.reason,
        proposals=[Proposal(id=f"P{next(numbers)}", text=c.text, reason=c.reason,
                            constraint_ids=list(c.constraint_ids), risk_ids=list(c.risk_ids),
                            depends_on=list(c.depends_on),
                            recommended=verdict.kind == "recommended")
                   for c in verdict.proposals])
