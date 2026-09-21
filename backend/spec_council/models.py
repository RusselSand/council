"""Контракт API: то, что видит фронт. Меняется только вместе с фронтом."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class CouncilStatus(StrEnum):
    brief = "brief"
    approaches = "approaches"
    decisions = "decisions"
    review = "review"
    ready = "ready"


class Council(BaseModel):
    id: str
    name: str
    status: CouncilStatus
    author: str
    reviewer: str
    updated_at: date


class CouncilCreated(BaseModel):
    """Ответ на создание: фронт сразу уходит на страницу проекта."""

    id: str


class Model(BaseModel):
    alias: str
    display_name: str


class Settings(BaseModel):
    models: list[Model]
    default_author: str
    default_reviewer: str
