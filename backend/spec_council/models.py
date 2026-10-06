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


class Stream(BaseModel):
    """Поток — подтверждённая группа под той же буквой. Первый шаг его цепочки — идея: у
    группы без неё идею ищет совет (discovery), утверждает человек (idea)."""

    group: str
    discovery: IdeaDiscovery | None = None
    idea: StreamIdea | None = None


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


class Model(BaseModel):
    alias: str
    short_name: str
    display_name: str
    cli: str
    # Есть подключение к CLI: провайдер известен и каталог учётной записи задан.
    available: bool = False


class Settings(BaseModel):
    models: list[Model]
    min_participants: int
    default_participants: list[str]
    default_judge: str
