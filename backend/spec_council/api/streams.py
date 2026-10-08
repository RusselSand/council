"""Потоки — подтверждённые группы. Подтверждение заводит поток на каждую группу и сразу
запускает поиск идеи у тех, в тексте которых её нет. Человек утверждает идею потока —
найденную советом, свою или записанную в тексте. Дальше необязательный шаг «Репозиторий»:
совет сканирует рабочую копию под идею, человек утверждает карту или пропускает шаг, — и
совет сразу ищет открытые вопросы, а карта идёт во все следующие шаги. Человек отбирает, какие
из них решать, и добавляет свои, — и совет сразу ищет к ним новые варианты ответа. Человек
выбирает по варианту на вопрос или оставляет его unresolved — и совет сразу проверяет выбор, а
для unresolved подбирает вариант из тех, что есть. Человек фиксирует решения — и совет сразу
собирает из них итоги. Каждый шаг утверждают заново — то, что ниже по цепочке, ищется заново."""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from ..agents import AgentRunner
from ..config import AppConfig
from ..decisions import RATIONALE_MAX
from ..deps import AgentsDep, ConfigDep, Launcher, LauncherDep, RepositoriesDep, Store, StoreDep
from ..ideas import IDEA_MAX
from ..models import (
    SKIPPED,
    STREAM_RUNS,
    ApproveChoices,
    ApproveDecisions,
    ApproveIdea,
    ApproveRepository,
    ApproveScope,
    Choice,
    Council,
    CouncilStatus,
    Decision,
    DecisionAnalysis,
    DecisionDraft,
    Group,
    GroupsEdit,
    IdeaDiscovery,
    LabeledFragment,
    OpenQuestion,
    OutcomeDiscovery,
    ProposalDiscovery,
    QuestionDiscovery,
    RepositoryScan,
    RepositoryStep,
    ScanRepository,
    Stream,
    StreamIdea,
)
from ..pipeline import (
    CouncilRun,
    DecisionRun,
    IdeaRun,
    OutcomeRun,
    ProposalRun,
    QuestionRun,
    RepositoryRun,
    Runner,
    choices_key,
    decisions_key,
    scope_key,
    start_analysis,
    start_idea,
    start_outcomes,
    start_proposals,
    start_questions,
    start_scan,
)
from ..questions import QUESTION_MAX, same_question
from ..repository import RepositoryError, context_prompt, working_copy
from .councils import (
    CANNOT_START,
    MISSING,
    NOT_FOUND,
    PROBE_ATTEMPTS,
    RunState,
    Slot,
    council_lock,
    launched,
    lineup,
    offline,
    reporter,
    running,
    start_run,
)
from .groups import NOT_THESE_GROUPS, current, outdated

router = APIRouter(prefix="/councils", tags=["streams"])

NO_STREAM = {409: {"description": "Групп уже других: потока нет, или группы не подтверждены"}}
CHANGING = {503: {"description": "Состав совета меняется прямо сейчас"}}
NO_IDEA = "Сначала утвердите идею потока"
RESLICED = "Типы фрагментов поменялись после раскладки — сначала разложите заново"
# Всё, что ниже шага «Репозиторий»: другой скан или другая идея это сбрасывает.
BELOW_REPOSITORY = {"questions": None, "scope": None, "proposals": None, "choices": None,
                    "analysis": None, "decisions": None, "outcomes": None}


@router.post("/{council_id}/structure/confirm",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **CHANGING})
def confirm_groups(council_id: str, edit: GroupsEdit, store: StoreDep, config: ConfigDep,
                   agents: AgentsDep, launch: LauncherDep) -> Council:
    """Человек подтвердил группы: каждая становится потоком, совет переходит к потокам.
    Подтверждает то, что видел: ту же раскладку и версию групп. Подтверждённые раньше —
    ответ тот же, совет не меняется.

    У групп без идеи совет сразу её ищет. Подтверждение от этого не зависит: нет
    подключения к моделям — поиск записан упавшим с причиной, и его можно повторить."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        lacking = any(group.missing_idea for group in council.structure.groups)
        return council, council.streams is None and lacking

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        if council.streams is not None:
            return council, []  # подтвердили раньше или в другой вкладке
        lacking = [group for group in council.structure.groups if group.missing_idea]
        runs = {} if missing else {group.id: idea_run(council, group, agents, store)
                                   for group in lacking}
        streams = [Stream(group=group.id, discovery=searched(council, group, runs, missing))
                   for group in council.structure.groups]
        return store.update_council(
            council_id, {"streams": streams, "status": CouncilStatus.review}), list(runs.values())

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


def searched(council: Council, group: Group, runs: dict[str, IdeaRun],
             missing: list[str]) -> IdeaDiscovery | None:
    """Поиск идеи потока при подтверждении: у группы с идеей его нет, без подключения —
    упавший с причиной, иначе — идущий."""
    if not group.missing_idea:
        return None
    if missing:
        return unconnected(start_idea(council.participants, council.judge), missing)
    return runs[group.id].state.model_copy(deep=True)


@router.post("/{council_id}/streams/{group}/discovery", status_code=202,
             responses={**NOT_FOUND, **CANNOT_START, **NO_STREAM})
def start_discovery(council_id: str, group: str, store: StoreDep, config: ConfigDep,
                    agents: AgentsDep, launch: LauncherDep) -> Council:
    """Ищет идею потока заново: после сбоя или если при подтверждении не было подключения
    к моделям. Повтор не платит второй раз за ответы, которые модели уже дали."""
    def ready(council: Council) -> None:
        stream = stream_in(council, group)
        if not group_of(council, group).missing_idea:
            raise HTTPException(422, "Идея группы записана в тексте — искать нечего")
        if stream.idea is not None:
            raise HTTPException(409, "Идея потока уже утверждена")
        if outdated(council.slicing, council.structure):
            raise HTTPException(409, RESLICED)

    return start_run(
        council_id, store, config, agents, launch, discovery(group), ready, None,
        lambda council, report: IdeaRun(council.id, fragments_of(council, group_of(council, group)),
                                        council.participants, council.judge, agents, report),
    )


@router.post("/{council_id}/streams/{group}/idea",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM,
                        422: {"description": "Пустая или слишком длинная идея, или идею из "
                                             "текста пытаются править"},
                        423: {"description": "Совет ещё работает с прежней идеей"}})
def approve_idea(council_id: str, group: str, edit: ApproveIdea, store: StoreDep) -> Council:
    """Человек утверждает идею потока; дальше — шаг «Репозиторий». Утвердить заново —
    поменять идею: скан, вопросы и всё ниже были к прежней и сбрасываются; та же идея их не
    трогает. Идея, записанная в тексте, не правится: это фрагменты группы."""
    with council_lock:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        idea = idea_for(council, stream, group, edit.text)
        changes: dict = {"idea": idea}
        if idea_changed(stream, idea):
            # Другую идею, пока ниже по цепочке совет ещё работает, не утвердить: его ход
            # пришлось бы бросить. Ту же — можно: это повтор (другая вкладка, потерянный ответ).
            if below_running(stream, "scan"):
                raise HTTPException(423, "Совет ещё работает с прежней идеей — дождитесь его")
            changes |= {"scan": None, "repository": None, **BELOW_REPOSITORY}
        council = store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update=changes))})
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def idea_for(council: Council, stream: Stream, group: str, text: str | None) -> StreamIdea:
    """Идея, которую утверждают: из текста — его фрагменты-идеи, иначе — формулировка
    человека. Пока совет ищет идею, утверждать рано."""
    target = group_of(council, group)
    if not target.missing_idea:
        if text is not None:
            raise HTTPException(422, "Идея группы записана в тексте — её не правят")
        texts = {fragment.id: fragment.text for fragment in council.slicing.fragments}
        return StreamIdea(text=" ".join(texts[i] for i in target.idea_fragment_ids),
                          by="text", evidence=target.idea_fragment_ids)
    if running(stream.discovery):
        raise HTTPException(409, "Совет ещё ищет идею — дождитесь его")
    return idea_of(text, stream.discovery)


def idea_changed(stream: Stream, idea: StreamIdea) -> bool:
    """Утверждают другую идею, чем была: всё ниже было к прежней."""
    return stream.idea is None or stream.idea.text != idea.text


@router.post("/{council_id}/streams/{group}/repository/scan", status_code=202,
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        409: {"description": "Идея не утверждена или её поменяли, скан уже "
                                             "идёт или группы уже другие"},
                        422: {"description": "Путь не к рабочей копии git"},
                        423: {"description": "Совет ещё работает ниже по цепочке"}})
def scan_repository(council_id: str, group: str, edit: ScanRepository, store: StoreDep,
                    config: ConfigDep, agents: AgentsDep, launch: LauncherDep,
                    repositories: RepositoriesDep) -> Council:
    """Совет сканирует репозиторий под идею потока: inventory рабочей копии — сейчас, потом
    участники и судья исследуют код, только читая его. Скан заново — шаг «Репозиторий» заново:
    утверждённая карта, вопросы и всё ниже сбрасываются. Повтор после сбоя берёт уже
    оплаченные ответы даром. Нет подключения к моделям — скан записан упавшим с причиной.
    Идея — та, что человек видел (seen_idea)."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        if stream.idea is None:
            raise HTTPException(409, NO_IDEA)
        seen_idea(stream, edit)
        if running(stream.scan):
            raise HTTPException(409, "Скан уже идёт")
        if below_running(stream, "questions"):
            raise HTTPException(423, "Совет ещё работает ниже по цепочке — дождитесь его")
        if outdated(council.slicing, council.structure):
            raise HTTPException(409, RESLICED)
        return council, True

    # Сначала дешёвое: устаревший или лишний запрос не должен ждать git на большой рабочей
    # копии ради 404 и 409. Под замком всё проверится ещё раз.
    with council_lock:
        plan()
    try:
        found = working_copy(edit.path, repositories)
    except RepositoryError as exc:
        raise HTTPException(422, str(exc)) from None

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        runs: list[CouncilRun] = []
        if missing:
            scan = unconnected(start_scan(council.participants, council.judge, stream.idea.text,
                                          edit.path, found), missing)
        else:
            runs = [RepositoryRun(council.id, stream.idea.text, edit.path, found,
                                  fragments_of(council, group_of(council, group)),
                                  council.participants, council.judge, agents,
                                  reporter(store, council.id, scanning(group)))]
            scan = runs[0].state.model_copy(deep=True)
        changes = {"scan": scan, "repository": None, **BELOW_REPOSITORY}
        return store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update=changes))}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


@router.post("/{council_id}/streams/{group}/repository",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        409: {"description": "Групп уже других, сканировали заново или идею "
                                             "поменяли"},
                        423: {"description": "Совет ещё сканирует или работает ниже"}})
def approve_repository(council_id: str, group: str, edit: ApproveRepository, store: StoreDep,
                       config: ConfigDep, agents: AgentsDep, launch: LauncherDep) -> Council:
    """Человек проходит шаг «Репозиторий»: утверждает карту скана или пропускает шаг, — и
    совет сразу ищет открытые вопросы, а карта идёт во все следующие шаги. Пройти шаг заново
    иначе — вопросы и всё ниже ищутся заново; так же — ничего не меняется. Карта — того скана,
    что был на экране: сканировали заново — 409; идея — та, что человек видел (seen_idea)."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        seen_idea(stream, edit)
        step = repository_step(stream, edit)
        anew = asks_anew(stream, step)
        if anew and below_running(stream, "scan"):
            raise HTTPException(423, "Совет ещё работает с этим потоком — дождитесь его")
        return council, anew

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        step = repository_step(stream, edit)
        changes: dict = {"repository": step}
        runs: list[CouncilRun] = []
        if asks_anew(stream, step):
            ready = stream.model_copy(update={"repository": step})
            if missing:
                questions = unconnected(start_questions(
                    council.participants, council.judge, stream.idea.text, repository_key(step)),
                    missing)
            else:
                runs = [question_run(council, group, ready, agents, store)]
                questions = runs[0].state.model_copy(deep=True)
            changes |= {**BELOW_REPOSITORY, "questions": questions}
        return store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update=changes))}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


def repository_step(stream: Stream, edit: ApproveRepository) -> RepositoryStep:
    """Как проходят шаг: без скана или с картой того скана, что на экране, — готового."""
    if stream.idea is None:
        raise HTTPException(409, NO_IDEA)
    if edit.scan_run is None:
        return RepositoryStep(by="skipped")
    scan = stream.scan
    if scan is None or scan.run != edit.scan_run:
        raise HTTPException(409, "Репозиторий уже сканировали заново — карта была к прежнему")
    if running(scan):
        raise HTTPException(409, "Совет ещё сканирует — дождитесь его")
    if scan.state != "done" or scan.result is None:
        raise HTTPException(409, "Скан не удался — запустите его снова или пропустите шаг")
    return RepositoryStep(by="scan", scan_run=scan.run)


def repository_key(step: RepositoryStep) -> str:
    """С какой картой ищут вопросы: без скана или с картой этого скана."""
    return step.scan_run if step.by == "scan" else SKIPPED


def asks_anew(stream: Stream, step: RepositoryStep) -> bool:
    """Вопросы ищутся заново, если их ещё не искали или искали к другой идее или карте."""
    questions = stream.questions
    return (questions is None or questions.idea != stream.idea.text
            or questions.repository != repository_key(step))


def repository_map(stream: Stream) -> str:
    """Что получают следующие шаги: карта утверждённого скана или «не сканировали»."""
    step, scan = stream.repository, stream.scan
    if step is None or step.by != "scan" or scan is None or scan.run != step.scan_run:
        return context_prompt(None)
    return context_prompt(scan.result, scan.commit_sha, dirty=scan.dirty,
                          outside=scan.outside, omitted=scan.omitted,
                          omitted_count=scan.omitted_count)


def idea_of(text: str | None, search: IdeaDiscovery | None) -> StreamIdea:
    """Идея человека. Слово в слово как у совета — вариант совета с его опорой, иначе своя."""
    text = " ".join((text or "").split())
    if not text:
        raise HTTPException(422, "Нужна формулировка идеи")
    if len(text) > IDEA_MAX:
        raise HTTPException(422, f"Идея длиннее {IDEA_MAX} знаков")
    offered = []
    if search is not None:
        if search.proposal is not None and search.proposal.idea is not None:
            offered.append((search.proposal.idea, search.proposal.evidence))
        offered += [(option.idea, option.evidence) for option in search.options]
    for idea, evidence in offered:
        if idea == text:
            return StreamIdea(text=text, by="council", evidence=evidence)
    return StreamIdea(text=text, by="human")


@router.post("/{council_id}/streams/{group}/questions/discovery", status_code=202,
             responses={**NOT_FOUND, **CANNOT_START, **NO_STREAM})
def start_question_discovery(council_id: str, group: str, store: StoreDep, config: ConfigDep,
                             agents: AgentsDep, launch: LauncherDep) -> Council:
    """Ищет вопросы к идее потока заново: после сбоя или если при утверждении идеи не было
    подключения к моделям. Повтор не платит второй раз за ответы, которые модели уже дали."""
    def ready(council: Council) -> None:
        stream = stream_in(council, group)
        if stream.idea is None:
            raise HTTPException(409, NO_IDEA)
        if stream.repository is None:
            raise HTTPException(409, "Сначала пройдите шаг «Репозиторий»")
        if stream.scope is not None:
            raise HTTPException(409, "Вопросы потока уже утверждены")
        if outdated(council.slicing, council.structure):
            raise HTTPException(409, RESLICED)

    def build(council: Council, report: Callable) -> QuestionRun:
        stream = stream_in(council, group)
        return QuestionRun(council.id, stream.idea.text,
                           fragments_of(council, group_of(council, group)),
                           council.participants, council.judge, agents, report,
                           repository=repository_key(stream.repository),
                           repository_map=repository_map(stream))

    return start_run(council_id, store, config, agents, launch, asking(group), ready, None,
                     build)


@router.post("/{council_id}/streams/{group}/questions",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        422: {"description": "Нет таких вопросов, пустой или слишком длинный "
                                             "свой вопрос, или не осталось ни одного"},
                        423: {"description": "Совет ещё ищет варианты или проверяет выбор "
                                             "к прежнему отбору"}})
def approve_scope(council_id: str, group: str, edit: ApproveScope, store: StoreDep,
                  config: ConfigDep, agents: AgentsDep, launch: LauncherDep) -> Council:
    """Человек утверждает, какие вопросы потоку решать: оставленные из найденных и свои, — и
    совет сразу ищет к ним новые варианты ответа. Ответы он здесь не выбирает. Утвердить
    заново — поменять отбор: варианты к прежнему и выбор по ним ищутся заново; тот же отбор
    их не трогает. Если поиск вопросов упал, можно утвердить и одни свои вопросы. Отбор — к
    тому поиску, что был на экране: нашли заново — 409, экран покажет новые вопросы."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        scope = scope_for(stream, edit)
        anew = proposes_anew(stream, scope)
        if anew and below_running(stream, "proposals"):
            raise HTTPException(
                423, "Совет ещё работает с прежним отбором — дождитесь его")
        return council, anew

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        scope = scope_for(stream, edit)
        changes: dict = {"scope": scope}
        runs: list[CouncilRun] = []
        if proposes_anew(stream, scope):
            if missing:
                proposals = unconnected(
                    start_proposals(council.participants, council.judge, scope), missing)
            else:
                runs = [proposal_run(council, group, stream, scope, agents, store)]
                proposals = runs[0].state.model_copy(deep=True)
            changes |= {"proposals": proposals, "choices": None, "analysis": None,
                        "decisions": None, "outcomes": None}
        return store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update=changes))}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


def scope_for(stream: Stream, edit: ApproveScope) -> list[OpenQuestion]:
    """Отбор, который утверждают: к нынешнему поиску вопросов, когда тот закончился."""
    search = stream.questions
    if stream.idea is None or search is None:
        raise HTTPException(409, "Вопросов ещё нет: сначала утвердите идею потока")
    if running(search):
        raise HTTPException(409, "Совет ещё ищет вопросы — дождитесь его")
    if search.run != edit.questions_run:
        raise HTTPException(409, "Вопросы уже нашли заново — отбор был к прежним")
    return scoped(search, edit.keep, edit.added)


def proposes_anew(stream: Stream, scope: list[OpenQuestion]) -> bool:
    """Варианты ищутся заново, если их ещё не искали или искали к другому отбору."""
    return stream.proposals is None or stream.proposals.scope != scope_key(scope)


@router.post("/{council_id}/streams/{group}/proposals/discovery", status_code=202,
             responses={**NOT_FOUND, **CANNOT_START, **NO_STREAM})
def start_proposal_discovery(council_id: str, group: str, store: StoreDep, config: ConfigDep,
                             agents: AgentsDep, launch: LauncherDep) -> Council:
    """Ищет варианты к отобранным вопросам заново: после сбоя или если при утверждении отбора
    не было подключения к моделям. Повтор не платит второй раз за уже данные ответы."""
    def ready(council: Council) -> None:
        stream = stream_in(council, group)
        if stream.scope is None:
            raise HTTPException(409, "Сначала утвердите вопросы потока")
        if stream.choices is not None:
            raise HTTPException(409, "Выбор по вопросам уже утверждён")
        if outdated(council.slicing, council.structure):
            raise HTTPException(409, RESLICED)

    def build(council: Council, report: Callable) -> ProposalRun:
        stream = stream_in(council, group)
        return ProposalRun(council.id, stream.idea.text, stream.scope,
                           fragments_of(council, group_of(council, group)),
                           council.participants, council.judge, agents, report,
                           repository=repository_map(stream))

    return start_run(council_id, store, config, agents, launch, proposing(group), ready, None,
                     build)


@router.post("/{council_id}/streams/{group}/choices",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        422: {"description": "Не по каждому вопросу один выбор, или такого "
                                             "варианта у вопроса нет"},
                        423: {"description": "Совет ещё проверяет прежний выбор или собирает "
                                             "итоги по нему"}})
def approve_choices(council_id: str, group: str, edit: ApproveChoices, store: StoreDep,
                    config: ConfigDep, agents: AgentsDep, launch: LauncherDep) -> Council:
    """Человек утверждает выбор: по каждому отобранному вопросу — вариант из текста группы
    (Fn) или найденный советом (Pn), либо None — пока не решает, вопрос уходит как unresolved.
    И совет сразу проверяет выбор, а для unresolved подбирает вариант из тех, что есть.
    Утвердить заново — поменять выбор: проверка прежнего и решения по ней уже ни к чему; тот
    же выбор их не трогает. Выбор — к тому поиску вариантов, что был на экране: нашли заново —
    409. Если поиск упал, выбирать можно из того, что есть: предложений группы и уже
    найденного."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        anew = analyzes_anew(stream, choices_for(stream, edit))
        if anew and below_running(stream, "analysis"):
            raise HTTPException(423, "Совет ещё работает с прежним выбором — дождитесь его")
        return council, anew

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        choices = choices_for(stream, edit)
        changes: dict = {"choices": choices}
        runs: list[CouncilRun] = []
        if analyzes_anew(stream, choices):
            if missing:
                analysis = unconnected(
                    start_analysis(council.participants, council.judge, choices), missing)
            else:
                runs = [decision_run(council, group, stream.model_copy(
                    update={"choices": choices}), agents, store)]
                analysis = runs[0].state.model_copy(deep=True)
            changes |= {"analysis": analysis, "decisions": None, "outcomes": None}
        return store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update=changes))}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


def choices_for(stream: Stream, edit: ApproveChoices) -> list[Choice]:
    """Выбор, который утверждают: к нынешнему поиску вариантов, когда тот закончился."""
    search = stream.proposals
    if stream.scope is None or search is None:
        raise HTTPException(409, "Вариантов ещё нет: сначала утвердите вопросы потока")
    if running(search):
        raise HTTPException(409, "Совет ещё ищет варианты — дождитесь его")
    if search.run != edit.proposals_run:
        raise HTTPException(409, "Варианты уже нашли заново — выбор был к прежним")
    return chosen(stream.scope, search, edit.choices)


def analyzes_anew(stream: Stream, choices: list[Choice]) -> bool:
    """Выбор проверяется заново, если его ещё не проверяли или проверяли другой."""
    return stream.analysis is None or stream.analysis.choices != choices_key(choices)


def chosen(scope: list[OpenQuestion], search: ProposalDiscovery,
           choices: list[Choice]) -> list[Choice]:
    """Выбор — по одному на каждый отобранный вопрос, в порядке отбора; вариант — из тех, что
    у этого вопроса есть: его предложения из текста и найденные к нему советом."""
    given = per_question(scope, choices, "выбора")
    for question in scope:
        proposal = given[question.id].proposal
        if proposal is not None and proposal not in offered_for(question, search):
            raise HTTPException(422, f"У вопроса {question.id} нет варианта {proposal}")
    return [given[question.id] for question in scope]


def per_question[T: (Choice, DecisionDraft)](scope: list[OpenQuestion], items: list[T],
                                            what: str) -> dict[str, T]:
    """По одному на каждый отобранный вопрос: ни дважды, ни лишних, ни пропущенных."""
    given: dict[str, T] = {}
    for item in items:
        if item.question_id in given:
            raise HTTPException(422, f"Вопрос {item.question_id} выбран дважды")
        given[item.question_id] = item
    unknown = sorted(set(given) - {question.id for question in scope})
    if unknown:
        raise HTTPException(422, f"Нет таких вопросов: {', '.join(unknown)}")
    missed = [question.id for question in scope if question.id not in given]
    if missed:
        raise HTTPException(422, f"Нет {what} по вопросам: {', '.join(missed)}")
    return given


def offered_for(question: OpenQuestion, search: ProposalDiscovery | None) -> set[str]:
    """Варианты вопроса: его предложения из текста и найденные к нему советом."""
    found = next((options.proposals for options in (search.options if search else [])
                  if options.question_id == question.id), [])
    return {f"F{i}" for i in question.proposal_ids} | {proposal.id for proposal in found}


@router.post("/{council_id}/streams/{group}/analysis", status_code=202,
             responses={**NOT_FOUND, **CANNOT_START, **NO_STREAM})
def start_decision_analysis(council_id: str, group: str, store: StoreDep, config: ConfigDep,
                            agents: AgentsDep, launch: LauncherDep) -> Council:
    """Проверяет выбор заново: после сбоя или если при утверждении выбора не было подключения
    к моделям. Повтор не платит второй раз за уже данные ответы."""
    def ready(council: Council) -> None:
        stream = stream_in(council, group)
        if stream.choices is None:
            raise HTTPException(409, "Сначала утвердите выбор по вопросам")
        if stream.decisions is not None:
            raise HTTPException(409, "Решения уже зафиксированы")
        if outdated(council.slicing, council.structure):
            raise HTTPException(409, RESLICED)

    def build(council: Council, report: Callable) -> DecisionRun:
        stream = stream_in(council, group)
        return DecisionRun(council.id, stream.idea.text, stream.scope, stream.choices,
                           stream.proposals, fragments_of(council, group_of(council, group)),
                           council.participants, council.judge, agents, report,
                           repository=repository_map(stream))

    return start_run(council_id, store, config, agents, launch, checking(group), ready, None,
                     build)


@router.post("/{council_id}/streams/{group}/decisions",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        422: {"description": "Не по каждому вопросу одно решение, такого "
                                             "варианта у вопроса нет или у решения нет "
                                             "обоснования"},
                        423: {"description": "Совет ещё собирает итоги по прежним решениям"}})
def approve_decisions(council_id: str, group: str, edit: ApproveDecisions, store: StoreDep,
                      config: ConfigDep, agents: AgentsDep, launch: LauncherDep) -> Council:
    """Человек фиксирует решения: по каждому отобранному вопросу — вариант с обоснованием (ADR)
    или открытый вопрос, — и совет сразу собирает из них итоги. Вариант — любой из тех, что у
    вопроса есть, а не только проверенный советом: решает человек, и проблема, которую нашёл
    совет, решению не мешает. Обоснование совета, оставленное как есть, — подтверждённое
    человеком (ai), своё или поправленное — human. Зафиксировать заново — поменять решения:
    итоги собираются заново; те же решения их не трогают. Решения — к той проверке, что была
    на экране: проверили заново — 409. Если проверка упала, решать можно и без неё — со своим
    обоснованием."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        anew = assembles_anew(stream, decisions_for(stream, edit))
        if anew and running(stream.outcomes):
            raise HTTPException(423, "Совет ещё собирает итоги по прежним решениям — дождитесь его")
        return council, anew

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        decisions = decisions_for(stream, edit)
        changes: dict = {"decisions": decisions}
        runs: list[CouncilRun] = []
        if assembles_anew(stream, decisions):
            if missing:
                outcomes = unconnected(
                    start_outcomes(council.participants, council.judge, decisions), missing)
            else:
                runs = [outcome_run(council, group, stream.model_copy(
                    update={"decisions": decisions}), agents, store)]
                outcomes = runs[0].state.model_copy(deep=True)
            changes["outcomes"] = outcomes
        return store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update=changes))}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


def decisions_for(stream: Stream, edit: ApproveDecisions) -> list[Decision]:
    """Решения, которые фиксируют: к нынешней проверке выбора, когда та закончилась."""
    analysis = stream.analysis
    if stream.choices is None or analysis is None:
        raise HTTPException(409, "Решать ещё рано: сначала утвердите выбор по вопросам")
    if running(analysis):
        raise HTTPException(409, "Совет ещё проверяет выбор — дождитесь его")
    if analysis.run != edit.analysis_run:
        raise HTTPException(409, "Выбор уже проверили заново — решения были к прежней проверке")
    return decided(stream.scope, stream.proposals, analysis, edit.decisions)


def assembles_anew(stream: Stream, decisions: list[Decision]) -> bool:
    """Итоги собираются заново, если их ещё не собирали или собирали к другим решениям."""
    return stream.outcomes is None or stream.outcomes.decisions != decisions_key(decisions)


@router.post("/{council_id}/streams/{group}/outcomes/discovery", status_code=202,
             responses={**NOT_FOUND, **CANNOT_START, **NO_STREAM})
def start_outcome_discovery(council_id: str, group: str, store: StoreDep, config: ConfigDep,
                            agents: AgentsDep, launch: LauncherDep) -> Council:
    """Собирает итоги заново: после сбоя или если при фиксации решений не было подключения к
    моделям. Повтор не платит второй раз за уже данные ответы. Собранные итоги он не трогает:
    за них заплачено, а заново они соберутся, когда поменяются решения."""
    def ready(council: Council) -> None:
        stream = stream_in(council, group)
        if stream.decisions is None:
            raise HTTPException(409, "Сначала зафиксируйте решения")
        if stream.outcomes is not None and stream.outcomes.state == "done":
            raise HTTPException(409, "Итоги уже собраны — заново они соберутся по другим решениям")
        if outdated(council.slicing, council.structure):
            raise HTTPException(409, RESLICED)

    def build(council: Council, report: Callable) -> OutcomeRun:
        stream = stream_in(council, group)
        return OutcomeRun(council.id, stream.idea.text, stream.scope, stream.decisions,
                          stream.proposals, fragments_of(council, group_of(council, group)),
                          council.participants, council.judge, agents, report,
                          repository=repository_map(stream))

    return start_run(council_id, store, config, agents, launch, assembling(group), ready, None,
                     build)


def decided(scope: list[OpenQuestion], search: ProposalDiscovery | None,
            analysis: DecisionAnalysis, drafts: list[DecisionDraft]) -> list[Decision]:
    """Решения — по одному на каждый отобранный вопрос, в порядке отбора. У решения есть
    обоснование: ADR без него не бывает. У открытого вопроса его нет."""
    given = per_question(scope, drafts, "решения")
    suggested = {found.question_id: found for found in analysis.analyses}
    decisions = []
    for question in scope:
        proposal = given[question.id].proposal
        if proposal is None:
            decisions.append(Decision(question_id=question.id))
            continue
        if proposal not in offered_for(question, search):
            raise HTTPException(422, f"У вопроса {question.id} нет варианта {proposal}")
        rationale = " ".join((given[question.id].rationale or "").split())
        if not rationale:
            raise HTTPException(422, f"У решения по {question.id} нет обоснования")
        if len(rationale) > RATIONALE_MAX:
            raise HTTPException(422, f"Обоснование по {question.id} длиннее {RATIONALE_MAX} знаков")
        ai = suggested.get(question.id)
        by_ai = ai is not None and ai.proposal == proposal and ai.rationale == rationale
        decisions.append(Decision(question_id=question.id, proposal=proposal, rationale=rationale,
                                  rationale_by="ai" if by_ai else "human"))
    return decisions


def scoped(search: QuestionDiscovery, keep: list[str], added: list[str]) -> list[OpenQuestion]:
    """Отобранные вопросы: оставленные — в порядке совета, свои — следом, с номерами дальше.
    Свой вопрос, совпавший с оставленным или другим своим, — тот же вопрос."""
    found = {question.id: question for question in search.questions}
    unknown = [question_id for question_id in keep if question_id not in found]
    if unknown:
        raise HTTPException(422, f"Нет вопросов: {', '.join(unknown)}")
    kept = [question for question in search.questions if question.id in set(keep)]
    seen = {same_question(question.text) for question in kept}
    own: list[str] = []
    for text in added:
        text = " ".join(text.split())
        if not text:
            raise HTTPException(422, "Свой вопрос пуст")
        if len(text) > QUESTION_MAX:
            raise HTTPException(422, f"Свой вопрос длиннее {QUESTION_MAX} знаков")
        if same_question(text) not in seen:
            seen.add(same_question(text))
            own.append(text)
    if not kept and not own:
        raise HTTPException(422, "Оставьте или добавьте хотя бы один вопрос")
    start = len(search.questions) + 1
    return [*kept, *(OpenQuestion(id=f"Q{n}", text=text, source="added")
                     for n, text in enumerate(own, start))]


def seen_idea(stream: Stream, edit: ScanRepository | ApproveRepository) -> None:
    """Правка — к той идее, что человек видел (edit.idea): её поменяли в другой вкладке — до
    запроса или пока шла проверка моделей и git (plan() зовётся и до, и после), — 409, а не скан
    или поиск вопросов под идею, которой он не видел."""
    if stream.idea is not None and stream.idea.text != edit.idea:
        raise HTTPException(409, "Идею потока поменяли — посмотрите на новую и повторите")


def probed[T](config: AppConfig, agents: AgentRunner, plan: Callable[[], tuple[Council, bool]],
              apply: Callable[[Council, list[str]], T]) -> T:
    """Правка потоков, которая, может быть, запускает ходы моделей. Вход проверяется вне
    замка — это запуски CLI, — а правка под замком, со сверкой: не поменялся ли состав совета,
    пока шла проверка. plan() под замком проверяет совет (исключение — отказ) и отвечает,
    нужны ли модели; apply(совет, модели без подключения) — сама правка."""
    with council_lock:
        before, needs = plan()
    for _ in range(PROBE_ATTEMPTS):
        missing = offline(before, config, agents, fresh=True) if needs else []
        with council_lock:
            council, again = plan()
            if again == needs and lineup(council) == lineup(before):
                return apply(council, missing)
            needs = again
        before = council
    # Не 409: 409 значит «правка уже не к тем группам», а здесь меняется состав совета.
    raise HTTPException(503, "Состав совета меняется прямо сейчас — попробуйте ещё раз")


def launched_all(store: Store, council_id: str, launch: Launcher, council: Council | None,
                 runs: list[CouncilRun]) -> Council:
    """Отдать ходы в пул. Какой не отдался (сервер останавливается) — записан упавшим, и
    тогда ответ — совет как он есть."""
    if council is None:
        raise HTTPException(404, MISSING)
    failed = [run for run in runs if not launched(launch, run, run.report)]
    return (store.get_council(council_id) or council) if failed else council


def unconnected[S: (IdeaDiscovery, RepositoryScan, QuestionDiscovery, ProposalDiscovery,
                    DecisionAnalysis, OutcomeDiscovery)](state: S, missing: list[str]) -> S:
    """Ход, который не запустить: к моделям нет подключения. Записан упавшим с причиной."""
    return state.model_copy(update={
        "state": "failed", "error": f"Нет подключения к моделям: {', '.join(missing)}"})


def discovery(group: str) -> Slot:
    """Поиск идеи потока как место хода. Потока нет — нет и хода."""
    return stream_slot(group, "discovery")


def scanning(group: str) -> Slot:
    """Скан репозитория потока как место хода."""
    return stream_slot(group, "scan")


def asking(group: str) -> Slot:
    """Поиск вопросов потока как место хода."""
    return stream_slot(group, "questions")


def proposing(group: str) -> Slot:
    """Поиск вариантов потока как место хода."""
    return stream_slot(group, "proposals")


def checking(group: str) -> Slot:
    """Проверка выбора потока как место хода."""
    return stream_slot(group, "analysis")


def assembling(group: str) -> Slot:
    """Сборка итогов потока как место хода."""
    return stream_slot(group, "outcomes")


def below_running(stream: Stream, field: str) -> bool:
    """Совет работает над этим звеном цепочки потока или над тем, что ниже него."""
    return any(running(getattr(stream, name)) for name in STREAM_RUNS[STREAM_RUNS.index(field):])


def stream_slot(group: str, field: str) -> Slot:
    def get(council: Council) -> RunState | None:
        stream = find_stream(council, group)
        return getattr(stream, field) if stream else None

    def put(council: Council, state: RunState) -> dict:
        stream = find_stream(council, group)
        return {"streams": replaced(council, stream.model_copy(update={field: state}))}

    return Slot(get, put)


def idea_run(council: Council, group: Group, runner: Runner, store: Store) -> IdeaRun:
    return IdeaRun(council.id, fragments_of(council, group), council.participants, council.judge,
                   runner, reporter(store, council.id, discovery(group.id)))


def question_run(council: Council, group: str, stream: Stream, runner: Runner,
                 store: Store) -> QuestionRun:
    return QuestionRun(council.id, stream.idea.text,
                       fragments_of(council, group_of(council, group)),
                       council.participants, council.judge, runner,
                       reporter(store, council.id, asking(group)),
                       repository=repository_key(stream.repository),
                       repository_map=repository_map(stream))


def proposal_run(council: Council, group: str, stream: Stream, scope: list[OpenQuestion],
                 runner: Runner, store: Store) -> ProposalRun:
    return ProposalRun(council.id, stream.idea.text, scope,
                       fragments_of(council, group_of(council, group)),
                       council.participants, council.judge, runner,
                       reporter(store, council.id, proposing(group)),
                       repository=repository_map(stream))


def decision_run(council: Council, group: str, stream: Stream, runner: Runner,
                 store: Store) -> DecisionRun:
    return DecisionRun(council.id, stream.idea.text, stream.scope, stream.choices,
                       stream.proposals, fragments_of(council, group_of(council, group)),
                       council.participants, council.judge, runner,
                       reporter(store, council.id, checking(group)),
                       repository=repository_map(stream))


def outcome_run(council: Council, group: str, stream: Stream, runner: Runner,
                store: Store) -> OutcomeRun:
    return OutcomeRun(council.id, stream.idea.text, stream.scope, stream.decisions,
                      stream.proposals, fragments_of(council, group_of(council, group)),
                      council.participants, council.judge, runner,
                      reporter(store, council.id, assembling(group)),
                      repository=repository_map(stream))


def find_stream(council: Council, group: str) -> Stream | None:
    return next((stream for stream in council.streams or [] if stream.group == group), None)


def stream_in(council: Council, group: str) -> Stream:
    """Поток группы. Нет — значит, группы уже другие: 409, экран покажет нынешние."""
    if council.streams is None:
        raise HTTPException(409, "Группы ещё не подтверждены — потоков нет")
    stream = find_stream(council, group)
    if stream is None:
        raise HTTPException(409, f"Потока {group} нет — группы уже другие")
    return stream


def group_of(council: Council, group: str) -> Group:
    """Группа потока. Поток есть — есть и группа: состав меняют только со снятием подтверждения."""
    return next(g for g in council.structure.groups if g.id == group)


def fragments_of(council: Council, group: Group) -> list[LabeledFragment]:
    members = set(group.fragment_ids)
    return [fragment for fragment in council.slicing.fragments if fragment.id in members]


def replaced(council: Council, stream: Stream) -> list[Stream]:
    return [stream if s.group == stream.group else s for s in council.streams or []]
