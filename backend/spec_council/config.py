"""Настройки инструмента: доступные модели, кто по умолчанию в совете и кто судья.

Пока константы. Когда появится чтение из env или файла, поменяется только
сборка AppConfig — роуты берут её через deps.ConfigDep.
"""

from dataclasses import dataclass, field

from .models import Model

# Меньше двух — сравнивать судье нечего.
MIN_PARTICIPANTS = 2


@dataclass(frozen=True)
class Agent:
    """Как запустить модель: провайдер agent-workers и имя модели в его CLI.

    Каталог учётной записи — не здесь, а в .env: COUNCIL_<ALIAS>_HOME. Там токены входа.
    """

    provider: str
    model: str


@dataclass(frozen=True)
class AppConfig:
    models: list[Model] = field(default_factory=list)
    default_participants: list[str] = field(default_factory=list)
    default_judge: str = ""
    # Модели без записи здесь в совете видны, но запустить их нечем.
    agents: dict[str, Agent] = field(default_factory=dict)


DEFAULT_CONFIG = AppConfig(
    models=[
        Model(alias="sol", short_name="Sol", display_name="GPT-5.6 Sol", cli="codex"),
        Model(alias="fable", short_name="Fable", display_name="Claude Fable 5.1", cli="claude"),
        Model(alias="astra", short_name="Astra", display_name="Gemini Astra 3", cli="gemini"),
    ],
    default_participants=["sol", "fable"],
    default_judge="fable",
    # У agent-workers нет провайдера Gemini, поэтому astra пока не запускается.
    agents={
        "sol": Agent(provider="codex", model="gpt-5.6-sol"),
        "fable": Agent(provider="claude", model="claude-fable-5-1"),
    },
)
