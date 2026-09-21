"""Контракт API: то, что видит фронт. Меняется только вместе с фронтом."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class RunStatus(StrEnum):
    brief = "brief"
    approaches = "approaches"
    decisions = "decisions"
    review = "review"
    ready = "ready"


class Run(BaseModel):
    id: str
    name: str
    status: RunStatus
    author: str
    reviewer: str
    updated_at: date


class RunCreated(BaseModel):
    """Ответ на создание: фронт сразу уходит на страницу проекта."""

    id: str


class Model(BaseModel):
    alias: str
    display_name: str


class Settings(BaseModel):
    models: list[Model]
    default_author: str
    default_reviewer: str
