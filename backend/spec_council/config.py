"""Настройки инструмента: доступные модели и кто по умолчанию автор и ревьюер.

Пока константы. Когда появится чтение из env или файла, поменяется только
сборка AppConfig — роуты берут её через deps.ConfigDep.
"""

from dataclasses import dataclass, field

from .models import Model


@dataclass(frozen=True)
class AppConfig:
    models: list[Model] = field(default_factory=list)
    default_author: str = ""
    default_reviewer: str = ""


DEFAULT_CONFIG = AppConfig(
    models=[
        Model(alias="sol", display_name="GPT-5.6 Sol"),
        Model(alias="fable", display_name="Claude Fable 5.1"),
    ],
    default_author="sol",
    default_reviewer="fable",
)
