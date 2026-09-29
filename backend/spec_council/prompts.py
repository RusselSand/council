"""Промпты моделей: шаблоны prompts/<имя>.md с подстановками вида {{input}}.

Текст правится в .md, код только подставляет данные. Подстановка в один проход: если
в тексте человека встретится «{{fragments}}», это останется текстом.
"""

import re
from importlib.resources import files

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class PromptError(RuntimeError):
    """Шаблон пуст или ждёт подстановку, которой код не даёт."""


def render(name: str, **values: str) -> str:
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
