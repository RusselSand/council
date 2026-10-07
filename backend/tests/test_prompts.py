"""Шаблоны промптов и то, что в них подставляет код."""

import pytest

from spec_council import prompts
from spec_council.prompts import PromptError, render

# Что подставляет конвейер в каждый шаблон (pipeline.py). Шаблон, который ждёт другое,
# упадёт на первой же нарезке, поэтому проверяем здесь.
GIVEN = {
    "slice": {"input"},
    "slice_judge": {"input", "options"},
    "label": {"input", "fragments"},
    "label_judge": {"input", "fragments", "label_options"},
    "structure": {"input", "fragments"},
    "structure_judge": {"input", "fragments", "structure_options"},
    "idea_discovery": {"group"},
    "idea_judge": {"group", "idea_options"},
    "question_discovery": {"idea", "fragments"},
    "question_judge": {"idea", "fragments", "question_candidates"},
}


@pytest.mark.parametrize("name", GIVEN)
def test_every_prompt_renders_with_what_the_pipeline_gives(name):
    values = {key: f"<{key}>" for key in GIVEN[name]}
    text = render(name, **values)
    assert "{{" not in text
    assert any(f"<{key}>" in text for key in values)


def test_substitution_is_one_pass():
    """Текст человека с «{{fragments}}» так и остаётся текстом."""
    text = render("label", input="x", fragments="см. {{fragments}} и {{input}}")
    assert "см. {{fragments}} и {{input}}" in text


def test_empty_prompt_is_reported(tmp_path, monkeypatch):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "slice.md").write_text("  \n", encoding="utf-8")
    monkeypatch.setattr(prompts, "files", lambda _: tmp_path)
    with pytest.raises(PromptError, match="slice.md пуст"):
        render("slice", input="x")


def test_placeholder_the_code_does_not_give_is_reported(tmp_path, monkeypatch):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "slice.md").write_text("{{input}} {{context}}", encoding="utf-8")
    monkeypatch.setattr(prompts, "files", lambda _: tmp_path)
    with pytest.raises(PromptError, match="context"):
        render("slice", input="x")
