"""Нарезка и разметка советом: участники работают по отдельности, судья решает споры.

1. slice — каждый участник нарезает текст (prompts/slice.md);
2. slice_judge — если нарезки разошлись или кто-то видит несколько вариантов, судья
   выбирает итоговую (slice_judge.md); если все сошлись, шаг пропускается;
3. label — каждый участник размечает итоговые фрагменты (label.md);
4. label_judge — фрагменты, где типы разошлись, решает судья (label_judge.md).

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
import random
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Protocol

from .models import LabeledFragment, ModelRun, Slicing, SlicingStep, SlicingStepName
from .prompts import PromptError, render
from .slicing import (
    BadAnswer,
    LabelOption,
    SliceOption,
    agreed_label,
    cut,
    judged_bounds,
    judged_labels,
    label_options,
    parse_json,
    slice_options,
)

log = logging.getLogger(__name__)

Step = SlicingStepName


class ModelFailed(RuntimeError):
    """Модель не ответила: нет входа, лимит, CLI упала. Текст — для человека."""


class SlicingFailed(RuntimeError):
    """Шаг не дал результата, дальше идти не с чем."""


class Runner(Protocol):
    def ask(self, model: str, prompt: str, key: str) -> str:
        """Текст ответа модели или ModelFailed."""

    def forget(self, keys: Iterable[str]) -> None:
        """Убрать оплаченные ответы из лотка: они больше не нужны."""


def start(participants: list[str], judge: str) -> Slicing:
    return Slicing(state="running", steps=[
        SlicingStep(name=Step.slice, runs=[ModelRun(model=m) for m in participants]),
        SlicingStep(name=Step.slice_judge, runs=[ModelRun(model=judge)]),
        SlicingStep(name=Step.label, runs=[ModelRun(model=m) for m in participants]),
        SlicingStep(name=Step.label_judge, runs=[ModelRun(model=judge)]),
    ])


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def shuffled[T](items: list[T]) -> list[T]:
    """Порядок, не связанный с моделями, но одинаковый для одних и тех же вариантов."""
    items = list(items)
    random.Random(digest(json.dumps(items, ensure_ascii=False, default=str))).shuffle(items)
    return items


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class Pipeline:
    def __init__(self, council_id: str, brief: str, participants: list[str], judge: str,
                 runner: Runner, report: Callable[[Slicing], None]) -> None:
        self.council_id = council_id
        self.brief = brief
        self.participants = participants
        self.judge = judge
        self.runner = runner
        self.report = report
        self.state = start(participants, judge)
        self._lock = Lock()
        self._keys: list[str] = []

    def run(self) -> Slicing:
        try:
            fragments = cut(self.brief, self._slice())
            labeled = self._label(fragments)
        except (SlicingFailed, PromptError) as exc:
            self._finish(error=str(exc))
            return self.state
        except Exception as exc:
            log.exception("нарезка совета %s упала", self.council_id)
            self._finish(error=f"внутренняя ошибка: {exc}")
            return self.state
        self._finish(fragments=labeled)
        self.runner.forget(self._keys)  # итог уже сохранён report'ом
        return self.state

    # --- шаги

    def _slice(self) -> tuple[int, ...]:
        prompt = render("slice", input=self.brief)
        answers = self._ask_all(Step.slice, prompt, lambda data: slice_options(self.brief, data))
        distinct: dict[tuple[int, ...], list[str]] = {}
        for options in answers.values():
            for option in options:
                reasons = distinct.setdefault(option.bounds, [])
                if option.reason and option.reason not in reasons:
                    reasons.append(option.reason)
        if len(distinct) == 1:
            self._skip(Step.slice_judge)
            return next(iter(distinct))

        candidates = [SliceOption(bounds, "; ".join(reasons) or None)
                      for bounds, reasons in distinct.items()]
        variants = shuffled([{"fragments": cut(self.brief, option.bounds), "reason": option.reason}
                             for option in candidates])
        prompt = render("slice_judge", input=self.brief,
                        options=as_json([{"variant": n, **v} for n, v in enumerate(variants, 1)]))
        return self._ask_judge(Step.slice_judge, prompt,
                               lambda data: judged_bounds(self.brief, data, candidates))

    def _label(self, fragments: list[str]) -> list[LabeledFragment]:
        ids = list(range(1, len(fragments) + 1))
        texts = dict(zip(ids, fragments, strict=True))
        prompt = render("label", input=self.brief,
                        fragments=as_json([{"id": i, "text": texts[i]} for i in ids]))
        answers = self._ask_all(Step.label, prompt, lambda data: label_options(data, ids))

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
            self._skip(Step.label_judge)
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
            final |= self._ask_judge(Step.label_judge, prompt,
                                     lambda data: judged_labels(data, list(disputed)))

        return [LabeledFragment(id=i, text=texts[i], label=final[i].label, reason=final[i].reason)
                for i in ids]

    # --- вызовы моделей

    def _ask_all[T](self, step: Step, prompt: str, parse: Callable[[dict], T]) -> dict[str, T]:
        """Все участники параллельно. Упавший выбывает из шага, остальные идут дальше."""
        self._set_step(step, "running")
        with ThreadPoolExecutor(max_workers=len(self.participants)) as pool:
            futures = {m: pool.submit(self._ask, step, m, prompt, parse) for m in self.participants}
        answers = {m: f.result() for m, f in futures.items() if f.result() is not None}
        if not answers:
            self._set_step(step, "failed")
            errors = "; ".join(f"{run.model}: {run.error}" for run in self._step(step).runs)
            raise SlicingFailed(f"ни один участник не справился с шагом {step}: {errors}")
        self._set_step(step, "done")
        return answers

    def _ask_judge[T](self, step: Step, prompt: str, parse: Callable[[dict], T]) -> T:
        self._set_step(step, "running")
        answer = self._ask(step, self.judge, prompt, parse)
        if answer is None:
            self._set_step(step, "failed")
            raise SlicingFailed(f"судья {self.judge}: {self._step(step).runs[0].error}")
        self._set_step(step, "done")
        return answer

    def _ask[T](self, step: Step, model: str, prompt: str, parse: Callable[[dict], T]) -> T | None:
        key = f"{self.council_id}-{step}-{model}-{digest(prompt)}"
        self._set_run(step, model, "running")
        try:
            reply = self.runner.ask(model, prompt, key)
        except ModelFailed as exc:
            self._set_run(step, model, "failed", str(exc))
            return None
        try:
            answer = parse(parse_json(reply))
        except BadAnswer as exc:
            self.runner.forget([key])
            self._set_run(step, model, "failed", f"негодный ответ: {exc}")
            return None
        with self._lock:
            self._keys.append(key)
        self._set_run(step, model, "done")
        return answer

    # --- состояние

    def _step(self, name: Step) -> SlicingStep:
        return next(step for step in self.state.steps if step.name == name)

    def _set_step(self, name: Step, state: str) -> None:
        with self._lock:
            self._step(name).state = state
            self._publish()

    def _skip(self, name: Step) -> None:
        with self._lock:
            step = self._step(name)
            step.state = "skipped"
            step.runs = []
            self._publish()

    def _set_run(self, name: Step, model: str, state: str, error: str | None = None) -> None:
        with self._lock:
            run = next(run for run in self._step(name).runs if run.model == model)
            run.state, run.error = state, error
            self._publish()

    def _finish(self, *, fragments: list[LabeledFragment] | None = None,
                error: str | None = None) -> None:
        with self._lock:
            self.state.state = "failed" if error else "done"
            self.state.error = error
            self.state.fragments = fragments or []
            self._publish()

    def _publish(self) -> None:
        self.report(self.state.model_copy(deep=True))
