"""Настройки инструмента: какие модели в совете, на чём они работают и кто судья.

Совет задаёт человек в .env тремя переменными: участники — COUNCIL_PARTICIPANT_1 и
COUNCIL_PARTICIPANT_2 («имя=провайдер/модель»; второго нет — COUNCIL_PARTICIPANT_2=none) — и
судья COUNCIL_JUDGE: имя одного из них или третья модель «имя=провайдер/модель». Без настройки —
Sol (Codex) и Fable (Claude Code), судья Fable; участник один — судья он же. Каталог учётной записи
каждой модели — .accounts/<имя> (или COUNCIL_ACCOUNTS/<имя>, или COUNCIL_<ИМЯ>_HOME): там
токены входа, см. README. Роуты берут настройки через deps.ConfigDep.
"""

import re
from dataclasses import dataclass, field

from .models import Council, Model

# Участник может быть и один: его ответ проверяет судья. Больше двух пока не нужно.
MIN_PARTICIPANTS = 1
# COUNCIL_PARTICIPANT_2 с этим значением — второго участника нет. Пусто — по умолчанию.
NONE = "none"

# Через что agent-workers запускает модель: его провайдеры.
PROVIDERS = ("codex", "claude")
# Как показывать известные модели; неизвестная — как её назвали в настройке.
NAMES = {
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "claude-fable-5-1": "Claude Fable 5.1",
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
}
DEFAULT_PARTICIPANTS = ("sol=codex/gpt-5.6-sol", "fable=claude/claude-fable-5-1")
ENTRY = re.compile(r"([a-z][a-z0-9_-]{0,19})\s*=\s*([a-z]+)\s*/\s*([A-Za-z0-9._:-]+)")


class ConfigError(ValueError):
    """Модели совета заданы так, что совет не собрать. Текст — для человека."""


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


def entry_of(text: str, variable: str) -> tuple[str, str, str]:
    """Модель из настройки: «имя=провайдер/модель» — имя, провайдер, модель."""
    found = ENTRY.fullmatch(text.strip())
    if found is None:
        raise ConfigError(f"{variable}: «{text.strip()}» — нужно «имя=провайдер/модель», имя "
                          "латиницей с маленькой буквы")
    alias, provider, model = found.groups()
    if provider not in PROVIDERS:
        raise ConfigError(f"{variable}: у «{alias}» провайдер {provider}, а есть только "
                          f"{' и '.join(PROVIDERS)}")
    return alias, provider, model


def config_of(first: str | None = "", second: str | None = "",
              judge: str | None = "") -> AppConfig:
    """Совет из настройки: участники «имя=провайдер/модель» — два или один (второй — none) — и
    судья — имя одного из них или третья модель. Пусто или не задано (None) — как по умолчанию;
    судья не задан — последний участник: второй, а у одного — он же."""
    participants = [entry_of(first or DEFAULT_PARTICIPANTS[0], "COUNCIL_PARTICIPANT_1")]
    if (second or "").strip().lower() != NONE:
        participants.append(entry_of(second or DEFAULT_PARTICIPANTS[1], "COUNCIL_PARTICIPANT_2"))
    if len(participants) == 2 and participants[0][0] == participants[1][0]:
        raise ConfigError(f"COUNCIL_PARTICIPANT_1 и _2: имя {participants[0][0]} у обоих — "
                          "нужны разные")
    known = {alias: (alias, provider, model) for alias, provider, model in participants}
    judge = (judge or "").strip() or participants[-1][0]
    if "=" in judge:
        entry = entry_of(judge, "COUNCIL_JUDGE")
        if entry[0] in known and known[entry[0]] != entry:
            raise ConfigError(f"COUNCIL_JUDGE: имя {entry[0]} уже у участника с другой моделью")
        known.setdefault(entry[0], entry)
        judge = entry[0]
    elif judge not in known:
        raise ConfigError(f"COUNCIL_JUDGE: {judge} — не участник; третью модель задайте как "
                          "«имя=провайдер/модель»")
    return AppConfig(
        models=[Model(alias=alias, short_name=alias.capitalize(),
                      display_name=NAMES.get(model, model), cli=provider)
                for alias, provider, model in known.values()],
        default_participants=[alias for alias, _, _ in participants],
        default_judge=judge,
        agents={alias: Agent(provider=provider, model=model)
                for alias, provider, model in known.values()},
    )


def fitted(council: Council, config: AppConfig) -> Council:
    """Совет под нынешнюю настройку. Участник, которого больше нет среди моделей, уходит, и
    его место, пока есть кем, занимают заданные: совет из двух остаётся из двух, если в .env
    их хоть двое; выбранные в совете и всё ещё настроенные остаются. Судья — свой, если он
    среди моделей, иначе заданный. Поменяли модели в .env — старые советы работают на новых, а
    не падают на «нет подключения» к тем, кого больше нет. Подгонять нечего — тот же совет."""
    aliases = {model.alias for model in config.models}
    participants = [alias for alias in council.participants if alias in aliases]
    wanted = max(MIN_PARTICIPANTS, len(council.participants))
    for alias in config.default_participants:
        if len(participants) >= wanted:
            break
        if alias not in participants:
            participants.append(alias)
    judge = council.judge if council.judge in aliases else config.default_judge
    if council.participants == participants and council.judge == judge:
        return council
    return council.model_copy(update={"participants": participants, "judge": judge})


DEFAULT_CONFIG = config_of()
