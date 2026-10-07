"""Потоки — подтверждённые группы. Подтверждение заводит поток на каждую группу и сразу
запускает поиск идеи у тех, в тексте которых её нет. Человек утверждает идею потока —
найденную советом, свою или записанную в тексте, — и совет сразу ищет к ней открытые
вопросы. Человек отбирает, какие из них решать, и добавляет свои."""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from ..agents import AgentRunner
from ..config import AppConfig
from ..deps import AgentsDep, ConfigDep, Launcher, LauncherDep, Store, StoreDep
from ..ideas import IDEA_MAX
from ..models import (
    ApproveIdea,
    ApproveScope,
    Council,
    CouncilStatus,
    Group,
    GroupsEdit,
    IdeaDiscovery,
    LabeledFragment,
    OpenQuestion,
    QuestionDiscovery,
    Stream,
    StreamIdea,
)
from ..pipeline import CouncilRun, IdeaRun, QuestionRun, Runner, start_idea, start_questions
from ..questions import QUESTION_MAX, same_question
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
            raise HTTPException(
                409, "Типы фрагментов поменялись после раскладки — сначала разложите заново")

    return start_run(
        council_id, store, config, agents, launch, discovery(group), ready, None,
        lambda council, report: IdeaRun(council.id, fragments_of(council, group_of(council, group)),
                                        council.participants, council.judge, agents, report),
    )


@router.post("/{council_id}/streams/{group}/idea",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        422: {"description": "Пустая или слишком длинная идея, или идею из "
                                             "текста пытаются править"},
                        423: {"description": "Совет ещё ищет вопросы к прежней идее"}})
def approve_idea(council_id: str, group: str, edit: ApproveIdea, store: StoreDep,
                 config: ConfigDep, agents: AgentsDep, launch: LauncherDep) -> Council:
    """Человек утверждает идею потока, и совет сразу ищет к ней открытые вопросы. Утвердить
    заново — поменять идею: вопросы к прежней и их отбор уже ни к чему, их ищут заново; та же
    идея их не трогает. Идея, записанная в тексте, не правится: это фрагменты группы. Нет
    подключения к моделям — идея утверждена, а поиск вопросов записан упавшим с причиной."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        idea = idea_for(council, stream, group, edit.text)
        # Другую идею, пока к нынешней ищут вопросы, не утвердить: их поиск пришлось бы бросить.
        # Ту же — можно: ничего не меняется, это повтор (другая вкладка, потерянный ответ).
        if running(stream.questions) and asks_anew(stream, idea):
            raise HTTPException(423, "Совет ещё ищет вопросы к прежней идее — дождитесь его")
        return council, asks_anew(stream, idea)

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        idea = idea_for(council, stream, group, edit.text)
        changes: dict = {"idea": idea}
        runs: list[CouncilRun] = []
        if asks_anew(stream, idea):
            if missing:
                questions = unconnected(
                    start_questions(council.participants, council.judge, idea.text), missing)
            else:
                runs = [question_run(council, group, idea.text, agents, store)]
                questions = runs[0].state.model_copy(deep=True)
            changes |= {"questions": questions, "scope": None}
        return store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update=changes))}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


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


def asks_anew(stream: Stream, idea: StreamIdea) -> bool:
    """Вопросы ищутся заново, если их ещё не искали или искали к другой идее."""
    return stream.questions is None or stream.questions.idea != idea.text


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
            raise HTTPException(409, "Сначала утвердите идею потока")
        if stream.scope is not None:
            raise HTTPException(409, "Вопросы потока уже утверждены")
        if outdated(council.slicing, council.structure):
            raise HTTPException(
                409, "Типы фрагментов поменялись после раскладки — сначала разложите заново")

    return start_run(
        council_id, store, config, agents, launch, asking(group), ready, None,
        lambda council, report: QuestionRun(
            council.id, stream_in(council, group).idea.text,
            fragments_of(council, group_of(council, group)),
            council.participants, council.judge, agents, report),
    )


@router.post("/{council_id}/streams/{group}/questions",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM,
                        422: {"description": "Нет таких вопросов, пустой или слишком длинный "
                                             "свой вопрос, или не осталось ни одного"}})
def approve_scope(council_id: str, group: str, edit: ApproveScope, store: StoreDep) -> Council:
    """Человек утверждает, какие вопросы потоку решать: оставленные из найденных и свои.
    Ответы он здесь не выбирает. Утвердить заново — поменять отбор. Если поиск упал, можно
    утвердить и одни свои вопросы. Отбор — к тому поиску, что был на экране: нашли заново —
    409, экран покажет новые вопросы."""
    with council_lock:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        search = stream.questions
        if stream.idea is None or search is None:
            raise HTTPException(409, "Вопросов ещё нет: сначала утвердите идею потока")
        if running(search):
            raise HTTPException(409, "Совет ещё ищет вопросы — дождитесь его")
        if search.run != edit.questions_run:
            raise HTTPException(409, "Вопросы уже нашли заново — отбор был к прежним")
        scope = scoped(search, edit.keep, edit.added)
        council = store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update={"scope": scope}))})
    if council is None:
        raise HTTPException(404, MISSING)
    return council


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


def unconnected[S: (IdeaDiscovery, QuestionDiscovery)](state: S, missing: list[str]) -> S:
    """Ход, который не запустить: к моделям нет подключения. Записан упавшим с причиной."""
    return state.model_copy(update={
        "state": "failed", "error": f"Нет подключения к моделям: {', '.join(missing)}"})


def discovery(group: str) -> Slot:
    """Поиск идеи потока как место хода. Потока нет — нет и хода."""
    return stream_slot(group, "discovery")


def asking(group: str) -> Slot:
    """Поиск вопросов потока как место хода."""
    return stream_slot(group, "questions")


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


def question_run(council: Council, group: str, idea: str, runner: Runner,
                 store: Store) -> QuestionRun:
    return QuestionRun(council.id, idea, fragments_of(council, group_of(council, group)),
                       council.participants, council.judge, runner,
                       reporter(store, council.id, asking(group)))


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
