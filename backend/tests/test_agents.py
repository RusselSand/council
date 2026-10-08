"""Подключение моделей: вход подтверждает CLI, а не файлы в каталоге."""

import subprocess
import threading
from pathlib import Path

import pytest
from agent_workers.base import Profile, Worker
from agent_workers.testing import QUIET, FakeAdapter

from spec_council.agents import AgentRunner
from spec_council.config import Agent
from spec_council.pipeline import ModelFailed


class Login:
    """Поддельный воркер: check() отвечает по очереди из answers, True — вход есть."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.checks = 0

    def check(self):
        self.checks += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if not answer:
            raise RuntimeError("нет входа")


def runner_with(tmp_path, monkeypatch, login, *, folder=True):
    runner = AgentRunner({"sol": Agent(provider="codex", model="gpt-5.6-sol")})
    home = tmp_path / "sol"
    if folder:
        (home / "runs").mkdir(parents=True)   # лоток ходов остаётся и после выхода
    monkeypatch.setattr(runner, "home", lambda alias: home)
    monkeypatch.setattr(runner, "_worker", lambda alias: login)
    return runner


def test_leftover_files_do_not_count_as_a_login(tmp_path, monkeypatch):
    login = Login(False)
    assert runner_with(tmp_path, monkeypatch, login).available("sol") is False
    assert login.checks == 1


def test_answer_is_remembered_and_fresh_asks_again(tmp_path, monkeypatch):
    login = Login(True, False)
    runner = runner_with(tmp_path, monkeypatch, login)
    assert runner.available("sol") is True
    assert runner.available("sol") is True and login.checks == 1          # из памяти
    assert runner.available("sol", fresh=True) is False and login.checks == 2


def test_no_folder_means_no_login_without_asking_the_cli(tmp_path, monkeypatch):
    login = Login()
    assert runner_with(tmp_path, monkeypatch, login, folder=False).available("sol") is False
    assert login.checks == 0


def test_model_without_a_provider_is_never_available(tmp_path):
    runner = AgentRunner({"sol": Agent(provider="codex", model="gpt-5.6-sol")})
    assert runner.availability(["astra"]) == {"astra": False}


def test_hung_cli_is_not_logged_in_and_not_a_500(tmp_path, monkeypatch):
    login = Login(subprocess.TimeoutExpired(["claude", "auth", "status"], 60))
    assert runner_with(tmp_path, monkeypatch, login).available("sol") is False


def test_pool_comes_back_after_a_shutdown():
    from spec_council import agents
    agents.shutdown()
    assert agents.STOP.is_set()
    ran = threading.Event()
    agents.launch(ran.set)          # новый жизненный цикл: новый пул, STOP снят
    assert ran.wait(5)
    assert not agents.STOP.is_set()
    agents.shutdown()


def test_identity_names_provider_and_model():
    runner = AgentRunner({"sol": Agent(provider="codex", model="gpt-5.6-sol")})
    assert runner.identity("sol") == "codex/gpt-5.6-sol"


def test_jobs_still_queued_at_shutdown_run_against_stop_instead_of_vanishing():
    from spec_council import agents
    gate = threading.Event()
    seen = []

    def job():
        gate.wait(5)
        seen.append(agents.STOP.is_set())

    for _ in range(6):                  # больше, чем потоков в пуле: двое ждут в очереди
        agents.launch(job)
    threading.Timer(0.2, gate.set).start()
    agents.shutdown()
    assert seen == [True] * 6


def test_a_workspace_reaches_the_model_through_agent_workers(tmp_path, monkeypatch):
    """Каталог для чтения доходит до провайдера проверенным — это умеет agent-workers ≥ 0.2.0;
    прежний молча его выбрасывал бы, и скан шёл бы вслепую."""
    # STOP мог поднять другой тест (остановка пула) — у этого хода своя, опущенная.
    monkeypatch.setattr("spec_council.agents.STOP", threading.Event())
    adapter = FakeAdapter(tmp_path)
    worker = Worker(adapter, Profile("sol", tmp_path / "home"), tmp_path / "runs", QUIET)
    runner = AgentRunner({"sol": Agent(provider="codex", model="gpt-5.6-sol")})
    monkeypatch.setattr(runner, "_worker", lambda alias: worker)
    repo = tmp_path / "repo"
    repo.mkdir()
    assert runner.ask("sol", "привет", "k1", workspace=Path(f"{repo}/../repo")) == "привет"
    assert adapter.asked[-1]["workspace"] == str(repo.resolve())
    with pytest.raises(ModelFailed, match="workspace"):
        runner.ask("sol", "привет", "k2", workspace=tmp_path / "нет")
