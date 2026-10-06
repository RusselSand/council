"""Потоки — подтверждённые группы. Подтверждение заводит поток на каждую группу и сразу
запускает поиск идеи у тех, в тексте которых её нет. Человек утверждает идею потока —
найденную советом, свою или записанную в тексте — и поток переходит к вопросам."""

from fastapi import APIRouter, HTTPException

from ..deps import AgentsDep, ConfigDep, LauncherDep, Store, StoreDep
from ..ideas import IDEA_MAX
from ..models import (
    ApproveIdea,
    Council,
    CouncilStatus,
    Group,
    GroupsEdit,
    IdeaDiscovery,
    LabeledFragment,
    Stream,
    StreamIdea,
)
from ..pipeline import IdeaRun, Runner, start_idea
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


@router.post("/{council_id}/structure/confirm",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS,
                        503: {"description": "Состав совета меняется прямо сейчас"}})
def confirm_groups(council_id: str, edit: GroupsEdit, store: StoreDep, config: ConfigDep,
                   agents: AgentsDep, launch: LauncherDep) -> Council:
    """Человек подтвердил группы: каждая становится потоком, совет переходит к потокам.
    Подтверждает то, что видел: ту же раскладку и версию групп. Подтверждённые раньше —
    ответ тот же, совет не меняется.

    У групп без идеи совет сразу её ищет. Подтверждение от этого не зависит: нет
    подключения к моделям — поиск записан упавшим с причиной, и его можно повторить."""
    with council_lock:
        before = current(council_id, store, edit)
    if before.streams is not None:
        return before
    for _ in range(PROBE_ATTEMPTS):
        lacking = [group for group in before.structure.groups if group.missing_idea]
        missing = offline(before, config, agents, fresh=True) if lacking else []
        with council_lock:
            council = current(council_id, store, edit)
            if council.streams is not None:
                return council  # подтвердили в другой вкладке
            if lineup(council) == lineup(before):
                runs = {} if missing else {group.id: idea_run(council, group, agents, store)
                                           for group in lacking}
                streams = [Stream(group=group.id, discovery=searched(council, group, runs, missing))
                           for group in council.structure.groups]
                council = store.update_council(
                    council_id, {"streams": streams, "status": CouncilStatus.review})
                break
        before = council
    else:
        raise HTTPException(503, "Состав совета меняется прямо сейчас — попробуйте ещё раз")
    failed = [run for run in runs.values() if not launched(launch, run, run.report)]
    return (store.get_council(council_id) or council) if failed else council


def searched(council: Council, group: Group, runs: dict[str, IdeaRun],
             missing: list[str]) -> IdeaDiscovery | None:
    """Поиск идеи потока при подтверждении: у группы с идеей его нет, без подключения —
    упавший с причиной, иначе — идущий."""
    if not group.missing_idea:
        return None
    if missing:
        return start_idea(council.participants, council.judge).model_copy(update={
            "state": "failed", "error": f"Нет подключения к моделям: {', '.join(missing)}"})
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
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM,
                        422: {"description": "Пустая или слишком длинная идея, или идею из "
                                             "текста пытаются править"}})
def approve_idea(council_id: str, group: str, edit: ApproveIdea, store: StoreDep) -> Council:
    """Человек утверждает идею потока, и поток переходит к вопросам. Утвердить заново —
    поменять идею. Идея, записанная в тексте, не правится: это фрагменты группы."""
    with council_lock:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        target = group_of(council, group)
        if not target.missing_idea:
            if edit.text is not None:
                raise HTTPException(422, "Идея группы записана в тексте — её не правят")
            texts = {fragment.id: fragment.text for fragment in council.slicing.fragments}
            idea = StreamIdea(text=" ".join(texts[i] for i in target.idea_fragment_ids),
                              by="text", evidence=target.idea_fragment_ids)
        else:
            if running(stream.discovery):
                raise HTTPException(409, "Совет ещё ищет идею — дождитесь его")
            idea = idea_of(edit.text, stream.discovery)
        council = store.update_council(council_id, {
            "streams": replaced(council, stream.model_copy(update={"idea": idea}))})
    if council is None:
        raise HTTPException(404, MISSING)
    return council


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


def discovery(group: str) -> Slot:
    """Поиск идеи потока как место хода. Потока нет — нет и хода."""
    def get(council: Council) -> RunState | None:
        stream = find_stream(council, group)
        return stream.discovery if stream else None

    def put(council: Council, state: RunState) -> dict:
        stream = find_stream(council, group)
        return {"streams": replaced(council, stream.model_copy(update={"discovery": state}))}

    return Slot(get, put)


def idea_run(council: Council, group: Group, runner: Runner, store: Store) -> IdeaRun:
    return IdeaRun(council.id, fragments_of(council, group), council.participants, council.judge,
                   runner, reporter(store, council.id, discovery(group.id)))


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
