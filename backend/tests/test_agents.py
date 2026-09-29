"""Подключение моделей: вход подтверждает CLI, а не файлы в каталоге."""

from spec_council.agents import AgentRunner
from spec_council.config import Agent


class Login:
    """Поддельный воркер: check() отвечает по очереди из answers, True — вход есть."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.checks = 0

    def check(self):
        self.checks += 1
        if not self.answers.pop(0):
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
