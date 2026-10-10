"""Ход совета: участники работают по отдельности, судья решает только там, где разошлись.
Ответ один (участник в совете один или другие упали) — сравнивать не с чем, и судья его
проверяет: «сошлись» — это минимум два одинаковых ответа.

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

Скан репозитория (RepositoryRun) — необязательный, к утверждённой идее; модели читают
рабочую копию сами:
1. repository_discovery — каждый участник по inventory и коду устанавливает, как система
   устроена сейчас относительно идеи (repository_discovery.md);
2. repository_judge — судья проверяет находки по коду, сводит их в одну карту и, если пробелы
   существенны, даёт задания follow_up (repository_judge.md); участники доисследуют их, судья
   проверяет снова — до двух раз. Карта идёт во все следующие шаги: {{repository}}.

Скан макета (DesignRun) — необязательный, после шага «Репозиторий»; совет сам снимает файл
Figma через REST API, модели читают снимок:
1. design_discovery — каждый участник по снимку устанавливает, какой интерфейс и какое
   поведение предусмотрены в макете для идеи (design_discovery.md);
2. design_judge — судья проверяет их описания по снимку, сводит в одно и, если пробелы
   существенны, даёт задания follow_up (design_judge.md) — так же до двух раз. Описание идёт
   во все следующие шаги: {{design}}.

Вопросы потока (QuestionRun) — к утверждённой идее:
1. question_discovery — каждый участник ищет открытые вопросы: из текста, восстановленные
   по предложениям и недостающие (question_discovery.md);
2. question_judge — судья сводит списки в канонический (question_judge.md); если списки
   совпали, он не нужен.

Варианты потока (ProposalRun) — к отобранным вопросам, по вопросу за раз; к вопросу, который
был в отборе и раньше (тот же номер и формулировка), варианты не ищут заново — их переносят:
1. proposal_discovery — каждый участник ищет новые варианты ответа, которых ещё нет среди
   предложений группы (proposal_discovery.md);
2. proposal_judge — если новые варианты есть, судья сводит их и решает, что показать:
   одну рекомендацию, равноправные альтернативы или ничего (proposal_judge.md).

Проверка выбора (DecisionRun) — по вопросу за раз; тот же выбор по тому же вопросу заново не
проверяют — анализ переносят:
1. decision_analysis — каждый участник проверяет выбранный человеком вариант, а у unresolved
   сравнивает варианты вопроса и, если один обоснованно лучше, рекомендует его
   (decision_analysis.md);
2. decision_judge — судья сводит их анализы в один итог (decision_judge.md). У unresolved
   вопроса без вариантов сравнивать нечего — модели его не видят.

Итоги потока (OutcomeRun) — из зафиксированных решений:
1. outcome_discovery — каждый участник собирает решения в законченные изменения системы,
   а то, что держит открытый вопрос, помечает заблокированным (outcome_discovery.md);
2. outcome_judge — судья сравнивает наборы и сводит их в итоговый (outcome_judge.md); если
   наборы совпали, он не нужен.

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
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from .decisions import Analysis, analysis_of, judged_analysis
from .decisions import Context as DecisionContext
from .decisions import as_prompt as analysis_prompt
from .design import Context as DesignContext
from .design import as_prompt as design_prompt
from .design import context_prompt as design_context
from .design import judged_design
from .design import map_of as design_map_of
from .export import previous_of, settled, translations, untranslated
from .figma import Fetcher, FigmaError, Link
from .figma import snapshot as figma_snapshot
from .grouping import StructureOption, judged_structure, structure_options
from .groups import letter_for
from .ideas import MergedOption, as_ids, declined, idea_options, judged_idea, merged, same_idea
from .issues import Answer as IssueAnswer
from .issues import Context as IssueContext
from .issues import Parent, issue_set, same_issues
from .issues import as_prompt as issue_prompt
from .models import (
    SKIPPED,
    Choice,
    Decision,
    DecisionAnalysis,
    DecisionsSearch,
    DesignScan,
    Group,
    GroupRelation,
    IdeaDiscovery,
    IdeaOption,
    IdeaProposal,
    Issue,
    IssueDiscovery,
    IssueGap,
    LabeledFragment,
    ModelRun,
    NotesDraft,
    NotesExport,
    OpenQuestion,
    Outcome,
    OutcomeDiscovery,
    OutcomeGap,
    OutcomeTouch,
    ProjectDecision,
    Proposal,
    ProposalDiscovery,
    QuestionAnalysis,
    QuestionDiscovery,
    QuestionOptions,
    RepositoryScan,
    Slicing,
    Step,
    StepName,
    Stream,
    Structure,
    StructureDecision,
    StructureProposal,
    Vote,
)
from .notes import Catalog
from .outcomes import Context as OutcomeContext
from .outcomes import as_prompt as outcome_prompt
from .outcomes import assembly_of, same_assembly, touch_prompt
from .project import (
    catalog_print,
    catalog_prompt,
    evidence_files,
    fingerprint,
    issue_outcomes,
    records,
    same_selection,
    scanned_commits,
    trails_of,
)
from .project import selected as selected_decisions
from .prompts import PromptError, render
from .proposals import Context, Verdict, found_by_question, judged_proposals, proposal_list
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
from .repository import Context as RepositoryContext
from .repository import (
    RepositoryError,
    Source,
    commits_prompt,
    context_prompt,
    judged_map,
    map_of,
    scanned,
    snapshot_all,
    sources_prompt,
)
from .repository import as_prompt as map_prompt
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
    def ask(self, model: str, prompt: str, key: str, workspace: Path | None = None) -> str:
        """Текст ответа модели или ModelFailed. workspace — каталог, который модель читает:
        ход идёт в нём, только на чтение."""

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


# Сколько проходов участников и судьи у скана: первый и до двух доисследований.
SCAN_ROUNDS = 3


# Снимок рабочих копий хода в каталог: его отпечаток и какие файлы легли.
type Copier = Callable[[Sequence[Source], Path], tuple[str, frozenset[str]]]


def start_scan(participants: list[str], judge: str, idea: str,
               sources: Sequence[Source]) -> RepositoryScan:
    return RepositoryScan(state="running", run=uuid4().hex[:8], idea=idea,
                          repositories=[scanned(source) for source in sources],
                          steps=steps(participants, judge, (StepName.repository_discovery,
                                                            StepName.repository_judge)))


def start_design(participants: list[str], judge: str, idea: str,
                 links: Sequence[Link]) -> DesignScan:
    return DesignScan(state="running", run=uuid4().hex[:8], idea=idea,
                      links=[link.url for link in links],
                      steps=steps(participants, judge, (StepName.design_discovery,
                                                        StepName.design_judge)))


def start_decisions(participants: list[str], judge: str, idea: str, repository: str,
                    design: str) -> DecisionsSearch:
    return DecisionsSearch(state="running", run=uuid4().hex[:8], idea=idea,
                           repository=repository, design=design,
                           steps=steps(participants, judge,
                                       (StepName.project_decisions_discovery,
                                        StepName.project_decisions_judge)))


def start_questions(participants: list[str], judge: str, idea: str,
                    repository: str = SKIPPED, design: str = SKIPPED,
                    decisions: Sequence[ProjectDecision] = (),
                    notes: str = "") -> QuestionDiscovery:
    return QuestionDiscovery(state="running", run=uuid4().hex[:8], idea=idea,
                             repository=repository, design=design,
                             decisions=[decision.adr_id for decision in decisions],
                             decisions_seen=fingerprint(decisions), notes=notes,
                             steps=steps(participants, judge,
                                         (StepName.question_discovery, StepName.question_judge)))


def question_key(question: OpenQuestion) -> str:
    """Вопрос, как его узнают после правки отбора: тот же номер и та же формулировка."""
    return f"{question.id}: {question.text}"


def scope_key(scope: list[OpenQuestion]) -> list[str]:
    """Отбор вопросов, как его помнит поиск вариантов: поменялся — искать заново."""
    return [question_key(question) for question in scope]


def start_proposals(participants: list[str], judge: str, scope: list[OpenQuestion],
                    carried: Iterable[QuestionOptions] = (), first: int = 1) -> ProposalDiscovery:
    """carried — варианты вопросов, которые были в отборе и раньше: их не ищут, они уже здесь;
    first — с какого номера нумеровать новые."""
    return ProposalDiscovery(state="running", run=uuid4().hex[:8], scope=scope_key(scope),
                             options=list(carried), first=first,
                             steps=steps(participants, judge,
                                         (StepName.proposal_discovery, StepName.proposal_judge)))


def choice_entry(choice: Choice) -> str:
    """Выбор по вопросу, как его помнит проверка: «Q1: P2», свой — и с текстом."""
    return (f"{choice.question_id}: {choice.proposal or '-'}"
            + (f": {choice.text}" if choice.text is not None else ""))


def choices_key(choices: list[Choice]) -> list[str]:
    """Выбор, как его помнит проверка: поменялся — и свой вариант тоже — проверять заново."""
    return [choice_entry(choice) for choice in choices]


def start_analysis(participants: list[str], judge: str, choices: list[Choice],
                   carried: Iterable[QuestionAnalysis] = ()) -> DecisionAnalysis:
    """carried — проверка того же выбора по тем же вопросам: её не повторяют, она уже здесь."""
    return DecisionAnalysis(state="running", run=uuid4().hex[:8], choices=choices_key(choices),
                            analyses=list(carried),
                            steps=steps(participants, judge,
                                        (StepName.decision_analysis, StepName.decision_judge)))


def decisions_key(decisions: list[Decision]) -> list[str]:
    """Решения, как их помнит сборка итогов: поменялись (и обоснование тоже) — собирать заново."""
    return [f"{d.question_id}: {d.proposal or '-'}: {d.rationale or ''}" for d in decisions]


def start_outcomes(participants: list[str], judge: str, decisions: list[Decision],
                   kept: Sequence[Outcome] = ()) -> OutcomeDiscovery:
    """kept — закреплённые итоги: их не пересобирают, и они видны сразу, пока собираются
    остальные."""
    return OutcomeDiscovery(state="running", run=uuid4().hex[:8],
                            decisions=decisions_key(decisions), outcomes=list(kept),
                            kept=[outcome.id for outcome in kept],
                            steps=steps(participants, judge,
                                        (StepName.outcome_discovery, StepName.outcome_judge)))


def outcome_print(outcome: Outcome) -> str:
    """Итог, каким его нарезали на задачи: тот же — его задачи переносятся. Номера решений —
    не в счёт: они сдвигаются вместе с отбором, а итог тот же."""
    return json.dumps([outcome.title, outcome.behavior, sorted(outcome.acceptance_criteria),
                       outcome.constraint_ids, outcome.risk_ids], ensure_ascii=False)


def start_issues(participants: list[str], judge: str, outcomes_run: str,
                 decisions: Sequence[Decision] = (),
                 carried: Sequence[Issue] = ()) -> IssueDiscovery:
    """Код в начале не прочитан: какой — ход отметит сам, когда снимок сделан. carried —
    перенесённые задачи: их не нарезают заново, и они видны сразу, пока режут остальное."""
    return IssueDiscovery(state="running", run=uuid4().hex[:8], outcomes=outcomes_run,
                          decisions=decisions_key(list(decisions)), issues=list(carried),
                          kept=[issue.id for issue in carried],
                          steps=steps(participants, judge,
                                      (StepName.issue_discovery, StepName.issue_judge)))


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


class CouncilRun[S: (Slicing, Structure, IdeaDiscovery, RepositoryScan, DesignScan,
                     DecisionsSearch, QuestionDiscovery, ProposalDiscovery, DecisionAnalysis,
                     OutcomeDiscovery, IssueDiscovery, NotesDraft)]:
    """Общий ход совета: вызовы участников и судьи, ключи ответов, лоток, состояние шагов.
    Что именно делают шаги — в work() наследника; он возвращает поля итога."""

    what = "ход"
    # Каталог, который модели читают в этом ходе; None — ход без файлов, только текст.
    workspace: Path | None = None
    # Состояние этого каталога: оно входит в ключ ответа — к другому коду ответ не годится.
    fingerprint: str = ""
    # Какие файлы легли в снимок.
    copied: frozenset[str] = frozenset()

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

    @contextmanager
    def _reading(self, sources: Sequence[Source], copy: Copier) -> Iterator[Path | None]:
        """Модели этого хода читают снимок рабочих копий: только файлы inventory, без .git и
        игнорируемого, неподвижный, пока ход идёт, — только на чтение. Его отпечаток ключует
        ответы: к другому коду оплаченный ответ не годится. Снимок удаляется с концом хода.
        Рабочих копий нет — кода нет: ход без файлов."""
        if not sources:
            yield None
            return
        with tempfile.TemporaryDirectory(prefix="council-scan-") as place:
            folder = Path(place)
            try:
                self.fingerprint, self.copied = copy(sources, folder)
            except RepositoryError as exc:
                raise StageFailed(str(exc)) from exc
            self.workspace = folder
            try:
                yield folder
            finally:
                self.workspace = None

    def _explored(self, discovery: StepName, judge: StepName, values: dict[str, str],
                  parse: Callable[[dict], Any], judged: Callable[[dict], Any],
                  shown: Callable[[Any], dict]) -> dict[str, Any]:
        """Исследование в несколько проходов — репозитория или макета: участники по
        отдельности, судья проверяет их по снимку и сводит в одно, а если пробелы существенны,
        участники доисследуют именно их — до SCAN_ROUNDS проходов; судья видит и прежнее
        описание. Одинаковые описания судья видит одним: число согласных — не довод. Промпты
        — по именам шагов."""
        requests: list[dict] = []
        previous: list | dict = []
        failures: dict[str, list[str]] = {}
        for n in range(1, SCAN_ROUNDS + 1):
            answers = self._ask_all(
                discovery,
                render(discovery.value, **values, investigation_requests=as_json(requests)),
                parse)
            self._keep_failures(discovery, f"проход {n}", failures)
            distinct = {as_json(shown(m)): shown(m) for m in answers.values()}
            variants = shuffled(list(distinct.values()))
            prompt = render(judge.value, **values, previous_findings=as_json(previous),
                            discovery_results=as_json(
                                [{"discovery": i, **v} for i, v in enumerate(variants, 1)]))
            verdict = self._ask_judge(judge, prompt, judged)
            with self._lock:
                self.state.rounds, self.state.complete = n, verdict.complete
                self.state.result, self.state.follow_up = verdict.result, list(verdict.follow_up)
                self._publish()
            if verdict.complete:
                break
            requests = [item.model_dump(mode="json") for item in verdict.follow_up]
            previous = shown(verdict.result)
        return {"rounds": self.state.rounds, "complete": self.state.complete,
                "result": self.state.result, "follow_up": self.state.follow_up}

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
        state = self.runner.identity(model) + self.fingerprint
        key = f"{self.council_id}-{step}-{model}-{digest(state + prompt)}"
        self._set_run(step, model, "running")
        try:
            reply = self.runner.ask(model, prompt, key, workspace=self.workspace)
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

    def _keep_failures(self, step: StepName, label: str,
                       failures: dict[str, list[str]]) -> None:
        """Шаг участников, который зовут по вопросу за раз, один на все вопросы, и каждый
        следующий перезаписал бы, кто упал на прежнем. Копим: упавшая хоть на одном вопросе
        модель так и числится упавшей — с тем, на каком и почему."""
        with self._lock:
            runs = list(self._step(step).runs)
        for run in runs:
            if run.state == "failed":
                failures.setdefault(run.model, []).append(f"{label}: {run.error}")
        for model, errors in failures.items():
            self._set_run(step, model, "failed", "; ".join(errors))

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
        if len(answers) > 1 and len(distinct) == 1:
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
            agreed = agreed_label(per_model) if len(answers) > 1 else None
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
        if len(answers) > 1 and len(distinct) == 1:
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
        # Идеи не нашли — проверять нечего; одна — судья нужен, если её предложил один ответ
        # (другой участник мог ответить, что идеи не видит, — это не согласие).
        if not options or (len(options) == 1 and len(options[0].models) > 1):
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
                 report: Callable[[QuestionDiscovery], None], *, repository: str = SKIPPED,
                 repository_map: str = context_prompt(None), design: str = SKIPPED,
                 design_map: str = design_context(None),
                 accepted: Sequence[ProjectDecision] = (), notes: str = "") -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start_questions(participants, judge, idea, repository, design,
                                         accepted, notes))
        self.idea = idea
        self.repository = repository_map
        self.design = design_map
        self.accepted = accepted_prompt(accepted)
        self.decision_ids = frozenset(decision.adr_id for decision in accepted)
        self.fragments = {fragment.id: fragment for fragment in fragments}

    def work(self) -> dict[str, Any]:
        group = as_json([{"id": f"F{f.id}", "type": f.label, "text": f.text}
                         for f in self.fragments.values()])
        prompt = render("question_discovery", idea=self.idea, fragments=group,
                        repository=self.repository, design=self.design,
                        accepted_decisions=self.accepted)
        answers = self._ask_all(StepName.question_discovery, prompt,
                                lambda data: question_list(data, self.fragments,
                                                           self.decision_ids))
        lists = list(answers.values())
        if len(lists) > 1 and same_lists(lists):
            self._skip(StepName.question_judge)
            chosen = lists[0]
        else:
            candidates = shuffled([{"questions": as_prompt(questions)} for questions in lists])
            numbered_lists = [{"agent": n, **c} for n, c in enumerate(candidates, 1)]
            prompt = render("question_judge", idea=self.idea, fragments=group,
                            repository=self.repository, design=self.design,
                            accepted_decisions=self.accepted,
                            question_candidates=as_json(numbered_lists))
            chosen = self._ask_judge(StepName.question_judge, prompt,
                                     lambda data: question_list(data, self.fragments,
                                                                self.decision_ids))
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
    на одном вопросе, так и числится упавшей, хоть следующие она и ответила.

    carried — варианты вопросов, которые были в отборе и раньше: их не ищут заново, хоть соседи
    и поменялись, — иначе каждый добавленный вопрос стоил бы поиска по всем. Новые варианты
    нумеруются с first: номера раньше заняты перенесёнными и своими вариантами человека."""

    what = "поиск вариантов"

    def __init__(self, council_id: str, idea: str, scope: list[OpenQuestion],
                 fragments: list[LabeledFragment], participants: list[str], judge: str,
                 runner: Runner, report: Callable[[ProposalDiscovery], None], *,
                 repository: str = context_prompt(None),
                 design: str = design_context(None),
                 accepted: Sequence[ProjectDecision] = (),
                 carried: Mapping[str, QuestionOptions] | None = None, first: int = 1) -> None:
        self.carried = dict(carried or {})
        self.first = first
        super().__init__(council_id, participants, judge, runner, report,
                         start_proposals(participants, judge, scope, self.carried.values(), first))
        self.idea = idea
        self.repository = repository
        self.design = design
        self.accepted = accepted_prompt(accepted)
        self.scope = scope
        self.fragments = {fragment.id: fragment for fragment in fragments}

    def work(self) -> dict[str, Any]:
        limits = [f for f in self.fragments.values() if f.label in ("constraint", "risk")]
        known = as_json([{"id": f"F{f.id}", "type": f.label, "text": f.text} for f in limits])
        numbers = iter(range(self.first, self.first + 10_000))
        failures: dict[str, list[str]] = {}
        judged = asked = False
        for question in self.scope:
            if question.id in self.carried:
                continue
            asked = True
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
                "repository": self.repository,
            "design": self.design,
            }
            answers = self._ask_all(
                StepName.proposal_discovery,
                render("proposal_discovery", **values, accepted_decisions=self.accepted),
                partial(proposal_list, context=context))
            self._keep_failures(StepName.proposal_discovery, question.id, failures)
            existing = {same_question(self.fragments[i].text): i for i in question.proposal_ids
                        if i in self.fragments}
            offered = merged_proposals(c for found in answers.values() for c in found)
            candidates = [c for c in offered if same_question(c.text) not in existing]
            if candidates:
                judged = True
                variants = shuffled([proposal_prompt(c) for c in candidates])
                prompt = render("proposal_judge", **values, accepted_adrs=self.accepted,
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
        if not asked:
            self._skip(StepName.proposal_discovery)
        if not judged:
            self._skip(StepName.proposal_judge)
        return {"options": self.state.options}


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


class DecisionRun(CouncilRun[DecisionAnalysis]):
    """Проверка выбора по отобранным вопросам потока, по вопросу за раз. Где человек выбрал
    вариант, участники проверяют его, где оставил unresolved — сравнивают варианты вопроса:
    из текста группы и найденные советом. Судья сводит их анализы в один итог. Новых вариантов
    здесь нет, выбор человека не меняется, а решений шаг не принимает — их фиксирует человек.
    Готовый вопрос сразу в отчёте.

    Модели видят и другие вопросы потока — что по ним выбрано и какие unresolved: без этого не
    сказать, от какого нерешённого вопроса зависит выбор. Одинаковые анализы судья видит
    одним: число согласных — не довод.

    carried — проверка того же выбора по тем же вопросам: её не повторяют, хоть выбор по
    соседним и поменялся, — проверяют только новое."""

    what = "проверка выбора"

    def __init__(self, council_id: str, idea: str, scope: list[OpenQuestion],
                 choices: list[Choice], proposals: ProposalDiscovery | None,
                 fragments: list[LabeledFragment], participants: list[str], judge: str,
                 runner: Runner, report: Callable[[DecisionAnalysis], None], *,
                 repository: str = context_prompt(None),
                 design: str = design_context(None),
                 accepted: Sequence[ProjectDecision] = (),
                 carried: Mapping[str, QuestionAnalysis] | None = None) -> None:
        self.carried = dict(carried or {})
        super().__init__(council_id, participants, judge, runner, report,
                         start_analysis(participants, judge, choices, self.carried.values()))
        self.idea = idea
        self.repository = repository
        self.design = design
        self.accepted = accepted_prompt(accepted)
        self.scope = scope
        self.choices = {choice.question_id: choice.proposal for choice in choices}
        self.found = found_by_question(proposals, choices)
        self.fragments = {fragment.id: fragment for fragment in fragments}

    def work(self) -> dict[str, Any]:
        limits = [f for f in self.fragments.values() if f.label in ("constraint", "risk")]
        known = as_json([{"id": f"F{f.id}", "type": f.label, "text": f.text} for f in limits])
        failures: dict[str, list[str]] = {}
        asked = False
        for question in self.scope:
            if question.id in self.carried:
                continue
            offered = self._offered(question)
            selected = self.choices.get(question.id)
            if not offered and selected is None:
                # Unresolved вопрос без вариантов: сравнивать нечего, рекомендовать — тоже.
                verdict = Analysis("none", None)
            else:
                asked = True
                verdict = self._analyze(question, offered, selected, known, limits, failures)
            with self._lock:
                self.state.analyses.append(analysis_of_question(question, verdict))
                self._publish()
        if not asked:
            self._skip(StepName.decision_analysis)
            self._skip(StepName.decision_judge)
        return {"analyses": self.state.analyses}

    def _analyze(self, question: OpenQuestion, offered: list[dict], selected: str | None,
                 known: str, limits: list[LabeledFragment],
                 failures: dict[str, list[str]]) -> Analysis:
        context = DecisionContext(
            frozenset(f.id for f in limits if f.label == "constraint"),
            frozenset(f.id for f in limits if f.label == "risk"),
            frozenset(q.id for q in self.scope if q.id != question.id),
            frozenset(proposal["id"] for proposal in offered), selected)
        values = {
            "idea": self.idea,
            "question": as_json({"id": question.id, "text": question.text}),
            "proposals": as_json(offered),
            "user_selection": as_json(
                None if selected is None else {"proposal_id": selected, "rationale": None}),
            "constraints_and_risks": known,
            "related_questions": as_json([self._related(q) for q in self.scope
                                          if q.id != question.id]),
            "repository": self.repository,
            "design": self.design,
        }
        answers = self._ask_all(StepName.decision_analysis,
                                render("decision_analysis", **values,
                                       accepted_decisions=self.accepted),
                                partial(analysis_of, context=context))
        self._keep_failures(StepName.decision_analysis, question.id, failures)
        distinct = {as_json(analysis_prompt(a)): analysis_prompt(a) for a in answers.values()}
        variants = shuffled(list(distinct.values()))
        prompt = render("decision_judge", **values, accepted_adrs=self.accepted,
                        decision_analyses=as_json(
                            [{"analysis": n, **v} for n, v in enumerate(variants, 1)]))
        return self._ask_judge(StepName.decision_judge, prompt,
                               partial(judged_analysis, context=context))

    def _offered(self, question: OpenQuestion) -> list[dict]:
        return offered(question, self.fragments, self.found)

    def _related(self, question: OpenQuestion) -> dict:
        """Другой вопрос потока и что по нему выбрал человек."""
        selected = self.choices.get(question.id)
        text = next((p["text"] for p in self._offered(question) if p["id"] == selected), None)
        return {"id": question.id, "text": question.text,
                "status": "unresolved" if selected is None else "selected",
                "selected_proposal": None if selected is None else {"id": selected, "text": text}}


def analysis_of_question(question: OpenQuestion, verdict: Analysis) -> QuestionAnalysis:
    return QuestionAnalysis(
        question_id=question.id, verdict=verdict.kind, proposal=verdict.proposal,
        constraint_conflicts=list(verdict.conflicts), risk_ids=list(verdict.risks),
        depends_on=list(verdict.depends_on), reason=verdict.reason or None,
        rationale=verdict.rationale)


def offered(question: OpenQuestion, fragments: dict[int, LabeledFragment],
            found: dict[str, list[Proposal]]) -> list[dict]:
    """Варианты вопроса для промпта: из текста группы, найденные к нему советом и свой вариант
    человека — у него только текст."""
    group = [{"id": f"F{i}", "source": "group", "text": fragments[i].text}
             for i in question.proposal_ids if i in fragments]
    council = [{"id": p.id, "source": "council", "text": p.text, "reason": p.reason,
                "constraint_ids": as_ids(p.constraint_ids), "risk_ids": as_ids(p.risk_ids),
                "depends_on_question_ids": p.depends_on}
               if p.source == "council" else {"id": p.id, "source": "user", "text": p.text}
               for p in found.get(question.id, [])]
    return group + council


def adr_id(n: int) -> str:
    """Решение по n-му вопросу отбора: ADR-n — тот же номер, что у карточки на экране."""
    return f"ADR-{n}"


def decided_context(scope: list[OpenQuestion], decisions: dict[str, Decision],
                    found: dict[str, list[Proposal]], fragments: dict[int, LabeledFragment]
                    ) -> tuple[list[dict], list[dict], list[LabeledFragment]]:
    """Вопросы отбора с их статусом, принятые решения (ADR-n — по n-му вопросу отбора, с
    выбранным вариантом и обоснованием) и ограничения с рисками группы — для промптов."""
    limits = [f for f in fragments.values() if f.label in ("constraint", "risk")]
    questions, adrs = [], []
    for n, question in enumerate(scope, 1):
        options = offered(question, fragments, found)
        decision = decisions.get(question.id)
        accepted = decision is not None and decision.proposal is not None
        questions.append({"id": question.id, "text": question.text,
                          "status": "decided" if accepted else "open",
                          "adr_id": adr_id(n) if accepted else None, "proposals": options})
        if accepted:
            adrs.append({"id": adr_id(n), "question_id": question.id,
                         "question": question.text, "proposal_id": decision.proposal,
                         "decision": next((o["text"] for o in options
                                           if o["id"] == decision.proposal), None),
                         "rationale": decision.rationale})
    return questions, adrs, limits


def limits_prompt(limits: list[LabeledFragment]) -> str:
    return as_json([{"id": f"F{f.id}", "type": f.label, "text": f.text} for f in limits])


class OutcomeRun(CouncilRun[OutcomeDiscovery]):
    """Итоги потока: участники по отдельности собирают зафиксированные решения в законченные
    изменения системы, судья сводит их наборы в итоговый. Итог, которому не хватает решения
    открытого вопроса, заблокирован им — недостающее не додумывается. Решения — ADR-n по
    номеру вопроса в отборе; открытый вопрос решения не имеет. Какие решения не вошли ни в
    один итог, считает код, а не модель.

    kept — закреплённые итоги (были готовы, их решения те же): модели видят их данностью и
    собирают только остальное, а если новое решение такой итог задевает — говорят об этом
    (touches), и решает человек. Закреплённые сохраняют номера, новые нумеруются дальше."""

    what = "сборка итогов"

    def __init__(self, council_id: str, idea: str, scope: list[OpenQuestion],
                 decisions: list[Decision], proposals: ProposalDiscovery | None,
                 fragments: list[LabeledFragment], participants: list[str], judge: str,
                 runner: Runner, report: Callable[[OutcomeDiscovery], None], *,
                 choices: Sequence[Choice] = (),
                 repository: str = context_prompt(None),
                 design: str = design_context(None),
                 kept: Sequence[Outcome] = ()) -> None:
        """choices — выбор человека: из него свои варианты, которыми можно было решить."""
        self.kept = list(kept)
        super().__init__(council_id, participants, judge, runner, report,
                         start_outcomes(participants, judge, decisions, self.kept))
        self.idea = idea
        self.repository = repository
        self.design = design
        self.scope = scope
        self.decisions = {decision.question_id: decision for decision in decisions}
        self.found = found_by_question(proposals, choices)
        self.fragments = {fragment.id: fragment for fragment in fragments}

    def work(self) -> dict[str, Any]:
        questions, adrs, limits = decided_context(self.scope, self.decisions, self.found,
                                                  self.fragments)
        context = OutcomeContext(
            frozenset(adr["id"] for adr in adrs),
            frozenset(f.id for f in limits if f.label == "constraint"),
            frozenset(f.id for f in limits if f.label == "risk"),
            frozenset(q["id"] for q in questions if q["status"] == "open"),
            {same_question(q.text): q.id for q in self.scope},
            {outcome.id: frozenset(outcome.adr_ids) for outcome in self.kept})
        values = {
            "idea": self.idea,
            "questions_and_proposals": as_json(questions),
            "accepted_adrs": as_json(adrs),
            "fixed_outcomes": as_json([{
                "id": outcome.id, "title": outcome.title, "behavior": outcome.behavior,
                "adr_ids": outcome.adr_ids,
                "constraint_ids": [f"F{i}" for i in outcome.constraint_ids],
                "risk_ids": [f"F{i}" for i in outcome.risk_ids],
                "acceptance_criteria": outcome.acceptance_criteria} for outcome in self.kept]),
            "constraints_and_risks": limits_prompt(limits),
            "repository": self.repository,
            "design": self.design,
        }
        answers = self._ask_all(StepName.outcome_discovery, render("outcome_discovery", **values),
                                partial(assembly_of, context=context))
        # Одинаковые наборы — один; порядок итогов — как у первого, кто его прислал.
        sets: dict[str, Any] = {}
        for found in answers.values():
            sets.setdefault(same_assembly(found), found)
        if len(answers) > 1 and len(sets) == 1:
            self._skip(StepName.outcome_judge)
            chosen = next(iter(sets.values()))
        else:
            variants = shuffled([{"outcomes": [outcome_prompt(c) for c in found.outcomes],
                                  "touches": [touch_prompt(t) for t in found.touches]}
                                 for found in sets.values()])
            prompt = render("outcome_judge", **values, outcome_candidates=as_json(
                [{"candidate": n, **v} for n, v in enumerate(variants, 1)]))
            chosen = self._ask_judge(StepName.outcome_judge, prompt,
                                     partial(assembly_of, context=context))
        first = max((int(outcome.id[1:]) for outcome in self.kept), default=0) + 1
        outcomes = [*self.kept, *(
            Outcome(id=f"O{n}", title=c.title, behavior=c.behavior,
                    adr_ids=list(c.adr_ids), constraint_ids=list(c.constraint_ids),
                    risk_ids=list(c.risk_ids), acceptance_criteria=list(c.criteria),
                    blocked_by=list(c.blocked_by),
                    gaps=[OutcomeGap(question=g.question, reason=g.reason) for g in c.gaps])
            for n, c in enumerate(chosen.outcomes, first))]
        covered = {name for outcome in outcomes for name in outcome.adr_ids}
        return {"outcomes": outcomes,
                "touched": [OutcomeTouch(outcome_id=t.outcome_id, adr_ids=list(t.adr_ids),
                                         reason=t.reason) for t in chosen.touches],
                "uncovered_adr_ids": [adr["id"] for adr in adrs if adr["id"] not in covered]}


class RepositoryRun(CouncilRun[RepositoryScan]):
    """Скан репозиториев под идею потока. Inventory — список файлов каждой рабочей копии на
    момент запуска; модели читают не их, а снимок: только файлы inventory, без .git и
    игнорируемого, у нескольких копий — каждая в своей папке, неподвижный, пока идёт скан, —
    только на чтение. Его отпечаток ключует ответы. Участники
    по отдельности устанавливают, как система устроена сейчас, судья проверяет их находки по
    коду и сводит в одну карту. Если он видит существенные пробелы, участники доисследуют
    именно их — до двух раз; судья видит и прежнюю карту. Одинаковые находки судья видит
    одним: число согласных — не довод. Снимок удаляется, когда скан закончен."""

    what = "скан репозитория"

    def __init__(self, council_id: str, idea: str, sources: Sequence[Source],
                 fragments: list[LabeledFragment], participants: list[str], judge: str,
                 runner: Runner, report: Callable[[RepositoryScan], None], *,
                 copy: Copier = snapshot_all) -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start_scan(participants, judge, idea, sources))
        self.idea = idea
        self.sources = sources
        self.fragments = fragments
        self.copy = copy

    def work(self) -> dict[str, Any]:
        with self._reading(self.sources, self.copy) as folder:
            context = RepositoryContext(self.copied, (folder,))
            values = {
                "idea": self.idea,
                "fragments": fragments_prompt(self.fragments),
                "inventory": sources_prompt(self.sources),
                "commit_sha": commits_prompt(self.sources),
            }
            return self._explored(StepName.repository_discovery, StepName.repository_judge,
                                  values, partial(map_of, context=context),
                                  partial(judged_map, context=context), map_prompt)


def accepted_prompt(decisions: Sequence[ProjectDecision]) -> str:
    """Принятые решения проекта, отобранные человеком для потока, — для промптов вопросов,
    вариантов и решений: номер, к какой идее, вопрос, решение, действует ли оно (заменённое —
    и каким), насколько и почему относится."""
    return as_json([{"adr_id": d.adr_id, "idea": d.idea, "question": d.question,
                     "decision": d.decision, "status": d.status,
                     "superseded_by": d.superseded_by, "relevance": d.relevance,
                     "reason": d.reason}
                    for d in decisions])


def fragments_prompt(fragments: Iterable[LabeledFragment]) -> str:
    return as_json([{"id": f"F{f.id}", "type": f.label, "text": f.text} for f in fragments])


class DesignRun(CouncilRun[DesignScan]):
    """Скан макета Figma под идею потока. Снимок файла совет делает сам, через REST API, с
    одной версии: страницы из ссылок целиком — структура и узлы как есть, — картинки фреймов
    и сводка файла. Модели читают снимок, а не Figma: все видят одно и то же, ответы ключуются
    его отпечатком, а токена и сети в ходе модели нет. Дальше — как у скана репозитория:
    участники по отдельности, судья проверяет по снимку и сводит, доисследование — до двух
    раз. Снимок удаляется, когда скан закончен."""

    what = "скан макета"

    def __init__(self, council_id: str, idea: str, links: Sequence[Link],
                 fragments: list[LabeledFragment], participants: list[str], judge: str,
                 runner: Runner, report: Callable[[DesignScan], None], *,
                 fetch: Fetcher) -> None:
        super().__init__(council_id, participants, judge, runner, report,
                         start_design(participants, judge, idea, links))
        self.idea = idea
        self.links = links
        self.fragments = fragments
        self.fetch = fetch

    def work(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="council-design-") as place:
            folder = Path(place)
            try:
                shot = figma_snapshot(self.links, self.fetch, folder)
            except FigmaError as exc:
                raise StageFailed(str(exc)) from exc
            self.fingerprint = shot.fingerprint
            with self._lock:
                self.state.source = shot.source
                self._publish()
            context = DesignContext(shot.nodes, shot.pages)
            values = {"idea": self.idea, "fragments": fragments_prompt(self.fragments),
                      "figma_source": shot.prompt}
            self.workspace = folder
            try:
                return self._explored(StepName.design_discovery, StepName.design_judge, values,
                                      partial(design_map_of, context=context),
                                      partial(judged_design, context=context), design_prompt)
            finally:
                self.workspace = None


class IssueRun(CouncilRun[IssueDiscovery]):
    """Нарезка утверждённых итогов на задачи для coding agents: участники по отдельности,
    судья сводит их нарезки в итоговый набор. Если шаг «Репозиторий» пройден сканом, модели
    читают снимок тех же рабочих копий заново (_reading) — точки входа и нынешнее состояние
    проверяются по коду, а карта скана идёт им в помощь; без скана кода нет. Задачу, которой
    не хватает решения, блокирует пробел или открытый вопрос — недостающее не додумывается.
    Номера задач (I-n) и пробелов (G-n) — по порядку у судьи; какие итоги не вошли ни в одну
    задачу, считает код, а не модель.

    carried — задачи прежней нарезки тех же итогов, которые ничто не держит: они уже в
    разработке, их не нарезают заново, а модели видят их данностью; cut — номера итогов, которые
    ещё надо нарезать (остальные целиком покрыты перенесёнными задачами). Новые задачи нумеруются
    дальше перенесённых."""

    what = "нарезка на задачи"

    def __init__(self, council_id: str, stream: Stream, fragments: list[LabeledFragment],
                 participants: list[str], judge: str, runner: Runner,
                 report: Callable[[IssueDiscovery], None], *,
                 sources: Sequence[Source] = (),
                 repository: str = context_prompt(None),
                 design: str = design_context(None),
                 copy: Copier = snapshot_all,
                 carried: Sequence[Issue] = (), cut: Iterable[str] | None = None) -> None:
        """stream — поток с утверждёнными итогами: его идея, отбор, решения, варианты и итоги."""
        super().__init__(council_id, participants, judge, runner, report,
                         start_issues(participants, judge, stream.outcomes.run,
                                      stream.decisions or [], carried))
        self.carried = list(carried)
        self.cut = set(cut) if cut is not None else {o.id for o in stream.outcomes.outcomes}
        self.idea = stream.idea.text
        self.scope = stream.scope or []
        self.decisions = {decision.question_id: decision for decision in stream.decisions or []}
        self.found_proposals = found_by_question(stream.proposals, stream.choices)
        self.outcomes = stream.outcomes.outcomes
        self.fragments = {fragment.id: fragment for fragment in fragments}
        self.sources = sources
        self.repository = repository
        self.design = design
        self.copy = copy

    def work(self) -> dict[str, Any]:
        if not self.cut:
            # Все итоги покрыты перенесёнными задачами: ни моделей, ни кода не нужно.
            self._skip(StepName.issue_discovery)
            self._skip(StepName.issue_judge)
            return self._numbered(IssueAnswer((), ()))
        with self._reading(self.sources, self.copy) as folder:
            if folder is not None:
                # Снимок есть — модели читают этот код: с каких он коммитов и с правками ли.
                with self._lock:
                    self.state.code = True
                    self.state.sources = [scanned(source) for source in self.sources]
                    self._publish()
            return self._cut()

    def _cut(self) -> dict[str, Any]:
        questions, adrs, limits = decided_context(self.scope, self.decisions,
                                                  self.found_proposals, self.fragments)
        uncut = [outcome for outcome in self.outcomes if outcome.id in self.cut]
        context = IssueContext(
            frozenset(outcome.id for outcome in uncut),
            frozenset(adr["id"] for adr in adrs),
            frozenset(f.id for f in limits if f.label == "constraint"),
            frozenset(f.id for f in limits if f.label == "risk"),
            frozenset(q["id"] for q in questions if q["status"] == "open"),
            {same_question(q.text): q.id for q in self.scope},
            {o.id: Parent(tuple(o.adr_ids), tuple(o.constraint_ids), tuple(o.risk_ids),
                          tuple(o.blocked_by), tuple((g.question, g.reason) for g in o.gaps),
                          tuple(o.acceptance_criteria))
             for o in uncut},
            frozenset(issue.id for issue in self.carried))
        opened = {q["id"]: {"id": q["id"], "question": q["text"], "proposals": q["proposals"]}
                  for q in questions if q["status"] == "open"}
        values = {
            "idea": self.idea,
            "outcomes": as_json([{
                "id": outcome.id, "title": outcome.title, "behavior": outcome.behavior,
                "adr_ids": outcome.adr_ids,
                "constraint_ids": [f"F{i}" for i in outcome.constraint_ids],
                "risk_ids": [f"F{i}" for i in outcome.risk_ids],
                "acceptance_criteria": outcome.acceptance_criteria,
                # Открытый вопрос, что держит итог, — текстом и с вариантами: по одному
                # номеру модели не поймут, чего не хватает и что от него зависит.
                "blocked_by": [opened.get(name, name) for name in outcome.blocked_by],
                "gaps": [gap.model_dump() for gap in outcome.gaps]} for outcome in uncut]),
            "accepted_adrs": as_json(adrs),
            "fixed_issues": as_json([{
                "id": issue.id, "title": issue.title, "user_story": issue.user_story,
                "outcome_ids": issue.outcome_ids, "scope": issue.scope}
                for issue in self.carried]),
            "constraints_and_risks": limits_prompt(limits),
            "repository_context": self._code_note() + self.repository,
            "design": self.design,
        }
        parse = partial(issue_set, context=context)
        answers = self._ask_all(StepName.issue_discovery, render("issue_discovery", **values),
                                parse)
        # Одинаковые наборы — один; порядок — как у первого, кто его прислал.
        sets: dict[str, IssueAnswer] = {}
        for found in answers.values():
            sets.setdefault(same_issues(found), found)
        if len(answers) > 1 and len(sets) == 1:
            self._skip(StepName.issue_judge)
            chosen = next(iter(sets.values()))
        else:
            fixed = [issue.id for issue in self.carried]
            variants = shuffled([issue_prompt(answer, fixed) for answer in sets.values()])
            prompt = render("issue_judge", **values, issue_candidates=as_json(
                [{"candidate": n, **v} for n, v in enumerate(variants, 1)]))
            chosen = self._ask_judge(StepName.issue_judge, prompt, parse)
        return self._numbered(chosen)

    def _code_note(self) -> str:
        """Где код: снимок — текущий каталог хода; без скана его нет."""
        if not self.sources:
            return ""
        if len(self.sources) == 1:
            where = f"её снимок, только на чтение, коммит {commits_prompt(self.sources)}"
        else:
            where = ("их снимок, только на чтение, каждая — в своей папке (folder в карте ниже), "
                     f"коммиты:\n{commits_prompt(self.sources)}\n")
        return (f"Код рабочих копий — в текущем каталоге: {where}. Проверяй по нему точки входа "
                f"и текущее состояние; карта ниже — с шага Repository Discovery.\n\n")

    def carried_only(self) -> IssueDiscovery:
        """Нарезка, когда резать нечего: только перенесённые задачи, ни моделей, ни кода. Без
        отчёта — её можно собрать и под замком совета, где отчёт ждал бы тот же замок."""
        return self.state.model_copy(update={
            "state": "done", "steps": [step.model_copy(update={"state": "skipped", "runs": []})
                                       for step in self.state.steps],
            **self._numbered(IssueAnswer((), ()))})

    def _numbered(self, chosen: IssueAnswer) -> dict[str, Any]:
        """Номера по порядку: задачи — I-n дальше перенесённых, пробелы — G-n (в ответе они уже
        по порядку); зависимости — по новым номерам. Перенесённые — как были."""
        first = max((int(issue.id[1:]) for issue in self.carried), default=0) + 1
        renamed = {issue.name: f"I{n}" for n, issue in enumerate(chosen.issues, first)
                   if issue.name}
        issues = [Issue(id=f"I{n}", title=c.title, user_story=c.user_story,
                        main_entry_points=list(c.entry_points), current_state=c.current_state,
                        scope=list(c.scope), outcome_ids=list(c.outcome_ids),
                        adr_ids=list(c.adr_ids), constraint_ids=list(c.constraint_ids),
                        risk_ids=list(c.risk_ids),
                        depends_on=[renamed.get(name, name) for name in c.depends_on],
                        blocked_by=list(c.blocked_by), acceptance_criteria=list(c.criteria))
                  for n, c in enumerate(chosen.issues, first)]
        gaps = [IssueGap(id=f"G{n}", question=g.question, reason=g.reason,
                         outcome_ids=list(g.outcome_ids)) for n, g in enumerate(chosen.gaps, 1)]
        issues = [*self.carried, *issues]
        covered = {name for issue in issues for name in issue.outcome_ids}
        return {"issues": issues, "gaps": gaps, "kept": [issue.id for issue in self.carried],
                "cut": {outcome.id: outcome_print(outcome) for outcome in self.outcomes},
                "uncovered_outcome_ids": [o.id for o in self.outcomes if o.id not in covered]}


def translating(judge: str) -> list[Step]:
    """Перевод заметок — один ход судьи."""
    return [Step(name=StepName.notes_translation, runs=[ModelRun(model=judge)])]


class NotesRun(CouncilRun[NotesDraft]):
    """Перевод черновика выгрузки на язык документации (COUNCIL_NOTES_LANGUAGE): один ход
    судьи, все новые тексты разом. Номера заметок и задач в переводе — те же, иначе ответ
    негодный. После перевода совет заново смотрит, что с каждой заметкой будет при записи."""

    what = "перевод заметок"

    def __init__(self, council_id: str, draft: NotesDraft, previous: NotesExport | None,
                 catalog: Catalog, root: Path, judge: str, runner: Runner,
                 report: Callable[[NotesDraft], None]) -> None:
        super().__init__(council_id, [], judge, runner, report, draft)
        self.previous = {note.key: note for note in previous.notes} if previous else {}
        self.catalog = catalog
        self.root = root

    def work(self) -> dict[str, Any]:
        sources = untranslated(self.state.notes)
        found: dict[str, str] = {}
        if sources:
            prompt = render("notes_translation", language=self.state.language,
                            notes=as_json([{"key": key, "text": text}
                                           for key, text in sources.items()]))
            found = self._ask_judge(StepName.notes_translation, prompt,
                                    partial(translations, sources=sources))
        else:
            self._skip(StepName.notes_translation)
        notes = [settled(note.model_copy(update={"text": found.get(note.key, note.text)}),
                         previous_of(note, self.previous), self.catalog, self.root)
                 for note in self.state.notes]
        return {"notes": notes}


class DecisionsRun(CouncilRun[DecisionsSearch]):
    """Отбор прошлых решений проекта для потока. Каталог — ADR из заметок с идеей, вопросом и
    статусом; след в коде к ним совет собирает сам, git log по файлам утверждённой карты
    репозитория. Участники по отдельности отбирают относящиеся к идее, судья проверяет только
    их кандидатов; одинаковый отбор — судья не нужен. Решения, которые выгрузил сам поток, —
    не «прошлые»: их в каталоге нет."""

    what = "отбор решений проекта"

    def __init__(self, council_id: str, stream: Stream, fragments: list[LabeledFragment],
                 participants: list[str], judge: str, runner: Runner,
                 report: Callable[[DecisionsSearch], None], *, catalog: Catalog,
                 scan: RepositoryScan | None, own: Sequence[str] = ()) -> None:
        super().__init__(council_id, participants, judge, runner, report, start_decisions(
            participants, judge, stream.idea.text, repository_of(stream), design_of(stream)))
        self.idea = stream.idea.text
        self.fragments = fragments
        self.catalog = catalog
        self.scan = scan
        self.own = list(own)

    def work(self) -> dict[str, Any]:
        commits = scanned_commits(self.scan) if self.scan and self.scan.result else {}
        files = evidence_files(self.scan, commits) if commits else []
        trails = trails_of(files, issue_outcomes(self.catalog), commits) if files else {}
        catalog = records(self.catalog, trails, self.own)
        with self._lock:
            self.state.catalog = len(catalog)
            self.state.fingerprint = catalog_print(self.catalog, self.own)
            self.state.traced = sum(1 for record in catalog if record.found_in_code)
            self._publish()
        values = {"idea": self.idea, "fragments": fragments_prompt(self.fragments),
                  "adr_catalog": as_json(catalog_prompt(catalog))}
        answers = self._ask_all(StepName.project_decisions_discovery,
                                render("project_decisions_discovery", **values),
                                partial(selected_decisions, catalog=catalog))
        lists = list(answers.values())
        if len(lists) > 1 and same_selection(lists):
            self._skip(StepName.project_decisions_judge)
            return {"decisions": lists[0]}
        proposed = {decision.adr_id for found in lists for decision in found}
        candidates = shuffled([[{"adr_id": d.adr_id, "relevance": d.relevance,
                                 "reason": d.reason} for d in found] for found in lists])
        prompt = render("project_decisions_judge", **values, discovery_results=as_json(
            [{"agent": n, "decisions": found} for n, found in enumerate(candidates, 1)]))
        return {"decisions": self._ask_judge(
            StepName.project_decisions_judge, prompt,
            partial(selected_decisions, catalog=catalog, allowed=proposed))}


def repository_of(stream: Stream) -> str:
    step = stream.repository
    return step.scan_run if step is not None and step.by == "scan" else SKIPPED


def design_of(stream: Stream) -> str:
    step = stream.design
    return step.scan_run if step is not None and step.by == "scan" else SKIPPED
