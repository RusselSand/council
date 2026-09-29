"""Запуск моделей совета через agent-workers: одна модель — одно подключение к CLI.

Каталог учётной записи модели — .accounts/<alias> рядом с .env (он в .gitignore), или
COUNCIL_<ALIAS>_HOME в .env или окружении; в докере его задаёт compose. Вход в подписку
делается заранее на хосте, см. README: python -m agent_workers login --home <каталог>.
"""

import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_workers import Settings, build
from agent_workers.base import Busy, LoginRequired, NotRemoved, Worker
from agent_workers.base.process import LaunchError

from .config import Agent
from .pipeline import ModelFailed

# Остановка приложения: идущие ходы сворачиваются, оплаченное остаётся в лотке.
STOP = threading.Event()

# Нарезки идут в своём пуле, а не фоновыми задачами запроса: uvicorn при остановке ждёт
# фоновые задачи и только потом зовёт lifespan, так что STOP не дошёл бы до идущих ходов.
# Пул живёт от запуска до остановки приложения; следующий запуск в том же процессе (тесты,
# второе приложение) получает новый пул и снятый STOP.
_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()

# Вход подтверждает сама CLI. Ответ помним недолго, чтобы страница не ждала её каждый раз;
# «нет входа» — совсем недолго: после входа модель должна подключиться почти сразу.
LOGIN_OK_TTL = 60.0
LOGIN_MISSING_TTL = 5.0


def launch(job: Callable[[], object]) -> None:
    global _pool
    with _pool_lock:
        if _pool is None:
            STOP.clear()
            _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="slicing")
        _pool.submit(job)


def shutdown() -> None:
    """Остановка приложения: идущие ходы сворачиваются, пул дожидается их отчёта.
    Ждущие в очереди не отменяются: их совет уже записан «идёт», и отменённая задача так бы
    там и осталась. Они запускаются при поднятом STOP, модели не зовут и отчитываются,
    что остановлены."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
        STOP.set()
    if pool is not None:
        pool.shutdown(wait=True)


def home_key(alias: str) -> str:
    return f"COUNCIL_{alias.upper()}_HOME"


def failure(result: Mapping) -> str:
    """Почему ход не дал ответа — словами для человека."""
    match result["state"]:
        case "limit_reached":
            return "подписка выбрана выше порога, ход не начинался"
        case "in_progress":
            return "этот же ход уже идёт в другом процессе"
        case "aborted":
            return "остановлено до запуска"
        case _:
            reply = result.get("reply")
            detail = result.get("reason") or (reply.diagnostic if reply else None)
            return f"ход оборвался: {detail or 'без объяснения'}"


class AgentRunner:
    """Runner для конвейера. Вызовы одной модели идут по очереди: так одна подписка не
    тратится параллельными ходами из разных советов."""

    def __init__(self, agents: Mapping[str, Agent]) -> None:
        self._agents = agents
        self._settings = Settings.load()
        self._workers: dict[str, Worker] = {}
        self._locks = {alias: threading.Lock() for alias in agents}
        self._entries: dict[str, tuple[str, object]] = {}
        self._checked: dict[str, tuple[bool, float]] = {}

    def identity(self, alias: str) -> str:
        """Что именно отвечает под этим alias: провайдер и модель. Входит в ключ ответа,
        чтобы после смены модели повтор не взял оплаченный ответ прежней."""
        agent = self._agents.get(alias)
        return f"{agent.provider}/{agent.model}" if agent else alias

    def home(self, alias: str) -> Path | None:
        if alias not in self._agents:
            return None
        # Без настройки — .accounts/<alias> рядом с .env, то есть в корне репозитория.
        root = self._settings.path.parent if self._settings.path else Path.cwd()
        return self._settings.path_of(home_key(alias)) or (root / ".accounts" / alias).resolve()

    def available(self, alias: str, *, fresh: bool = False) -> bool:
        """Вход в подписку подтверждает сама CLI (claude auth status, codex login status).
        Файлы в каталоге ничего не значат: лоток ходов лежит там же и после выхода.
        fresh — спросить заново, а не из памяти: перед платным запуском."""
        home = self.home(alias)
        if home is None or not home.is_dir():
            return False
        known = self._checked.get(alias)
        if known and not fresh:
            ok, at = known
            if time.monotonic() - at < (LOGIN_OK_TTL if ok else LOGIN_MISSING_TTL):
                return ok
        try:
            self._worker(alias).check()
            ok = True
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
            ok = False  # нет входа, CLI не запускается или зависла (TimeoutExpired)
        self._checked[alias] = (ok, time.monotonic())
        return ok

    def availability(self, aliases: Iterable[str], *, fresh: bool = False) -> dict[str, bool]:
        """Несколько моделей разом: проверки CLI идут параллельно."""
        unique = list(dict.fromkeys(aliases))
        with ThreadPoolExecutor(max_workers=max(len(unique), 1)) as pool:
            answers = pool.map(lambda alias: self.available(alias, fresh=fresh), unique)
            return dict(zip(unique, answers, strict=True))

    def ask(self, model: str, prompt: str, key: str) -> str:
        # Вход проверяет сам run (ensure_login): нет его — LoginRequired ниже.
        with self._locks[model]:
            try:
                result = self._worker(model).run({"user": prompt}, key=key,
                                                  stop=STOP.is_set, ensure_login=True)
            except LoginRequired as exc:
                login = f"python -m agent_workers login с AGENT_HOME={self.home(model)}"
                raise ModelFailed(f"нет входа в подписку ({exc}): войдите: {login}") from exc
            except LaunchError as exc:
                raise ModelFailed(f"CLI не запускается: {exc}") from exc
            except (OSError, ValueError) as exc:
                raise ModelFailed(str(exc)) from exc
        if result["state"] not in ("answered", "resumed"):
            raise ModelFailed(failure(result))
        self._entries[key] = (model, result["entry"])
        return result["reply"].text

    def forget(self, keys: Iterable[str]) -> None:
        for key in keys:
            model, entry = self._entries.pop(key, (None, None))
            if model is None:
                continue
            try:
                self._worker(model).collect(entry)
            except (Busy, NotRemoved, OSError):
                pass  # не убралось — останется в лотке, python -m agent_workers pending покажет

    def _worker(self, alias: str) -> Worker:
        if alias not in self._workers:
            agent, home = self._agents[alias], self.home(alias)
            settings = self._settings.override(provider=agent.provider, model=agent.model,
                                               home=str(home), runs=str(home / "runs"))
            self._workers[alias] = build(settings)
        return self._workers[alias]
