"""Совет из .env: два участника и судья, подгонка старых советов, каталоги учётных записей."""

import pytest

from spec_council.agents import AgentRunner
from spec_council.config import Agent, ConfigError, config_of, fitted
from spec_council.models import Council, CouncilStatus


def test_without_settings_the_council_is_sol_and_fable_judged_by_fable():
    config = config_of()
    assert config.default_participants == ["sol", "fable"]
    assert config.default_judge == "fable"
    assert [(m.alias, m.short_name, m.display_name, m.cli) for m in config.models] == [
        ("sol", "Sol", "GPT-5.6 Sol", "codex"), ("fable", "Fable", "Claude Fable 5.1", "claude")]
    assert config.agents["sol"] == Agent(provider="codex", model="gpt-5.6-sol")


def test_two_claude_models_judged_by_one_of_them():
    config = config_of("fable=claude/claude-fable-5-1", " opus = claude / claude-opus-5-5 ",
                       "fable")
    assert (config.default_participants, config.default_judge) == (["fable", "opus"], "fable")
    assert [m.display_name for m in config.models] == ["Claude Fable 5.1", "Claude Opus 5.5"]
    assert config.agents["opus"] == Agent(provider="claude", model="claude-opus-5-5")


def test_the_judge_may_be_a_third_model():
    config = config_of("fable=claude/claude-fable-5-1", "opus=claude/claude-opus-5-5",
                       "sol=codex/gpt-5.6-sol")
    assert config.default_participants == ["fable", "opus"]
    assert config.default_judge == "sol"
    assert [m.alias for m in config.models] == ["fable", "opus", "sol"]
    # Тот же, что участник, — тот же, а не третий.
    same = config_of("fable=claude/claude-fable-5-1", "opus=claude/claude-opus-5-5",
                     "opus=claude/claude-opus-5-5")
    assert [m.alias for m in same.models] == ["fable", "opus"]


def test_an_unknown_model_is_shown_as_it_was_named():
    config = config_of("next=claude/claude-next-9", "sol=codex/gpt-5.6-sol")
    assert config.models[0].display_name == "claude-next-9"


@pytest.mark.parametrize(("first", "second", "judge", "problem"), [
    ("fable", "", "", "COUNCIL_PARTICIPANT_1: «fable» — нужно"),
    ("Fable=claude/x", "", "", "латиницей с маленькой"),
    ("astra=gemini/astra-3", "", "", "провайдер gemini, а есть только codex и claude"),
    ("fable=claude/a", "fable=claude/b", "", "имя fable у обоих"),
    ("", "", "opus", "COUNCIL_JUDGE: opus — не участник"),
    ("", "", "sol=claude/claude-opus-5-5", "уже у участника с другой моделью"),
])
def test_a_council_that_cannot_be_assembled_is_refused(first, second, judge, problem):
    with pytest.raises(ConfigError, match=problem):
        config_of(first, second, judge)


def council(participants, judge):
    return Council(id="c1", name="", status=CouncilStatus.brief, brief="",
                   participants=participants, judge=judge, updated_at="2026-10-08T00:00:00Z")


def test_an_old_council_works_on_the_models_of_today():
    """Поменяли модели в .env — совет на прежних не падает на «нет подключения»."""
    config = config_of("fable=claude/claude-fable-5-1", "opus=claude/claude-opus-5-5")
    moved = fitted(council(["sol", "fable"], "sol"), config)
    assert (moved.participants, moved.judge) == (["fable", "opus"], "opus")
    kept = fitted(council(["fable", "opus"], "fable"), config)    # свой судья — среди моделей
    assert kept.judge == "fable"
    same = council(["fable", "opus"], "opus")
    assert fitted(same, config) is same


def test_account_folders_live_in_one_place_unless_a_model_has_its_own(tmp_path, monkeypatch):
    runner = AgentRunner({"opus": Agent(provider="claude", model="claude-opus-5-5"),
                          "sol": Agent(provider="codex", model="gpt-5.6-sol")})
    monkeypatch.setenv("COUNCIL_ACCOUNTS", str(tmp_path / "accounts"))
    monkeypatch.setenv("COUNCIL_SOL_HOME", str(tmp_path / "своя"))
    assert runner.home("opus") == (tmp_path / "accounts" / "opus").resolve()
    assert runner.home("sol") == (tmp_path / "своя").resolve()


def test_a_lineup_of_models_still_configured_is_kept():
    """Выбранный в совете состав — из моделей, что и сейчас есть, — перезапуск не трогает."""
    config = config_of("fable=claude/claude-fable-5-1", "opus=claude/claude-opus-5-5",
                       "sol=codex/gpt-5.6-sol")
    chosen = council(["fable", "sol"], "opus")
    assert fitted(chosen, config) is chosen
    # Ушла одна — на её место встаёт заданная, остальные остаются.
    partly = fitted(council(["astra", "sol"], "sol"), config)
    assert (partly.participants, partly.judge) == (["sol", "fable"], "sol")
