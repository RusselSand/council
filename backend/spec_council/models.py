"""Контракт API: то, что видит фронт. Меняется только вместе с фронтом."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class CouncilStatus(StrEnum):
    brief = "brief"
    slices = "slices"
    structure = "structure"
    review = "review"
    ready = "ready"


Label =Literal["idea", "question", "proposal", "constraint", "risk"]
RunState = Literal["waiting", "running", "done", "failed"]


class StepName(StrEnum):
    slice = "slice"              # участники нарезают текст, каждый сам по себе
    slice_judge = "slice_judge"  # судья выбирает нарезку, если участники разошлись
    label = "label"              # участники размечают итоговые фрагменты
    label_judge = "label_judge"  # судья решает фрагменты, где типы разошлись
    structure = "structure"              # участники раскладывают фрагменты по группам
    structure_judge = "structure_judge"  # судья выбирает раскладку, если разошлись
    idea_discovery = "idea_discovery"    # участники восстанавливают идею группы без неё
    idea_judge = "idea_judge"            # судья выбирает идею, если вариантов несколько
    repository_discovery = "repository_discovery"  # участники исследуют репозиторий под идею
    repository_judge = "repository_judge"          # судья проверяет их находки и покрытие
    design_discovery = "design_discovery"  # участники исследуют макет Figma под идею
    design_judge = "design_judge"          # судья проверяет их описание макета и покрытие
    # участники отбирают прошлые решения проекта, относящиеся к идее; судья сводит отбор
    project_decisions_discovery = "project_decisions_discovery"
    project_decisions_judge = "project_decisions_judge"
    question_discovery = "question_discovery"  # участники ищут открытые вопросы к идее
    question_judge = "question_judge"          # судья сводит их в один канонический список
    proposal_discovery = "proposal_discovery"  # участники ищут новые варианты ответа на вопрос
    proposal_judge = "proposal_judge"          # судья решает, какие из них показать
    decision_analysis = "decision_analysis"  # участники проверяют выбор или сравнивают варианты
    decision_judge = "decision_judge"        # судья сводит их анализы в один итог по вопросу
    outcome_discovery = "outcome_discovery"  # участники собирают решения в изменения системы
    outcome_judge = "outcome_judge"          # судья выбирает и сводит их в итоговый набор
    issue_discovery = "issue_discovery"  # участники нарезают утверждённые итоги на задачи
    issue_judge = "issue_judge"          # судья сводит их нарезки в итоговый набор задач
    notes_translation = "notes_translation"  # судья переводит заметки на язык документации


class ModelRun(BaseModel):
    model: str
    state: RunState = "waiting"
    error: str | None = None


class Step(BaseModel):
    name: StepName
    # skipped — судья не понадобился: участники сошлись.
    state: Literal["waiting", "running", "done", "failed", "skipped"] = "waiting"
    runs: list[ModelRun]


class Vote(BaseModel):
    """Что предложил участник. Вариантов несколько, если он видит неоднозначность."""

    model: str
    labels: list[Label]


class LabeledFragment(BaseModel):
    id: int
    text: str
    # Итоговый тип. Человек может поменять его, council_label остаётся как было у совета.
    label: Label
    reason: str
    council_label: Label
    # agreed — участники сошлись, judge — разошлись и решил судья.
    decided_by: Literal["agreed", "judge"] = "agreed"
    votes: list[Vote] = []
    # Решение судьи нарезки о границе перед этим фрагментом или внутри него.
    slice_note: str | None = None


class Slicing(BaseModel):
    """Нарезка и разметка текста советом: ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    # Свой у каждого запуска. Номера фрагментов в каждой нарезке с 1, поэтому правка типа
    # несёт run: правка к прежней нарезке не ляжет на чужие фрагменты новой.
    run: str = ""
    # Текст, который нарезали: исходник мог поменяться после запуска.
    text: str = ""
    steps: list[Step]
    fragments: list[LabeledFragment] = []
    error: str | None = None


class Group(BaseModel):
    """Фрагменты вокруг одной задумки. Общий фрагмент (ограничение, риск) входит в несколько
    групп тем же ID: копия со ссылкой на источник, а не новый фрагмент."""

    # A, B, C… по порядку первого фрагмента. Правки человека букв не переставляют: у новой
    # группы — первая свободная.
    id: str
    title: str
    fragment_ids: list[int]
    idea_fragment_ids: list[int]
    # Идеи в тексте нет: её восстановит следующий этап, сам совет её не формулирует.
    missing_idea: bool
    # Какие из fragment_ids есть и в других группах.
    shared_fragment_ids: list[int] = []


class GroupRelation(BaseModel):
    """Связь групп. Независимость — просто отсутствие связи."""

    source: str
    target: str
    # depends_on — source требует результата target; related — связаны без зависимости.
    type: Literal["depends_on", "related"]
    reason: str


class StructureDecision(BaseModel):
    """Решение судьи там, где раскладки участников расходились."""

    issue: str
    decision: str
    reason: str


class StructureProposal(BaseModel):
    """Группы и связи, как их предложил совет: к ним можно вернуться после своих правок."""

    groups: list[Group]
    relations: list[GroupRelation]


class Structure(BaseModel):
    """Раскладка фрагментов готовой нарезки по группам: ход по шагам и итог. groups и
    relations — с правками человека, proposal — как предложил совет."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # Из какой нарезки и с какими типами раскладывали: поменялись — раскладка устарела.
    slicing_run: str = ""
    labels: dict[int, Label] = {}
    steps: list[Step]
    groups: list[Group] = []
    relations: list[GroupRelation] = []
    decisions: list[StructureDecision] = []
    proposal: StructureProposal | None = None
    # Сколько раз человек правил группы этой раскладки. Правка несёт номер версии, к которой
    # она сделана: из другой вкладки к прежней версии она не ляжет на нынешнюю.
    revision: int = 0
    error: str | None = None

    @computed_field
    @property
    def edited(self) -> bool:
        """Человек менял группы: они не такие, как предложил совет."""
        return self.proposal is not None and (
            self.groups != self.proposal.groups or self.relations != self.proposal.relations)


class IdeaOption(BaseModel):
    """Формулировка идеи, как её восстановили по фрагментам группы. Одинаковые формулировки
    разных участников — один вариант."""

    idea: str
    # На какие фрагменты группы она опирается.
    evidence: list[int]
    reason: str
    # Кто предложил: человек видит, судья — нет.
    models: list[str]


class IdeaProposal(BaseModel):
    """Что предлагает совет. idea None — не предлагает: никто из участников не взялся
    восстановить идею или судья не принял ни один вариант; reason — почему."""

    idea: str | None
    evidence: list[int] = []
    reason: str
    # agreed — вариант один, судья не понадобился; judge — решал судья.
    decided_by: Literal["agreed", "judge"]
    # Какой из IdeaDiscovery.options предложен как есть; None — судья свёл формулировки.
    option: int | None = None


class IdeaDiscovery(BaseModel):
    """Поиск идеи группы, в тексте которой её нет: участники по отдельности, судья — если
    вариантов несколько. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    steps: list[Step]
    options: list[IdeaOption] = []
    proposal: IdeaProposal | None = None
    error: str | None = None


class StreamIdea(BaseModel):
    """Идея потока, утверждённая человеком."""

    text: str
    # text — записана в тексте (фрагменты-идеи группы); council — вариант совета как есть;
    # human — формулировка человека.
    by: Literal["text", "council", "human"]
    evidence: list[int] = []


class Evidence(BaseModel):
    """Где в репозитории подтверждение: файл, строки, символ."""

    path: str
    lines: str | None = None
    symbol: str | None = None


class RepositoryFinding(BaseModel):
    """Факт о том, как система устроена сейчас. verified — подтверждён кодом (evidence есть),
    inferred — следует из наблюдений, unknown — установить не удалось."""

    id: str
    statement: str
    status: Literal["verified", "inferred", "unknown"]
    evidence: list[Evidence] = []
    relevance: str = ""


class FlowStep(BaseModel):
    description: str
    finding_ids: list[str] = []


class RepositoryFlow(BaseModel):
    """Как поведение проходит через систему: откуда начинается и через что идёт."""

    name: str
    entry_point: str = ""
    steps: list[FlowStep] = []


class CoverageArea(BaseModel):
    """Насколько исследована область репозитория относительно идеи."""

    area: str
    status: Literal["covered", "partial", "not_investigated", "not_applicable"]
    evidence_ids: list[str] = []
    reason: str = ""


class RepositoryUnknown(BaseModel):
    """Что установить не удалось, почему это важно и где искать дальше."""

    question: str
    reason: str = ""
    investigate: list[str] = []


class FollowUp(BaseModel):
    """Задание на доисследование от судьи: что установить и где."""

    objective: str
    reason: str = ""
    targets: list[str] = []
    related_finding_ids: list[str] = []


class RepositoryMap(BaseModel):
    """Проверенная карта существующей реализации: факты, потоки выполнения, покрытие и
    неизвестное. Описывает, как система устроена сейчас, а не как её менять."""

    findings: list[RepositoryFinding] = []
    flows: list[RepositoryFlow] = []
    coverage: list[CoverageArea] = []
    unknowns: list[RepositoryUnknown] = []
    documentation_conflicts: list[str] = []


# Поля рабочей копии, как их хранил скан, пока она была у него одна.
SOURCE_FIELDS = ("path", "root", "commit_sha", "dirty", "files", "outside", "omitted",
                 "omitted_count")


class ScannedRepository(BaseModel):
    """Рабочая копия скана: путь, как его ввёл человек, корень, к которому он тогда привёл
    (каталог репозиториев могут и поменять), её коммит и что о ней известно."""

    # Папка в снимке: у нескольких рабочих копий пути их файлов — «name/…», у одной — без неё.
    name: str = ""
    path: str = ""
    root: str = ""
    commit_sha: str = ""
    # Есть незакоммиченные правки: модели читают рабочую копию, а не коммит.
    dirty: bool = False
    # Сколько файлов в inventory.
    files: int = 0
    # Сколько файлов коммита вне sparse checkout: их нет ни на диске, ни в снимке.
    outside: int = 0
    # Чего нет в снимке, хоть оно и в рабочей копии (нескачанные подмодули, ссылки), с
    # причиной. Список — первые, в пределах бюджета (карта идёт в каждый промпт ниже),
    # omitted_count — сколько всего.
    omitted: list[str] = []
    omitted_count: int = 0


class RepositoryScan(BaseModel):
    """Скан репозиториев под идею потока: inventory каждой рабочей копии при запуске,
    участники исследуют их вместе, судья проверяет и, если пробелы существенны, отправляет их
    доисследовать — до двух раз. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # К какой идее и каким рабочим копиям.
    idea: str = ""
    repositories: list[ScannedRepository] = []
    # Сколько проходов участников и судьи понадобилось.
    rounds: int = 0
    steps: list[Step]
    # complete — судья счёл исследование достаточным; иначе остались задания follow_up.
    complete: bool = False
    result: RepositoryMap | None = None
    follow_up: list[FollowUp] = []
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def one_repository(cls, data: object) -> object:
        """Скан, сохранённый, пока рабочая копия была у него одна: её поля — первая в
        repositories."""
        if isinstance(data, dict) and "repositories" not in data and "path" in data:
            source = {key: data[key] for key in SOURCE_FIELDS if key in data}
            rest = {key: value for key, value in data.items() if key not in SOURCE_FIELDS}
            return {**rest, "repositories": [source]}
        return data


# Шаг «Репозиторий» пропущен: так его помнят вопросы.
SKIPPED = "skipped"


class RepositoryStep(BaseModel):
    """Шаг «Репозиторий», как его прошёл человек: пропустил или утвердил карту скана."""

    # skipped — без скана; scan — с картой скана scan_run.
    by: Literal["skipped", "scan"]
    scan_run: str = ""


class DesignNode(BaseModel):
    """Узел макета Figma: страница, сам узел и его имя — на что ссылаются находки и задания."""

    page_id: str = ""
    node_id: str = ""
    name: str = ""


class DesignFinding(BaseModel):
    """Факт о макете: что в нём предусмотрено. verified — видно в макете (evidence есть),
    inferred — следует из его структуры, unknown — установить не удалось."""

    id: str
    statement: str
    status: Literal["verified", "inferred", "unknown"]
    evidence: list[DesignNode] = []
    relevance: str = ""


class DesignAction(BaseModel):
    """Действие пользователя на экране и что оно даёт, если это видно в макете."""

    action: str
    result: str | None = None
    status: Literal["verified", "inferred", "unknown"] = "unknown"
    finding_ids: list[str] = []


class DesignState(BaseModel):
    name: str
    node_id: str = ""


class DesignScreen(BaseModel):
    """Экран макета: зачем он, какие данные показывает и принимает, что на нём можно сделать
    и в каких состояниях он нарисован."""

    name: str
    node_id: str = ""
    purpose: str = ""
    data: list[str] = []
    actions: list[DesignAction] = []
    states: list[DesignState] = []


class DesignFlow(BaseModel):
    """Сценарий пользователя через экраны макета."""

    name: str
    steps: list[FlowStep] = []
    status: Literal["verified", "inferred", "unknown"] = "unknown"


class DesignCoverage(BaseModel):
    """Насколько исследована область макета относительно идеи."""

    area: str
    status: Literal["covered", "partial", "not_investigated", "not_applicable"]
    reason: str = ""


class DesignUnknown(BaseModel):
    """Что по макету установить не удалось, почему это важно и где смотреть дальше."""

    question: str
    reason: str = ""
    investigate: list[DesignNode] = []


class DesignFollowUp(BaseModel):
    """Задание на доисследование макета от судьи: что установить и в каких узлах."""

    objective: str
    reason: str = ""
    targets: list[DesignNode] = []
    related_finding_ids: list[str] = []


class DesignMap(BaseModel):
    """Проверенное описание макета: факты, экраны, сценарии, покрытие, неизвестное и
    противоречия. Описывает, что предусмотрено в дизайне, а не как это реализовать."""

    findings: list[DesignFinding] = []
    screens: list[DesignScreen] = []
    flows: list[DesignFlow] = []
    coverage: list[DesignCoverage] = []
    unknowns: list[DesignUnknown] = []
    design_conflicts: list[str] = []


class FigmaSource(BaseModel):
    """Какой макет читали: файл Figma, его версия и что из него легло в снимок."""

    file_key: str = ""
    name: str = ""
    # Версия файла в Figma: снимок взят ровно с неё, даже если файл правили, пока он делался.
    version: str = ""
    last_modified: str = ""
    # Узлы из ссылок: страницы или фреймы, с которых начинают.
    requested: list[DesignNode] = []
    # Сколько страниц легло в снимок целиком и сколько фреймов отрисовано картинками.
    pages: int = 0
    images: int = 0


class DesignScan(BaseModel):
    """Скан макета Figma под идею потока: снимок файла — страниц из ссылок, со структурой и
    картинками фреймов, — участники исследуют его, судья проверяет и, если пробелы
    существенны, отправляет их доисследовать — до двух раз. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # К какой идее и каким ссылкам; source — что легло в снимок (пусто, пока его нет).
    idea: str = ""
    links: list[str] = []
    source: FigmaSource | None = None
    rounds: int = 0
    steps: list[Step]
    complete: bool = False
    result: DesignMap | None = None
    follow_up: list[DesignFollowUp] = []
    error: str | None = None


class DesignStep(BaseModel):
    """Шаг «Дизайн», как его прошёл человек: пропустил или утвердил описание скана макета."""

    by: Literal["skipped", "scan"]
    scan_run: str = ""


class CodeTrail(BaseModel):
    """След решения в коде: коммит с номером задачи, которая реализовала итог этого решения, в
    файле, который новая идея, по карте репозитория, будет затрагивать."""

    issue: str
    outcome: str
    commit: str
    file: str


class ProjectDecision(BaseModel):
    """Принятое решение проекта из каталога заметок, каким его видят шаги потока: номер, к
    какой идее, на какой вопрос и что решено, действует ли оно, его след в коде — и, когда
    его отобрали, насколько и почему оно относится к идее потока."""

    adr_id: str
    idea: str = ""
    question: str = ""
    decision: str = ""
    status: Literal["active", "under_review", "superseded"] = "active"
    superseded_by: str | None = None
    found_in_code: list[CodeTrail] = []
    relevance: Literal["applicable", "potential_conflict", "uncertain"] | None = None
    reason: str = ""


class DecisionsSearch(BaseModel):
    """Отбор прошлых решений проекта для потока — в начале шага «Вопросы», когда в каталоге
    заметок есть решения: участники по отдельности отбирают относящиеся к идее (с учётом их
    следа в коде), судья сводит отбор, человек отмечает нужные. К какой идее, карте и
    описанию макета — как у поиска вопросов. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    idea: str = ""
    repository: str = ""
    design: str = ""
    # Сколько решений в каталоге и сколько из них со следом в коде.
    catalog: int = 0
    traced: int = 0
    # Отпечаток всего каталога решений, который видели модели (project.fingerprint): решение
    # добавили, поправили или убрали — отбор устарел.
    fingerprint: str = ""
    steps: list[Step]
    decisions: list[ProjectDecision] = []
    error: str | None = None


class OpenQuestion(BaseModel):
    """Открытый вопрос: что ещё неизвестно, чтобы идею можно было реализовать. Ответов в нём
    нет: предложения из текста связаны с ним через proposal_ids."""

    id: str
    text: str
    # user — вопрос из текста, дословно; inferred — незаписанный вопрос, на который отвечают
    # предложения группы; discovered — недостающий; added — добавил человек при отборе.
    source: Literal["user", "inferred", "discovered", "added"]
    # Фрагмент-вопрос, если вопрос из текста.
    source_question_id: int | None = None
    # Фрагменты-предложения группы, которые отвечают на этот вопрос.
    proposal_ids: list[int] = []
    reason: str | None = None
    # Для заметки: у вопроса из текста — та же неопределённость атомарно, одним предложением.
    note: str | None = None
    # Принятое решение проекта, которое вопрос пересматривает (ADR-0007), — из отобранных.
    revisits: str | None = None


class QuestionDiscovery(BaseModel):
    """Поиск открытых вопросов к утверждённой идее: участники по отдельности, судья сводит
    их списки в канонический. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # Идея, к которой ищут: утвердили другую — вопросы ищутся заново.
    idea: str = ""
    # С какой картой репозитория и каким описанием макета: «skipped» или run скана. Прошли
    # шаг иначе — ищут заново.
    repository: str = ""
    design: str = ""
    # С какими принятыми решениями проекта: номера, которые человек отобрал для потока.
    decisions: list[str] = []
    # Отпечаток отмеченных решений (project.fingerprint): решение с тем же номером переписали —
    # вопросы ищутся заново.
    decisions_seen: str = ""
    steps: list[Step]
    questions: list[OpenQuestion] = []
    error: str | None = None


class Proposal(BaseModel):
    """Новый вариант ответа на открытый вопрос, найденный советом. Варианты из текста группы —
    её фрагменты-предложения, они связаны с вопросом в OpenQuestion.proposal_ids."""

    # P1, P2… — сквозь все вопросы потока.
    id: str
    text: str
    reason: str
    # Ограничения и риски группы, которые вариант учитывает.
    constraint_ids: list[int] = []
    risk_ids: list[int] = []
    # Другие открытые вопросы потока, от решения которых он зависит.
    depends_on: list[str] = []
    # Судья счёл его обоснованно предпочтительным.
    recommended: bool = False


class QuestionOptions(BaseModel):
    """Что совет нашёл к одному вопросу: новые варианты и что о них сказал судья."""

    question_id: str
    proposals: list[Proposal] = []
    # recommended — один предпочтительный; alternatives — равноправные, выбор за человеком;
    # none — новых обоснованных вариантов нет.
    verdict: Literal["recommended", "alternatives", "none"]
    # Почему так: чем различаются альтернативы или почему вариантов нет.
    reason: str | None = None


class ProposalDiscovery(BaseModel):
    """Поиск новых вариантов ответа на отобранные вопросы потока: по вопросу за раз,
    участники по отдельности, судья решает, что показать. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # К какому отбору вопросов искали (id и формулировки): отобрали другие — ищут заново.
    scope: list[str] = []
    steps: list[Step]
    # По вопросу, по мере готовности.
    options: list[QuestionOptions] = []
    error: str | None = None


class Choice(BaseModel):
    """Выбор человека по вопросу: вариант (Fn — из текста группы, Pn — найденный советом)
    или None — пока не решает, вопрос уходит как unresolved."""

    question_id: str
    proposal: str | None = None


class QuestionAnalysis(BaseModel):
    """Что совет сказал по вопросу перед решением: проверил выбор человека или, если вопрос
    unresolved, сравнил его варианты. Новых вариантов здесь нет, выбор человека не меняется."""

    question_id: str
    # validated — выбор проверен, проблем нет; conflict — с выбором проблема (решать всё равно
    # человеку); recommended — для unresolved совет предлагает вариант; none — обоснованно
    # выбрать нельзя.
    verdict: Literal["validated", "conflict", "recommended", "none"]
    # Выбор человека (validated, conflict) или рекомендованный вариант (recommended): Fn или Pn.
    proposal: str | None = None
    # С какими ограничениями группы вариант расходится, какие её риски с ним связаны, от каких
    # других вопросов потока он зависит.
    constraint_conflicts: list[int] = []
    risk_ids: list[int] = []
    depends_on: list[str] = []
    # Почему так: в чём проблема, чем рекомендованный лучше, чего не хватает для выбора.
    reason: str | None = None
    # Обоснование решения, предложенное советом: в ADR — только если человек его подтвердит.
    rationale: str | None = None


class DecisionAnalysis(BaseModel):
    """Проверка выбора по отобранным вопросам потока: по вопросу за раз, участники по
    отдельности, судья сводит их анализы. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # К какому выбору проверяли: выбрали другое — проверяют заново.
    choices: list[str] = []
    steps: list[Step]
    # По вопросу, по мере готовности.
    analyses: list[QuestionAnalysis] = []
    error: str | None = None


class Decision(BaseModel):
    """Решение человека по вопросу — ADR: вариант и почему он. proposal None — вопрос оставлен
    открытым: решения и обоснования нет, и он заблокирует свои итоги."""

    question_id: str
    proposal: str | None = None
    rationale: str | None = None
    # ai — обоснование совета, человек подтвердил его как есть; human — своё или поправленное.
    rationale_by: Literal["ai", "human"] | None = None


class OutcomeGap(BaseModel):
    """Неопределённость, которой нет среди вопросов потока: материал для нового поиска
    вопросов, а не ответ на неё."""

    question: str
    reason: str = ""


class Outcome(BaseModel):
    """Итог — законченное изменение системы после принятых решений: что меняется, на каких
    решениях стоит, что соблюдать и как проверить. Вопрос без решения его блокирует:
    недостающее не додумывается."""

    # O1, O2… по порядку.
    id: str
    title: str
    behavior: str
    # Принятые решения (ADR-n — n-й вопрос отбора), из которых он следует.
    adr_ids: list[str] = []
    constraint_ids: list[int] = []
    risk_ids: list[int] = []
    acceptance_criteria: list[str] = []
    # Открытые вопросы потока, без решения которых его поведение не определить.
    blocked_by: list[str] = []
    gaps: list[OutcomeGap] = []


class OutcomeDiscovery(BaseModel):
    """Сборка итогов потока из его решений: участники по отдельности, судья сводит их в
    итоговый набор. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # К каким решениям собирали: зафиксировали другие — собирают заново.
    decisions: list[str] = []
    steps: list[Step]
    outcomes: list[Outcome] = []
    # Принятые решения, не вошедшие ни в один итог.
    uncovered_adr_ids: list[str] = []
    error: str | None = None


class IssueGap(BaseModel):
    """Неопределённость, без решения которой часть работы не начать: материал для нового
    открытого вопроса, а не ответ на него."""

    # G1, G2… по порядку: на него ссылается blocked_by задачи.
    id: str
    question: str
    reason: str = ""
    outcome_ids: list[str] = []


class Issue(BaseModel):
    """Задача для coding agent — законченная часть одного или нескольких утверждённых итогов:
    кому и зачем (user story), где менять (точки входа и что там сейчас) и что именно сделать
    (scope). Задача, которой не хватает решения, заблокирована: недостающее не додумывается."""

    # I1, I2… по порядку.
    id: str
    title: str
    user_story: str
    main_entry_points: list[str] = []
    current_state: str = ""
    scope: list[str] = []
    outcome_ids: list[str] = []
    adr_ids: list[str] = []
    constraint_ids: list[int] = []
    risk_ids: list[int] = []
    # Задачи, результат которых нужен этой.
    depends_on: list[str] = []
    # Пробелы нарезки (G-n) и открытые вопросы потока, без решения которых её не сделать.
    blocked_by: list[str] = []
    # Когда готовы её итоги: их критерии — из итогов, а не от модели, — доходят до агента.
    acceptance_criteria: list[str] = []


NoteType = Literal["idea", "open_question", "proposal", "adr", "outcome"]


class NotePlan(BaseModel):
    """Заметка, какой она ляжет в каталог при выгрузке. key — какая это часть потока (идея,
    вопрос, вариант, решение, итог): по нему повторная выгрузка находит свою прежнюю заметку.
    generated — текст от совета; text — что предлагается записать (прежний, если совет
    написал бы то же самое, — с правками человека). action: create — новая; update — файл
    перепишется; same — в файле уже это; edited — файл правили руками после выгрузки, совет его
    не трогает."""

    key: str
    id: str
    type: NoteType
    text: str
    generated: str
    links: list[str] = []
    action: Literal["create", "update", "same", "edited"]
    # Что в файле сейчас — у update и edited.
    current: str | None = None
    # Ключ части прошлой выгрузки, которую заметка продолжает: обычно тот же key, но у итога
    # с поправленным поведением ключ другой, а заметка — та же.
    was: str | None = None


class VanishedNote(BaseModel):
    """Заметка прежней выгрузки, которой в потоке больше нет. Сама не удаляется: удалить её
    можно, только если на неё не ссылается ничего вне потока (linked_from)."""

    id: str
    type: NoteType
    text: str
    linked_from: list[str] = []


class IssueNumber(BaseModel):
    """Номер задачи на весь проект (ISS-0012): его пишут в финальный коммит, и по нему скан
    репозитория находит, под какие решения сделан код."""

    key: str
    id: str
    issue_id: str
    title: str
    outcome_ids: list[str] = []


class NotesDraft(BaseModel):
    """Черновик выгрузки потока в заметки: что ляжет, что изменится, что исчезло и номера
    задач. Собирается сразу; если язык документации другой, — ход судьи с переводом. К
    каким задачам собран (issues): нарезали заново — черновик устарел."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    issues: str = ""
    language: str = ""
    steps: list[Step] = []
    notes: list[NotePlan] = []
    vanished: list[VanishedNote] = []
    numbers: list[IssueNumber] = []
    # Что не выгружается и почему: итог без решений, решение из другой идеи в итоге.
    skipped: list[str] = []
    error: str | None = None


class ExportedNote(BaseModel):
    """Заметка, как её выгрузили: из какой части потока, под каким номером, что сгенерировал
    совет, что записали и отпечаток файла — по нему видно, правили ли его потом руками."""

    key: str
    id: str
    type: NoteType
    generated: str
    written: str
    links: list[str] = []
    digest: str
    # Исчезла из потока, а человек оставил её в каталоге: заметка всё ещё потока — её решения
    # не «прошлые» для него, и повторная выгрузка снова предложит её удалить.
    kept: bool = False


class NotesExport(BaseModel):
    """Последняя выгрузка потока: по ней повторная находит свои заметки и номера задач."""

    run: str
    issues: str
    language: str
    notes: list[ExportedNote] = []
    numbers: list[IssueNumber] = []


class IssueDiscovery(BaseModel):
    """Нарезка утверждённых итогов на задачи: участники по отдельности, судья сводит их в
    итоговый набор. Если шаг «Репозиторий» пройден сканом, модели читают снимок той же
    рабочей копии заново — точки входа проверяются по коду. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # К каким итогам нарезали (OutcomeDiscovery.run): собрали другие — нарезают заново.
    outcomes: str = ""
    # С какого кода нарезали: code — читали ли его вообще (без скана — нет), и каждая рабочая
    # копия — имя в снимке, путь, коммит и правки.
    code: bool = False
    sources: list[ScannedRepository] = []
    steps: list[Step]
    issues: list[Issue] = []
    gaps: list[IssueGap] = []
    # Утверждённые итоги, не вошедшие ни в одну задачу: считает код, а не модель.
    uncovered_outcome_ids: list[str] = []
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def one_source(cls, data: object) -> object:
        """Нарезка, сохранённая, пока рабочая копия была одна: её коммит и правки — первая в
        sources."""
        if isinstance(data, dict) and "sources" not in data and "commit_sha" in data:
            rest = {key: value for key, value in data.items()
                    if key not in ("commit_sha", "dirty")}
            sources = [{"commit_sha": data["commit_sha"], "dirty": data.get("dirty", False)}]
            return {**rest, "sources": sources if data.get("code") else []}
        return data


class Stream(BaseModel):
    """Поток — подтверждённая группа под той же буквой. Его цепочка: идея — у группы без неё
    её ищет совет (discovery), утверждает человек (idea); потом необязательный скан
    репозитория — его ведёт совет (scan), а человек утверждает карту или пропускает шаг
    (repository), и карта идёт во все следующие шаги; потом так же необязательный скан
    макета Figma (design_scan) и шаг «Дизайн» (design); потом вопросы — их ищет совет
    (questions), а человек отбирает, какие решать (scope); потом варианты ответа — их ищет
    совет (proposals), а человек выбирает по варианту на вопрос или оставляет его unresolved
    (choices); потом совет проверяет выбор и подбирает вариант для unresolved (analysis), а
    человек фиксирует решения (decisions); из них совет собирает итоги (outcomes), а
    утверждённые человеком итоги нарезает на задачи для coding agents (issues)."""

    group: str
    discovery: IdeaDiscovery | None = None
    idea: StreamIdea | None = None
    scan: RepositoryScan | None = None
    repository: RepositoryStep | None = None
    design_scan: DesignScan | None = None
    design: DesignStep | None = None
    # Отбор прошлых решений проекта и что человек из него взял (None — блок не пройден).
    decisions_search: DecisionsSearch | None = None
    project_decisions: list[ProjectDecision] | None = None
    questions: QuestionDiscovery | None = None
    # Вопросы, которые человек оставил и добавил: их и решает поток дальше.
    scope: list[OpenQuestion] | None = None
    proposals: ProposalDiscovery | None = None
    choices: list[Choice] | None = None
    analysis: DecisionAnalysis | None = None
    decisions: list[Decision] | None = None
    outcomes: OutcomeDiscovery | None = None
    issues: IssueDiscovery | None = None
    # Черновик выгрузки в заметки и последняя выгрузка. Выгрузку правки выше не сбрасывают:
    # по ней повторная находит свои прежние заметки.
    notes_draft: NotesDraft | None = None
    notes: NotesExport | None = None


# Ходы потока по его цепочке: поиск идеи, скан репозитория, скан макета, поиск вопросов,
# вариантов, проверка выбора, сборка итогов, нарезка на задачи.
STREAM_RUNS = ("discovery", "scan", "design_scan", "decisions_search", "questions",
               "proposals", "analysis", "outcomes", "issues", "notes_draft")


class Council(BaseModel):
    id: str
    name: str
    status: CouncilStatus
    brief: str
    # Каждый участник предлагает свой вариант, не видя чужих; судья выбирает лучший.
    participants: list[str]
    judge: str
    # Момент, а не дата: две правки за один день должны различаться порядком в списке.
    updated_at: datetime
    slicing: Slicing | None = None
    structure: Structure | None = None
    # Потоки подтверждённых групп, по их порядку. None — группы ещё не подтверждены.
    streams: list[Stream] | None = None


class CouncilCreated(BaseModel):
    """Ответ на создание: фронт сразу уходит на страницу проекта."""

    id: str


class CouncilPatch(BaseModel):
    """Правка с экрана: меняются только присланные поля, null значит «не менять»."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    brief: str | None = None
    participants: list[str] | None = None
    judge: str | None = None
    # Типы фрагментов готовой нарезки: {id: тип}. Только изменённые, остальные не трогаются.
    labels: dict[int, Label] | None = None
    # К какой нарезке относятся labels: Slicing.run. Обязателен вместе с ними.
    slicing_run: str | None = None


class GroupsEdit(BaseModel):
    """Правка готовых групп человеком: к какой раскладке (Structure.run) и какой версии её
    групп (Structure.revision) она сделана."""

    model_config = ConfigDict(extra="forbid")

    run: str
    revision: int


class MergeGroups(GroupsEdit):
    # Где нажали «Объединить с…»: её буква и название остаются.
    group: str
    other: str


class SplitGroup(GroupsEdit):
    group: str
    # Что уходит в новую группу; остальное остаётся.
    fragment_ids: list[int]
    title: str


class RenameGroup(GroupsEdit):
    group: str
    title: str


class ApproveIdea(GroupsEdit):
    """Человек утверждает идею потока. text — его формулировка; у группы, где идея записана
    в тексте, её не правят, и text нет."""

    text: str | None = None


# Сколько рабочих копий можно сканировать разом: у каждой свои вызовы git.
REPOSITORIES_MAX = 10


class ScanRepository(GroupsEdit):
    """Человек запускает скан репозиториев потока: пути к рабочим копиям — абсолютные или от
    каталога репозиториев (COUNCIL_REPOS); бэкенд и фронтенд в разных репозиториях — два пути.
    idea — идея, которую человек видел: её поменяли в другой вкладке — 409, а не скан под
    идею, которой он не видел."""

    paths: list[str] = Field(min_length=1, max_length=REPOSITORIES_MAX)
    idea: str


class ApproveRepository(GroupsEdit):
    """Человек проходит шаг «Репозиторий»: scan_run — утверждает карту этого скана, None —
    пропускает шаг. Дальше — шаг «Дизайн». idea — идея, которую человек видел."""

    scan_run: str | None = None
    idea: str


# Сколько ссылок на макет можно дать разом: страницы и фреймы одного файла.
LINKS_MAX = 10


class ScanDesign(GroupsEdit):
    """Человек запускает скан макета потока: ссылки на страницы или фреймы одного файла Figma
    (без node-id — весь файл). idea — идея, которую человек видел."""

    links: list[str] = Field(min_length=1, max_length=LINKS_MAX)
    idea: str


class ApproveDesign(GroupsEdit):
    """Человек проходит шаг «Дизайн»: scan_run — утверждает описание этого скана макета, None
    — пропускает шаг. И совет сразу ищет вопросы. idea — идея, которую человек видел."""

    scan_run: str | None = None
    idea: str


class SelectDecisions(GroupsEdit):
    """Человек отмечает, какие прошлые решения проекта учитывать в потоке: keep — номера из
    отбора search_run (пусто — ни одного), и совет сразу ищет вопросы. search_run — отбор, что
    был на экране, и для «ни одного» тоже, хоть упавший. idea — идея, которую человек видел."""

    search_run: str | None = None
    keep: list[str] = []
    idea: str


class ApproveScope(GroupsEdit):
    """Человек утверждает, какие вопросы потоку решать: оставленные из найденных (их id) и
    свои, добавленные при отборе (тексты). questions_run — к какому поиску (QuestionDiscovery
    .run): каждый поиск нумерует вопросы с Q1, и отбор к прежнему лёг бы на чужие вопросы."""

    questions_run: str
    keep: list[str]
    added: list[str] = []


class ApproveChoices(GroupsEdit):
    """Человек утверждает выбор: по каждому отобранному вопросу — вариант или None
    (unresolved). proposals_run — к какому поиску вариантов: их номера у каждого свои."""

    proposals_run: str
    choices: list[Choice]


class DecisionDraft(BaseModel):
    """Решение по вопросу, как его фиксирует человек: вариант и обоснование, или None —
    вопрос остаётся открытым, и обоснование тогда не нужно."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    proposal: str | None = None
    rationale: str | None = None


class ApproveDecisions(GroupsEdit):
    """Человек фиксирует решения: по каждому отобранному вопросу — вариант с обоснованием или
    открытый вопрос. analysis_run — к какой проверке выбора (DecisionAnalysis.run)."""

    analysis_run: str
    decisions: list[DecisionDraft]


class ApproveOutcomes(GroupsEdit):
    """Человек утверждает итоги потока — и совет нарезает их на задачи. outcomes_run — какие
    итоги были на экране (OutcomeDiscovery.run): собрали заново — 409."""

    outcomes_run: str


class Model(BaseModel):
    alias: str
    short_name: str
    display_name: str
    cli: str
    # Есть подключение к CLI: провайдер известен и каталог учётной записи задан.
    available: bool = False


class Settings(BaseModel):
    models: list[Model]
    # Каталог репозиториев для скана (COUNCIL_REPOS): пути — от него. None — путь абсолютный.
    repositories: str | None = None
    # Задан ли токен Figma (FIGMA_TOKEN): без него макет не сканировать.
    figma: bool = False
    # Каталог заметок проекта (COUNCIL_NOTES): без него поток не выгрузить.
    notes: str | None = None
    min_participants: int
    default_participants: list[str]
    default_judge: str
