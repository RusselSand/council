"""Промпты моделей: шаблоны prompts/<имя>.md с подстановками вида {{input}}.

Текст правится в .md, код только подставляет данные. Подстановка в один проход: если
в тексте человека встретится «{{fragments}}», это останется текстом.

Промпты — на английском: инструкции так короче в токенах. Всё, что модель пишет для человека,
— на языке работы совета, {{language}}: его подставляет сам render (COUNCIL_LANGUAGE, по
умолчанию русский).
"""

import re
from functools import cache
from importlib.resources import files

from agent_workers import Settings

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
LANGUAGE = "Russian"


@cache
def language() -> str:
    """Язык работы совета: COUNCIL_LANGUAGE из окружения или .env — как его поймёт модель
    («Russian», «English», «русский»). Читается один раз: поменяли — перезапустите сервер."""
    return Settings.load().get("COUNCIL_LANGUAGE").strip() or LANGUAGE


class PromptError(RuntimeError):
    """Шаблон пуст или ждёт подстановку, которой код не даёт."""


def render(name: str, **values: str) -> str:
    values.setdefault("language", language())
    template = (files(__package__) / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    if not template.strip():
        raise PromptError(f"Промпт {name}.md пуст")
    unknown = sorted(set(PLACEHOLDER.findall(template)) - values.keys())
    if unknown:
        given = ", ".join(f"{{{{{key}}}}}" for key in sorted(values))
        raise PromptError(
            f"В {name}.md есть {', '.join(unknown)}, а код подставляет только {given}"
        )
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
