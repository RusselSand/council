"""Настройки инструмента: доступные модели, кто по умолчанию в совете и кто судья.

Пока константы. Когда появится чтение из env или файла, поменяется только
сборка AppConfig — роуты берут её через deps.ConfigDep.
"""

from dataclasses import dataclass, field

from .models import Model

# Меньше двух — сравнивать судье нечего.
MIN_PARTICIPANTS = 2


@dataclass(frozen=True)
class AppConfig:
    models: list[Model] = field(default_factory=list)
    default_participants: list[str] = field(default_factory=list)
    default_judge: str = ""


DEFAULT_CONFIG = AppConfig(
    models=[
        Model(alias="sol", short_name="Sol", display_name="GPT-5.6 Sol", cli="codex"),
        Model(alias="fable", short_name="Fable", display_name="Claude Fable 5.1", cli="claude"),
        Model(alias="astra", short_name="Astra", display_name="Gemini Astra 3", cli="gemini"),
    ],
    default_participants=["sol", "fable"],
    default_judge="fable",
)
