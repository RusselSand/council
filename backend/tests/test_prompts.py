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
    "repository_discovery": {"idea", "fragments", "inventory", "commit_sha",
                             "investigation_requests"},
    "repository_judge": {"idea", "fragments", "inventory", "commit_sha", "discovery_results",
                         "previous_findings"},
    "design_discovery": {"idea", "fragments", "figma_source", "investigation_requests"},
    "design_judge": {"idea", "fragments", "figma_source", "discovery_results",
                     "previous_findings"},
    "question_discovery": {"idea", "fragments", "repository", "design"},
    "question_judge": {"idea", "fragments", "question_candidates", "repository", "design"},
    "proposal_discovery": {"idea", "question", "existing_proposals", "constraints_and_risks",
                           "accepted_decisions", "repository", "design"},
    "proposal_judge": {"idea", "question", "existing_proposals", "constraints_and_risks",
                       "accepted_adrs", "proposal_candidates", "repository", "design"},
    "decision_analysis": {"idea", "question", "proposals", "user_selection",
                          "constraints_and_risks", "related_questions", "accepted_decisions",
                          "repository", "design"},
    "decision_judge": {"idea", "question", "proposals", "user_selection",
                       "constraints_and_risks", "related_questions", "accepted_adrs",
                       "decision_analyses", "repository", "design"},
    "outcome_discovery": {"idea", "questions_and_proposals", "accepted_adrs",
                          "constraints_and_risks", "repository", "design"},
    "outcome_judge": {"idea", "questions_and_proposals", "accepted_adrs", "constraints_and_risks",
                      "outcome_candidates", "repository", "design"},
    "issue_discovery": {"idea", "outcomes", "accepted_adrs", "constraints_and_risks",
                        "repository_context", "design"},
    "issue_judge": {"idea", "outcomes", "accepted_adrs", "constraints_and_risks",
                    "repository_context", "design", "issue_candidates"},
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


@pytest.mark.parametrize("name", [name for name, given in GIVEN.items() if "repository" in given])
def test_every_step_after_the_scan_gets_the_repository_map(name):
    """Карта репозитория передаётся дальше: каждый следующий шаг её видит."""
    values = {key: f"<{key}>" for key in GIVEN[name]}
    assert "<repository>" in render(name, **values)


@pytest.mark.parametrize("name", [name for name, given in GIVEN.items() if "design" in given])
def test_every_step_after_the_design_step_gets_the_design(name):
    """Описание макета передаётся дальше: каждый следующий шаг его видит."""
    values = {key: f"<{key}>" for key in GIVEN[name]}
    assert "<design>" in render(name, **values)
