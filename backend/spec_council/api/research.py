"""Этап «Исследование» — на весь совет, между группами и потоками. Когда идеи всех групп
утверждены, совет исследует код и макет под них все разом: необязательный шаг «Репозиторий» —
скан рабочих копий, карту утверждают или шаг пропускают, — потом так же необязательный шаг
«Дизайн» со сканом макета Figma. Исследование пройдено — потоки можно начинать: поток берёт себе
копию карты и описания макета (streams.start_stream).

Исследование само ничего не сбрасывает в потоках, а потоки — в нём: поменяли идею — на экране
видно, что исследование было к прежним идеям (scan.idea), и его можно сбросить кнопкой; прошли
исследование заново — начатый поток видит, что взял прежнее, и его можно начать заново."""

from fastapi import APIRouter, HTTPException

from ..deps import AgentsDep, ConfigDep, FigmaDep, LauncherDep, RepositoriesDep, StoreDep
from ..figma import FigmaError, links_of
from ..models import (
    ApproveDesign,
    ApproveRepository,
    Council,
    DesignStep,
    GroupsEdit,
    LabeledFragment,
    RepositoryStep,
    Research,
    ScanDesign,
    ScanRepository,
)
from ..pipeline import CouncilRun, DesignRun, RepositoryRun, start_design, start_scan
from ..repository import RepositoryError, fits, merged, sources_of, working_copy
from .councils import MISSING, NOT_FOUND, RunState, Slot, council_lock, reporter, running
from .groups import NOT_THESE_GROUPS, current, outdated
from .streams import CHANGING, RESLICED, launched_all, probed, unconnected

router = APIRouter(prefix="/councils", tags=["research"])

NO_IDEAS = "Сначала утвердите идеи всех групп"
NO_REPOSITORY = "Сначала пройдите шаг «Репозиторий»"


def research_of(council: Council) -> Research:
    return council.research or Research()


def research_slot(field: str) -> Slot:
    """Ход исследования как место хода: скан репозитория или макета."""
    def get(council: Council) -> RunState | None:
        return getattr(council.research, field) if council.research else None

    def put(council: Council, state: RunState) -> dict:
        return {"research": research_of(council).model_copy(update={field: state})}

    return Slot(get, put)


SCANNING = research_slot("scan")
DESIGNING = research_slot("design_scan")


def ideas_of(council: Council) -> str:
    """Идеи всех групп одним текстом — под них идёт исследование, его и помнит скан. Группа без
    утверждённой идеи — исследовать рано (409)."""
    if not council.streams:
        raise HTTPException(409, "Группы ещё не подтверждены")
    titles = {group.id: group.title for group in council.structure.groups}
    lines = []
    for stream in council.streams:
        if stream.idea is None:
            raise HTTPException(409, NO_IDEAS)
        lines.append(f"{stream.group}. {titles.get(stream.group, '')}: {stream.idea.text}")
    return "\n".join(lines)


def all_fragments(council: Council) -> list[LabeledFragment]:
    """Фрагменты всех групп — по порядку текста, общий фрагмент один раз."""
    members = {i for group in council.structure.groups for i in group.fragment_ids}
    return [fragment for fragment in council.slicing.fragments if fragment.id in members]


def researching(council: Council) -> bool:
    research = council.research
    return research is not None and (running(research.scan) or running(research.design_scan))


def ready_for(council: Council) -> str:
    """Исследовать можно: группы подтверждены, идеи утверждены, типы не менялись. Ответ — идеи."""
    if council.slicing is None or council.structure is None:
        raise HTTPException(409, "Группы ещё не разложены")
    if outdated(council.slicing, council.structure):
        raise HTTPException(409, RESLICED)
    return ideas_of(council)


@router.post("/{council_id}/research/repository/scan", status_code=202,
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **CHANGING,
                        409: {"description": "Идеи не утверждены, скан уже идёт или группы уже "
                                             "другие"},
                        422: {"description": "Путь не к рабочей копии git"}})
def scan_repository(council_id: str, edit: ScanRepository, store: StoreDep, config: ConfigDep,
                    agents: AgentsDep, launch: LauncherDep,
                    repositories: RepositoriesDep) -> Council:
    """Совет сканирует репозиторий под идеи всех групп: inventory рабочих копий — сейчас, потом
    участники и судья исследуют код, только читая его. Скан заново — шаг «Репозиторий» заново:
    утверждённая карта и пройденный шаг «Дизайн» снимаются (скан макета остаётся); потоки, уже
    начатые, работают со своей копией. Повтор после сбоя берёт уже оплаченные ответы даром.
    Нет подключения к моделям — скан записан упавшим с причиной."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        ready_for(council)
        if running(research_of(council).scan):
            raise HTTPException(409, "Скан уже идёт")
        return council, True

    # Сначала дешёвое: устаревший или лишний запрос не должен ждать git на большой рабочей
    # копии ради 404 и 409. Под замком всё проверится ещё раз.
    with council_lock:
        plan()
    try:
        sources = sources_of([(path, working_copy(path, repositories, mark=True))
                              for path in edit.paths])
        fits(merged(sources))
    except RepositoryError as exc:
        raise HTTPException(422, str(exc)) from None

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        ideas = ready_for(council)
        runs: list[CouncilRun] = []
        if missing:
            scan = unconnected(start_scan(council.participants, council.judge, ideas, sources),
                               missing)
        else:
            runs = [RepositoryRun(council.id, ideas, sources, all_fragments(council),
                                  council.participants, council.judge, agents,
                                  reporter(store, council.id, SCANNING))]
            scan = runs[0].state.model_copy(deep=True)
        research = research_of(council).model_copy(
            update={"scan": scan, "repository": None, "design": None})
        return store.update_council(council_id, {"research": research}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


@router.post("/{council_id}/research/repository",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS,
                        409: {"description": "Групп уже других, идеи не утверждены или "
                                             "сканировали заново"}})
def approve_repository(council_id: str, edit: ApproveRepository, store: StoreDep) -> Council:
    """Человек проходит шаг «Репозиторий»: утверждает карту скана или пропускает шаг; дальше —
    шаг «Дизайн». Пройти шаг заново иначе — шаг «Дизайн» проходят заново (скан макета
    остаётся); так же — ничего не меняется. Карта — того скана, что был на экране: сканировали
    заново — 409."""
    with council_lock:
        council = current(council_id, store, edit)
        ready_for(council)
        research = research_of(council)
        step = repository_step(research, edit)
        changes: dict = {"repository": step}
        if research.repository != step:
            changes["design"] = None
        council = store.update_council(council_id, {
            "research": research.model_copy(update=changes)})
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def repository_step(research: Research, edit: ApproveRepository) -> RepositoryStep:
    """Как проходят шаг: без скана или с картой того скана, что на экране, — готового."""
    if edit.scan_run is None:
        return RepositoryStep(by="skipped")
    scan = research.scan
    if scan is None or scan.run != edit.scan_run:
        raise HTTPException(409, "Репозиторий уже сканировали заново — карта была к прежнему")
    if running(scan):
        raise HTTPException(409, "Совет ещё сканирует — дождитесь его")
    if scan.state != "done" or scan.result is None:
        raise HTTPException(409, "Скан не удался — запустите его снова или пропустите шаг")
    return RepositoryStep(by="scan", scan_run=scan.run)


@router.post("/{council_id}/research/design/scan", status_code=202,
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **CHANGING,
                        409: {"description": "Идеи не утверждены, шаг «Репозиторий» не пройден, "
                                             "скан уже идёт или группы уже другие"},
                        422: {"description": "Ссылки не на Figma или токена Figma нет"}})
def scan_design(council_id: str, edit: ScanDesign, store: StoreDep, config: ConfigDep,
                agents: AgentsDep, launch: LauncherDep, figma: FigmaDep) -> Council:
    """Совет сканирует макет Figma под идеи всех групп: сам снимает страницы из ссылок с одной
    версии файла, потом участники и судья исследуют снимок, только читая его. Скан заново —
    шаг «Дизайн» заново. Повтор после сбоя той же версии берёт уже оплаченные ответы даром. Нет
    подключения к моделям — скан записан упавшим с причиной."""
    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        ready_for(council)
        research = research_of(council)
        if research.repository is None:
            raise HTTPException(409, NO_REPOSITORY)
        if running(research.design_scan):
            raise HTTPException(409, "Скан макета уже идёт")
        return council, True

    with council_lock:
        plan()
    try:
        links = links_of(edit.links)
    except FigmaError as exc:
        raise HTTPException(422, str(exc)) from None
    if figma is None:
        raise HTTPException(422, "Токен Figma не задан: впишите FIGMA_TOKEN в .env и "
                                 "перезапустите сервер")

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        ideas = ready_for(council)
        runs: list[CouncilRun] = []
        if missing:
            scan = unconnected(start_design(council.participants, council.judge, ideas, links),
                               missing)
        else:
            runs = [DesignRun(council.id, ideas, links, all_fragments(council),
                              council.participants, council.judge, agents,
                              reporter(store, council.id, DESIGNING), fetch=figma)]
            scan = runs[0].state.model_copy(deep=True)
        research = research_of(council).model_copy(update={"design_scan": scan, "design": None})
        return store.update_council(council_id, {"research": research}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


@router.post("/{council_id}/research/design",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS,
                        409: {"description": "Групп уже других, макет сканировали заново или шаг "
                                             "«Репозиторий» не пройден"}})
def approve_design(council_id: str, edit: ApproveDesign, store: StoreDep) -> Council:
    """Человек проходит шаг «Дизайн»: утверждает описание скана макета или пропускает шаг.
    Исследование пройдено — потоки можно начинать. Описание — того скана, что был на экране:
    сканировали заново — 409."""
    with council_lock:
        council = current(council_id, store, edit)
        ready_for(council)
        research = research_of(council)
        step = design_step(research, edit)
        council = store.update_council(council_id, {
            "research": research.model_copy(update={"design": step})})
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def design_step(research: Research, edit: ApproveDesign) -> DesignStep:
    """Как проходят шаг «Дизайн»: без скана или с описанием того скана, что на экране, —
    готового. Сначала — шаг «Репозиторий»."""
    if research.repository is None:
        raise HTTPException(409, NO_REPOSITORY)
    if edit.scan_run is None:
        return DesignStep(by="skipped")
    scan = research.design_scan
    if scan is None or scan.run != edit.scan_run:
        raise HTTPException(409, "Макет уже сканировали заново — описание было к прежнему")
    if running(scan):
        raise HTTPException(409, "Совет ещё сканирует макет — дождитесь его")
    if scan.state != "done" or scan.result is None:
        raise HTTPException(409, "Скан макета не удался — запустите его снова или пропустите "
                                 "шаг")
    return DesignStep(by="scan", scan_run=scan.run)


@router.post("/{council_id}/research/reset",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS,
                        409: {"description": "Групп уже других"},
                        423: {"description": "Совет ещё сканирует"}})
def reset_research(council_id: str, edit: GroupsEdit, store: StoreDep) -> Council:
    """Человек сбрасывает исследование — например, после того как поменял идеи: сканы и
    пройденные шаги снимаются. Начатые потоки работают со своей копией, пока их не начнут
    заново."""
    with council_lock:
        council = current(council_id, store, edit)
        if researching(council):
            raise HTTPException(423, "Совет ещё сканирует — дождитесь его")
        council = store.update_council(council_id, {"research": None})
    if council is None:
        raise HTTPException(404, MISSING)
    return council
