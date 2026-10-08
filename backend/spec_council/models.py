"""Контракт API: то, что видит фронт. Меняется только вместе с фронтом."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field


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
    question_discovery = "question_discovery"  # участники ищут открытые вопросы к идее
    question_judge = "question_judge"          # судья сводит их в один канонический список
    proposal_discovery = "proposal_discovery"  # участники ищут новые варианты ответа на вопрос
    proposal_judge = "proposal_judge"          # судья решает, какие из них показать
    decision_analysis = "decision_analysis"  # участники проверяют выбор или сравнивают варианты
    decision_judge = "decision_judge"        # судья сводит их анализы в один итог по вопросу
    outcome_discovery = "outcome_discovery"  # участники собирают решения в изменения системы
    outcome_judge = "outcome_judge"          # судья выбирает и сводит их в итоговый набор


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


class RepositoryScan(BaseModel):
    """Скан репозитория под идею потока: inventory при запуске, участники исследуют, судья
    проверяет и, если пробелы существенны, отправляет их доисследовать — до двух раз. Ход по
    шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # К какой идее и какому репозиторию: путь, как его ввёл человек, и его коммит.
    idea: str = ""
    path: str = ""
    commit_sha: str = ""
    # В рабочей копии есть незакоммиченные правки: модели читают её, а не коммит.
    dirty: bool = False
    # Сколько файлов в inventory и сколько проходов участников и судьи понадобилось.
    files: int = 0
    rounds: int = 0
    steps: list[Step]
    # complete — судья счёл исследование достаточным; иначе остались задания follow_up.
    complete: bool = False
    result: RepositoryMap | None = None
    follow_up: list[FollowUp] = []
    error: str | None = None


class RepositoryStep(BaseModel):
    """Шаг «Репозиторий», как его прошёл человек: пропустил или утвердил карту скана."""

    # skipped — без скана; scan — с картой скана scan_run.
    by: Literal["skipped", "scan"]
    scan_run: str = ""


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


class QuestionDiscovery(BaseModel):
    """Поиск открытых вопросов к утверждённой идее: участники по отдельности, судья сводит
    их списки в канонический. Ход по шагам и итог."""

    state: Literal["running", "done", "failed"]
    run: str = ""
    # Идея, к которой ищут: утвердили другую — вопросы ищутся заново.
    idea: str = ""
    # С какой картой репозитория: «skipped» или run скана. Прошли шаг иначе — ищут заново.
    repository: str = ""
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


class Stream(BaseModel):
    """Поток — подтверждённая группа под той же буквой. Его цепочка: идея — у группы без неё
    её ищет совет (discovery), утверждает человек (idea); потом необязательный скан
    репозитория — его ведёт совет (scan), а человек утверждает карту или пропускает шаг
    (repository), и карта идёт во все следующие шаги; потом вопросы — их ищет совет
    (questions), а человек отбирает, какие решать (scope); потом варианты ответа — их ищет
    совет (proposals), а человек выбирает по варианту на вопрос или оставляет его unresolved
    (choices); потом совет проверяет выбор и подбирает вариант для unresolved (analysis), а
    человек фиксирует решения (decisions); из них совет собирает итоги (outcomes)."""

    group: str
    discovery: IdeaDiscovery | None = None
    idea: StreamIdea | None = None
    scan: RepositoryScan | None = None
    repository: RepositoryStep | None = None
    questions: QuestionDiscovery | None = None
    # Вопросы, которые человек оставил и добавил: их и решает поток дальше.
    scope: list[OpenQuestion] | None = None
    proposals: ProposalDiscovery | None = None
    choices: list[Choice] | None = None
    analysis: DecisionAnalysis | None = None
    decisions: list[Decision] | None = None
    outcomes: OutcomeDiscovery | None = None


# Ходы потока по его цепочке: поиск идеи, скан репозитория, поиск вопросов, вариантов,
# проверка выбора, сборка итогов.
STREAM_RUNS = ("discovery", "scan", "questions", "proposals", "analysis", "outcomes")


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


class ScanRepository(GroupsEdit):
    """Человек запускает скан репозитория потока: путь к рабочей копии — абсолютный или от
    каталога репозиториев (COUNCIL_REPOS)."""

    path: str


class ApproveRepository(GroupsEdit):
    """Человек проходит шаг «Репозиторий»: scan_run — утверждает карту этого скана, None —
    пропускает шаг. И совет сразу ищет вопросы."""

    scan_run: str | None = None


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
    min_participants: int
    default_participants: list[str]
    default_judge: str
