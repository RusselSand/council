"""Контракт API: то, что видит фронт. Меняется только вместе с фронтом."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class CouncilStatus(StrEnum):
    brief = "brief"
    slices = "slices"
    structure = "structure"
    review = "review"
    ready = "ready"


Label =Literal["idea", "question", "proposal", "constraint", "risk"]
RunState = Literal["waiting", "running", "done", "failed"]


class SlicingStepName(StrEnum):
    slice = "slice"              # участники нарезают текст, каждый сам по себе
    slice_judge = "slice_judge"  # судья выбирает нарезку, если участники разошлись
    label = "label"              # участники размечают итоговые фрагменты
    label_judge = "label_judge"  # судья решает фрагменты, где типы разошлись


class ModelRun(BaseModel):
    model: str
    state: RunState = "waiting"
    error: str | None = None


class SlicingStep(BaseModel):
    name: SlicingStepName
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
    # Текст, который нарезали: исходник мог поменяться после запуска.
    text: str = ""
    steps: list[SlicingStep]
    fragments: list[LabeledFragment] = []
    error: str | None = None


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
    # Типы фрагментов готовой нарезки, все сразу: {id: тип}. Так повторная отправка безопасна.
    labels: dict[int, Label] | None = None


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
