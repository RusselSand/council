"""Репозиторий потока: inventory рабочей копии и разбор ответов участников и судьи.

Inventory — обычный список файлов, его даёт git при запуске скана: отслеживаемые (и в
подмодулях) и новые, не игнорируемые, и только обычные файлы, что на диске есть. Git зовётся
только на чтение: каталог может быть смонтирован read-only, а владелец — не тот, кто запускает
(safe.directory). Корень рабочей копии — внутри каталога репозиториев. Модели читают не саму
рабочую копию, а её снимок — только файлы inventory, без .git и игнорируемого: он не меняется
во время скана, а его отпечаток ключует оплаченные ответы.

Факт verified держится на evidence, и evidence — на файлах, которые в репозитории есть: путь
не из inventory отбрасывается, verified без единого подтверждения становится inferred. Ссылки
на факты — только на свои; чужой номер просто отбрасывается. Модели описывают, как система
устроена сейчас: это вход для следующих шагов, а не решения.
"""

import hashlib
import itertools
import json
import os
import re
import stat
import subprocess
import tempfile
import threading
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import BinaryIO, NamedTuple

from .ideas import reason_of
from .models import (
    CoverageArea,
    Evidence,
    FlowStep,
    FollowUp,
    RepositoryFinding,
    RepositoryFlow,
    RepositoryMap,
    RepositoryUnknown,
)
from .slicing import BadAnswer

# Больше файлов в промпт не кладём: модели всё равно ищут по репозиторию сами.
INVENTORY_MAX = 5000
# И не длиннее этого: путь бывает и в 4 КБ, а список идёт в каждый промпт скана.
INVENTORY_CHARS = 150_000
# Нескачанных подмодулей в промптах — не больше стольких и стольких символов.
ABSENT_SHOWN = 20
ABSENT_CHARS = 4000
# Снимок ложится на диск сервера: рабочую копию больше этого не копируем, а отказываем, —
# и по байтам, и по числу файлов (крошечных их бывает миллион: кончились бы память и inode).
SNAPSHOT_MAX = 512 * 2**20
FILES_MAX = 100_000
# Больше вывода от одной команды git не читаем — и путей всех копий вместе не держим.
OUTPUT_MAX = 64 * 2**20
PATHS_MAX = 64 * 2**20
# Вложенных рабочих копий (подмодулей и репозиториев внутри) — у каждой свои вызовы git.
COPIES_MAX = 500
GIT_TIMEOUT = 120
TEXT_MAX = 2000
# Путь в ответе: 4 КБ байтов имени, каждый — до четырёх знаков «\xNN», и символ точки входа.
PATH_CHARS = 20_000
FINDING_ID = re.compile(r"R?(\d+)", re.IGNORECASE)
STATUSES = ("verified", "inferred", "unknown")
COVERAGE = ("covered", "partial", "not_investigated", "not_applicable")


class RepositoryError(ValueError):
    """Каталог не годится для скана: его нет, это не рабочая копия git или git не запускается.
    Текст — для человека; его сохраняют и отдают в JSON, так что байт не из UTF-8 в имени
    (у POSIX — суррогат) в нём виден как \\udcNN, а не ломает запись."""

    def __init__(self, message: str) -> None:
        super().__init__(message.encode("utf-8", "backslashreplace").decode("utf-8"))


@dataclass(frozen=True)
class Inventory:
    root: Path
    # Пусто — коммитов ещё нет: новый репозиторий, только рабочая копия.
    commit_sha: str
    dirty: bool
    files: tuple[str, ...]
    # Состояние рабочей копии при inventory — коммит и git status: снимок сверяется с ним.
    state: bytes = b""
    # Бит исполняемости из индекса — там, где git не верит диску (core.fileMode=false).
    modes: Mapping[str, bool] = field(default_factory=dict)
    # Сколько весят файлы: больше SNAPSHOT_MAX — снимка не будет.
    size: int = 0
    # Сколько файлов коммита вне sparse checkout: их нет ни на диске, ни в снимке.
    outside: int = 0
    # Чего нет в снимке, хоть оно и в рабочей копии: нескачанные подмодули и ссылки (их не
    # копируем — за ссылкой может быть что угодно), с причиной; модели должны это знать.
    omitted: tuple[str, ...] = ()


def git_command(root: Path, *args: str) -> list[str]:
    # --no-optional-locks: status не пытается обновить индекс — каталог может быть read-only.
    # core.fsmonitor — команда из конфига рабочей копии: git status её запускает, не надо.
    return ["git", "--no-pager", "-c", "safe.directory=*", "-c", "core.fsmonitor=false",
            "--no-optional-locks", "-C", str(root), *args]


def git_env(root: Path | None) -> dict[str, str]:
    """Окружение git без команд из конфига рабочей копии: фильтры (clean, smudge, process),
    заданные в ней самой, git status и hash-object запускают — от имени сервера, с его доступом
    к ключам моделей. Их отключаем; заданные сервером (git-lfs) — его, им верим. Через
    GIT_CONFIG_*, а не -c: там «=» в имени фильтра разорвало бы настройку."""
    pairs = []
    for driver in local_filters(root) if root is not None else ():
        pairs += [(f"filter.{driver}.{key}", "") for key in ("clean", "smudge", "process")]
        pairs.append((f"filter.{driver}.required", "false"))
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
    env["GIT_CONFIG_COUNT"] = str(len(pairs))
    for n, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{n}"] = key
        env[f"GIT_CONFIG_VALUE_{n}"] = value
    return env


def local_filters(root: Path) -> set[str]:
    """Фильтры, которые задаёт сама рабочая копия (её .git/config, worktree и их include)."""
    # Не больше OUTPUT_MAX, как и всё от git: .git/config не входит ни в какой предел. Ничего
    # не задано — git config выходит с 1; любая другая ошибка — отказ, а не скан с фильтрами.
    output = git_bytes(root, "config", "-z", "--show-scope", "--get-regexp", r"^filter\.",
                       nothing=1)
    entries = output.split(b"\0")
    drivers = set()
    for scope, entry in zip(entries[::2], entries[1::2], strict=False):
        name = os.fsdecode(entry.split(b"\n", 1)[0])           # «filter.<драйвер>.<ключ>»
        if scope in (b"local", b"worktree") and name.count(".") >= 2:
            drivers.add(name[len("filter."):name.rindex(".")])
    return drivers


def git_bytes(root: Path, *args: str, nothing: int | None = None) -> bytes:
    """Вывод git — кусками и не больше OUTPUT_MAX: больше — RepositoryError, а git
    останавливаем. В рабочей копии с миллионами файлов один список занял бы всю память.
    nothing — код выхода, который значит «ничего не нашлось»: тогда пусто."""
    command = git_command(root, *args)
    # Содержимое файлов — а с ним и фильтры — читают только status и hash-object.
    env = git_env(root) if args[0] in ("status", "hash-object") else git_env(None)
    expired = threading.Event()
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, env=env)
        except OSError as exc:
            raise RepositoryError(f"git не запускается: {exc}") from exc

        def stop() -> None:
            expired.set()
            process.kill()

        timer = threading.Timer(GIT_TIMEOUT, stop)
        timer.start()
        output = bytearray()
        try:
            with process.stdout:
                while chunk := process.stdout.read(1 << 16):
                    output += chunk
                    if len(output) > OUTPUT_MAX:
                        process.kill()
                        break
            code = process.wait()
        finally:
            timer.cancel()
        if len(output) > OUTPUT_MAX:
            raise RepositoryError(f"Рабочая копия слишком велика для скана: список от git "
                                  f"{args[0]} больше {OUTPUT_MAX / 2**20:g} МБ")
        if expired.is_set():
            raise RepositoryError(f"git {args[0]} не уложился в {GIT_TIMEOUT} с")
        if code == nothing:
            return b""
        if code != 0:
            errors.seek(0)
            detail = errors.read(8192).decode("utf-8", errors="replace").strip()
            raise RepositoryError(detail or f"git {args[0]} не удался")
    return bytes(output)


def git(root: Path, *args: str) -> str:
    return git_bytes(root, *args).decode("utf-8", errors="replace")


class Copy(NamedTuple):
    """Рабочая копия — корень или вложенная: каталог, путь от корня с «/» на конце (у корня —
    ""), её отслеживаемые и новые, не игнорируемые файлы; embedded — не подмодуль, а просто
    репозиторий внутри: её коммита в коммите корня нет."""

    folder: Path
    prefix: str
    cached: list[str]
    others: list[str]
    embedded: bool = False
    outside: int = 0
    # Её подмодули, что не скачаны (или подменены ссылкой): их кода в снимке нет.
    absent: tuple[str, ...] = ()


def listed(copies: list[Copy]) -> list[str]:
    """Отслеживаемые и новые, не игнорируемые файлы каждой рабочей копии из copies_of. Во
    вложенные git сам не заходит (--recurse-submodules споткнулся бы о подмодуль-ссылку, а
    --others его и вовсе не умеет): обходим их мы, без ссылок и кругов. Новые файлы внешней
    копии, что лежат во вложенной, — по правилам вложенной: её исключений внешняя не знает."""
    found: list[str] = []
    for copy in copies:
        inner = tuple(other.prefix.removeprefix(copy.prefix) for other in copies
                      if other.prefix != copy.prefix and other.prefix.startswith(copy.prefix))
        found += [copy.prefix + name for name in copy.cached]
        found += [copy.prefix + name for name in copy.others if not name.startswith(inner)]
    return found


def copies_of(root: Path) -> list[Copy]:
    """Корень и вложенные рабочие копии — checked-out подмодули и просто репозитории внутри,
    не подмодули, — и вложенные в них. Подменённую ссылкой и уже пройденную не обходим: ссылка
    назад на родителя водила бы по кругу, а наружу — за пределы рабочей копии."""
    top = os.path.realpath(root)
    seen = {top}
    found: list[Copy] = []
    counted = chars = 0
    queue = [(root, "", False)]
    while queue:
        folder, prefix, embedded = queue.pop(0)
        index = index_of(folder)
        cached = [name for *_, name in index]
        others = names(git_bytes(folder, "ls-files", "-z", "--others", "--exclude-standard"))
        counted += len(cached) + len(others)
        # Пути — как их потом соберёт listed(): с путём копии от корня у каждого.
        chars += (len(cached) + len(others)) * len(prefix)
        chars += sum(map(len, cached)) + sum(map(len, others))
        within(counted, chars, len(seen))   # пока обходим: подмодулей бывает и тысяча
        # Подмодуль записан в коммите своего родителя (recorded); репозиторий внутри — нигде.
        links = [(name, embedded, True) for _, mode, _, name in index if mode == b"160000"]
        links += [(name, True, False) for name in inner_copies(folder, cached, others)]
        absent: list[str] = []
        for link, inside, recorded in links:
            path = folder / link
            if not checked_out(path, top):
                # Подменённую ссылкой покажет links_of; остальное — тут, с причиной.
                if recorded and not is_link(path):
                    absent.append(f"{shown(prefix + link)}/ — подмодуль не скачан")
                elif not is_link(path):
                    absent.append(f"{shown(prefix + link)}/ — репозиторий внутри не прочитать: "
                                  "его .git не годится или уводит в другой каталог")
                continue
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                within(counted, chars, len(seen))
                queue.append((path, f"{prefix}{link}/", inside))
        found.append(Copy(folder, prefix, cached, others, embedded, outside_of(folder, index),
                          tuple(absent)))
    return found


def within(files: int, chars: int, copies: int) -> None:
    """Пределы обхода всех копий вместе — каждая команда git и так в своём, а вместе их много:
    файлов, длины их путей и самих копий (у каждой свои вызовы git)."""
    if files > FILES_MAX:
        raise too_many()
    if chars > PATHS_MAX:
        raise RepositoryError(f"Рабочая копия слишком велика для скана: пути её файлов вместе "
                              f"длиннее {PATHS_MAX / 2**20:g} МБ")
    if copies > COPIES_MAX:
        raise RepositoryError(f"Рабочая копия слишком велика для скана: вложенных рабочих копий "
                              f"больше {COPIES_MAX}")


def checked_out(path: Path, top: str) -> bool:
    """Вложенная рабочая копия на месте: каталог, а не ссылка, внутри корня и со своим .git."""
    try:
        if not stat.S_ISDIR(path.lstat().st_mode):
            return False
    except OSError:
        return False
    real = os.path.realpath(path)
    return (real == os.path.abspath(path) and Path(real).is_relative_to(top)
            and (path / ".git").exists() and own_top(path))


def own_top(path: Path) -> bool:
    """Корень этой копии по git — сама она: core.worktree или .git-файл не уводят git в чужой
    каталог под её именем."""
    try:
        return os.path.normcase(top_of(path)) == os.path.normcase(os.path.realpath(path))
    except RepositoryError:
        return False


def outside_of(folder: Path, index: list[tuple[bytes, bytes, str, str]]) -> int:
    """skip-worktree, а файла нет — он вне sparse checkout: в снимок не ляжет."""
    return sum(1 for tag, mode, _, name in index
               if tag.upper() == b"S" and mode in (b"100644", b"100755")
               and not plain(folder, name))


def inner_copies(folder: Path, *listings: list[str]) -> list[str]:
    """Репозитории внутри, не подмодули: каталоги с .git, где лежат файлы из списков. --others
    показывает такой каталог одной строкой («tools/gen/»), а если в нём есть и отслеживаемые
    файлы внешней копии — поштучно. Игнорируемые каталоги в списки не попадают — в них не ищем."""
    return [prefix for prefix, is_folder in prefixes(itertools.chain(*listings))
            if is_folder and os.path.lexists(folder / prefix / ".git")]


def prefixes(names: Iterable[str]) -> Iterator[tuple[str, bool]]:
    """Пути от корня к именам — и каталоги по дороге, и сами имена — каждый по одному разу, по
    порядку: (путь, каталог ли). Имена — по порядку, и у соседних общее начало уже пройдено:
    все имена под одним каталогом в нём идут подряд. Строк «каталог по дороге» у глубокого пути
    квадратично много — их общая длина не больше PATHS_MAX, иначе RepositoryError."""
    previous: list[str] = []
    used = 0
    for name in sorted(set(names)):
        parts = name.removesuffix("/").split("/")
        whole = name.endswith("/")                   # «tools/gen/» — сам каталог тоже
        same = 0
        while same < min(len(parts), len(previous)) and parts[same] == previous[same]:
            same += 1
        for depth in range(same + 1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            used += len(prefix)
            if used > PATHS_MAX:
                raise RepositoryError(f"Рабочая копия слишком велика для скана: пути к её файлам "
                                      f"вместе длиннее {PATHS_MAX / 2**20:g} МБ")
            yield prefix, depth < len(parts) or whole
        previous = parts


def names(output: bytes) -> list[str]:
    """Пути из вывода с -z: через NUL, без кавычек и восьмеричных escape-кодов. Байты — как в
    файловой системе (os.fsdecode): имя не в UTF-8 остаётся тем же файлом, а не «�»."""
    return [os.fsdecode(name) for name in output.split(b"\0") if name]


def located(text: str, base: Path | None) -> Path:
    """Каталог рабочей копии по тексту человека. С каталогом репозиториев путь — от него и
    только внутри него; без него — абсолютный."""
    if not text.strip():           # пробелы по краям — часть имени: « repo» — не «repo»
        raise RepositoryError("Укажите путь к рабочей копии репозитория")
    if "\0" in text:              # в пути его не бывает, а resolve() на нём падает
        raise RepositoryError("В пути не может быть символа NUL")
    path = Path(text)
    if base is not None:
        path = (base / path).resolve()
        if not path.is_relative_to(base.resolve()):
            raise RepositoryError(f"Путь вне каталога репозиториев {base}")
    elif not path.is_absolute():
        raise RepositoryError(
            "Нужен абсолютный путь: каталог репозиториев (COUNCIL_REPOS) не задан")
    if not path.is_dir():
        raise RepositoryError(f"Каталога нет: {path}")
    return path.resolve()


def working_copy(text: str, base: Path | None) -> Inventory:
    """Рабочая копия по тексту человека — целиком внутри каталога репозиториев: корень git
    может оказаться выше выбранной папки. Корень — одним дешёвым вызовом git, до обхода: чужую
    рабочую копию не читаем даже ради отказа."""
    root = top_of(located(text, base))
    if base is not None and not root.is_relative_to(base.resolve()):
        raise RepositoryError(f"Корень рабочей копии {root} вне каталога репозиториев {base}")
    found = inventory(root)
    fits(found)
    return found


def top_of(path: Path) -> Path:
    """Корень по git — байтами файловой системы: «�» вместо байта дал бы другой каталог."""
    output = git_bytes(path, "rev-parse", "--show-toplevel").removesuffix(b"\n")
    return Path(os.fsdecode(output.removesuffix(b"\r"))).resolve()


def fits(found: Inventory) -> None:
    """Снимок этой рабочей копии ляжет на диск сервера — или RepositoryError: больше не
    копируем."""
    if len(found.files) > FILES_MAX:
        raise too_many()
    if found.size > SNAPSHOT_MAX:
        raise too_big()


def too_many() -> RepositoryError:
    return RepositoryError(f"В рабочей копии слишком много файлов для снимка: больше {FILES_MAX}")


def too_big() -> RepositoryError:
    return RepositoryError(
        f"Рабочая копия слишком велика для снимка: файлы весят больше "
        f"{SNAPSHOT_MAX / 2**20:g} МБ — крупные артефакты держите вне git, в игнорируемых")


def head(root: Path) -> str:
    """Коммит рабочей копии; пусто — коммитов ещё нет, а файлы есть."""
    try:
        return git(root, "rev-parse", "--verify", "-q", "HEAD").strip()
    except RepositoryError:
        return ""


def levels(copies: list[Copy]) -> list[tuple[str, str, bytes]]:
    """Каждая рабочая копия из copies_of: (путь от корня, коммит, git status с каждым новым
    файлом). Во вложенные git status сам не заходит: обходим их мы, без ссылок и кругов, — и у
    каждой свой статус: у грязного подмодуля общая пометка в родителе не меняется, что бы в
    нём ни правили."""
    return [(copy.prefix, head(copy.folder), changes_of(copy.folder)) for copy in copies]


def state_of(found: list[tuple[str, str, bytes]]) -> bytes:
    """Состояние рабочей копии одной строкой байтов: поменялось — её правили."""
    return b"\0\0".join(os.fsencode(prefix) + b"\0" + sha.encode() + b"\0" + status
                         for prefix, sha, status in found)


def changes_of(root: Path) -> bytes:
    """git status с каждым новым файлом — и правки, которых он не покажет."""
    hidden = hidden_of(root)
    return status_of(root) + (b"\0\0hidden\0" + hidden if hidden else b"")


def hidden_of(root: Path) -> bytes:
    """Правки в файлах с assume-unchanged или skip-worktree: их содержимое git status не
    сверяет, а модели читают уже не коммит. Такие файлы на диске сверяем сами — с индексом
    (hash-object — с теми же фильтрами, что и git add), и бит исполняемости тоже, если git ему
    на диске верит: снимок его сохранит."""
    flagged: dict[str, str] = {}
    changed: list[str] = []
    modes = file_mode(root) and os.name != "nt"
    symlinks = config_bool(root, "core.symlinks")
    for tag, mode, sha, name in index_of(root):
        if not (tag.islower() or tag == b"S"):
            continue
        if mode == b"120000":
            if link_changed(root, name, sha, symlinks=symlinks, sparse=tag.upper() == b"S"):
                changed.append(name)
            continue
        if mode not in (b"100644", b"100755"):
            continue
        if plain(root, name):
            flagged[name] = sha
            if modes and executable_on_disk(root / name) != (mode == b"100755"):
                changed.append(name)
        elif tag.upper() != b"S":
            # assume-unchanged, а файла нет или он уже не файл — правка; у skip-worktree это
            # обычный sparse checkout.
            changed.append(name)
    for chunk in batches(list(flagged)):
        shas = git(root, "hash-object", "--", *chunk).split()
        changed += [name for name, sha in zip(chunk, shas, strict=True) if sha != flagged[name]]
    return b"\0".join(os.fsencode(name) for name in changed)


def batches(names: list[str], limit: int = 8000) -> Iterator[list[str]]:
    """Имена пачками по длине: командная строка не бесконечна (на Windows — около 32 тысяч
    символов), а имя — до 4 КБ, так что по числу пачку не отмерить."""
    batch: list[str] = []
    used = 0
    for name in names:
        size = len(os.fsencode(name)) + 3            # с пробелом и кавычками
        if batch and used + size > limit:
            yield batch
            batch, used = [], 0
        batch.append(name)
        used += size
    if batch:
        yield batch


def link_changed(root: Path, name: str, sha: str, *, symlinks: bool, sparse: bool) -> bool:
    """Ссылка с флагом против её версии в индексе (блоб — текст ссылки). Без поддержки ссылок
    (core.symlinks=false, как на Windows) git кладёт её файлом с этим текстом. Нет на диске:
    у assume-unchanged — правка, у skip-worktree — sparse checkout."""
    path = root / name
    if os.path.islink(path):
        data = os.fsencode(os.readlink(path))
    elif not symlinks and plain(root, name):
        with path.open("rb") as file:
            data = file.read(1 << 16)
    else:
        return os.path.lexists(path) or not sparse
    return blob_id(data, len(sha)) != sha


def blob_id(data: bytes, length: int) -> str:
    """Имя блоба, как его считает git: sha1 или, в репозитории на sha256, — sha256."""
    algorithm = hashlib.sha1 if length == 40 else hashlib.sha256
    return algorithm(b"blob %d\0" % len(data) + data).hexdigest()


def executable_on_disk(path: Path) -> bool:
    try:
        return bool(path.lstat().st_mode & 0o111)
    except OSError:
        return False


def index_of(root: Path) -> list[tuple[bytes, bytes, str, str]]:
    """Записи индекса: (тег ls-files -v, режим, sha, имя) — из «h 100644 <sha> 0<TAB><имя>»."""
    found = []
    for entry in git_bytes(root, "ls-files", "-z", "-v", "--stage").split(b"\0"):
        if entry:
            tag, _, rest = entry.partition(b" ")
            meta, _, raw = rest.partition(b"\t")
            mode, sha = meta.split(b" ")[:2]
            found.append((tag, mode, sha.decode(), os.fsdecode(raw)))
    return found


def modes_of(copies: list[Copy]) -> dict[str, bool]:
    """Бит исполняемости, которому git верит больше, чем диску: при core.fileMode=false — из
    индекса (на диске он бывает и у всех файлов сразу, как в bind mount из Windows). Снимок
    берёт его оттуда же, откуда взял бы коммит: иначе модели видели бы не показанный коммит, а
    копия числилась бы без правок."""
    modes: dict[str, bool] = {}
    for copy in copies:
        if not file_mode(copy.folder):
            modes.update({copy.prefix + name: mode == b"100755"
                          for _, mode, _, name in index_of(copy.folder)
                          if mode in (b"100644", b"100755")})
    return modes


def file_mode(root: Path) -> bool:
    """core.fileMode: false — бит исполняемости на диске git не сверяет."""
    return config_bool(root, "core.fileMode")


def config_bool(root: Path, key: str) -> bool:
    """Булева настройка git; не задана — true (так у core.fileMode и core.symlinks)."""
    try:
        return git(root, "config", "--type=bool", "--get", key).strip() != "false"
    except RepositoryError:
        return True


def status_of(root: Path) -> bytes:
    """--ignore-submodules=dirty: подмодуль не на записанном в родителе коммите — это правка
    (снимок уже не показанный коммит), а что внутри него, git сам не смотрит: это его статус."""
    return git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                     "--ignore-submodules=dirty")


def inventory(path: Path) -> Inventory:
    """Корень рабочей копии, её коммит, есть ли незакоммиченные правки, и список файлов — тех,
    что на диске есть, это обычные файлы и лежат в рабочей копии (удалённый, но отслеживаемый,
    вне sparse checkout, ссылка и файл за каталогом-ссылкой — не её файлы)."""
    root = top_of(path)
    copies = copies_of(root)
    files = present(root, copies)
    size = sum(stamp[0] for stamp in (stamp_of(root / name) for name in files) if stamp)
    if size > SNAPSHOT_MAX:
        raise too_big()        # до git status и hash-object: они читают файлы с флагами целиком
    found = levels(copies)
    # Правки — и вложенный репозиторий, не подмодуль: его кода в коммите корня нет.
    dirty = any(status for _, _, status in found) or any(copy.embedded for copy in copies)
    return Inventory(root, found[0][1], dirty, files,
                     state_of(found), modes_of(copies), size,
                     sum(copy.outside for copy in copies), omitted_of(root, copies))


def omitted_of(root: Path, copies: list[Copy]) -> tuple[str, ...]:
    """Чего нет в снимке, хоть оно и в рабочей копии, — с причиной."""
    return (*(entry for copy in copies for entry in copy.absent), *links_of(root, copies))


def links_of(root: Path, copies: list[Copy]) -> list[str]:
    """Ссылки рабочей копии — путь и куда ведёт (сам текст ссылки, по ней не ходим). И ссылка
    на каталог по дороге к файлу: файлов за ней в снимке нет, даже если git её самой не
    показывает (каталог игнорируется). Каждая — один раз, первая по пути."""
    found: list[str] = []
    behind = None                                    # ссылка, за которой уже не смотрим
    for prefix, _ in prefixes(listed(copies)):
        if behind is not None and prefix.startswith(behind):
            continue
        if is_link(root / prefix):
            found.append(f"{shown(prefix)} → {link_text(root / prefix)} — ссылка, в снимок не "
                         "копируется")
            behind = prefix + "/"
    return found


def is_link(path: Path) -> bool:
    return os.path.islink(path) or os.path.isjunction(path)


def link_text(path: Path) -> str:
    try:
        return shown(os.readlink(path))
    except OSError:
        return "?"


def present(root: Path, copies: list[Copy]) -> tuple[str, ...]:
    """Файлы рабочей копии: из списков git — те, что на диске есть и это обычные файлы."""
    listing = set(listed(copies))
    if len(listing) > FILES_MAX:
        raise too_many()                  # до lstat каждого: их может быть миллион
    return tuple(sorted(name for name in listing if plain(root, name)))


def plain(root: Path, name: str) -> bool:
    """Обычный файл, и путь к нему — без ссылок: ни он сам, ни каталоги по дороге. За ссылкой
    может быть что угодно, вплоть до /dev/zero или чужих ключей."""
    path = root / name
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return False
    except OSError:
        return False
    return unlinked(root, name)


def unlinked(root: Path, name: str) -> bool:
    """От корня до файла — ни одной ссылки или junction: путь без них тот же, что и с ними.
    Ссылка и внутрь рабочей копии не годится: за ней может быть игнорируемое, вплоть до .env."""
    real = os.path.realpath(root / name)
    expected = os.path.join(os.path.realpath(root), *name.split("/"))
    return os.path.normcase(real) == os.path.normcase(expected)


def snapshot(found: Inventory, into: Path) -> tuple[str, frozenset[str]]:
    """Снимок рабочей копии, который читают модели: только файлы inventory — без .git и
    игнорируемого (там бывают .env и ключи) — и только обычные файлы внутри неё. Пока идёт
    скан, рабочую копию могут править, а снимок неподвижен: все участники и все проходы читают
    один и тот же код. Правили, пока он делался, — снимок был бы смесью старого и нового:
    RepositoryError. Отпечаток — по содержимому снимка и битам исполняемости: им ключуются
    оплаченные ответы, и тот же код в другой копии — тот же ключ. Файл inventory не прочитать —
    тоже RepositoryError: промпт его называет, и карта без него вышла бы «полной», хотя его никто
    не читал. Вернёт отпечаток и какие файлы в снимок легли."""
    fits(found)
    digest = hashlib.sha256()
    taken: dict[str, tuple[int, int]] = {}
    missed: list[str] = []
    written = 0
    for name in found.files:
        copied = copied_file(found.root, name, into / name, executable=found.modes.get(name),
                             limit=SNAPSHOT_MAX - written)
        if copied is None:
            missed.append(name)
            continue
        part, stamp = copied
        digest.update(os.fsencode(name) + b"\0" + part + b"\0")
        taken[name] = stamp
        written += (into / name).stat().st_size
    copies = copies_of(found.root)
    # Состояние читается после списка файлов: появился файл между ними — его в снимке нет.
    appeared = set(present(found.root, copies)) - set(found.files)
    if state_of(levels(copies)) != found.state or appeared or any(
            stamp_of(found.root / name) != stamp for name, stamp in taken.items()):
        raise RepositoryError("Рабочая копия менялась, пока делался её снимок, — запустите скан "
                              "снова, когда правки закончатся")
    if missed:
        told = ", ".join(map(shown, missed[:5]))
        told += f" и ещё {len(missed) - 5}" if len(missed) > 5 else ""
        raise RepositoryError(f"Не прочитать файлы рабочей копии: {told} — без них карта вышла "
                              "бы неполной; дайте серверу права на чтение и запустите скан снова")
    return digest.hexdigest(), frozenset(taken)


def stamp_of(path: Path) -> tuple[int, int] | None:
    """Размер и время правки: поменялись после копирования — файл правили."""
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_size, info.st_mtime_ns


def open_inside(root: Path, name: str) -> int:
    """Файл рабочей копии, открытый так, чтобы ни один каталог по дороге не был ссылкой: каждый
    — относительно предыдущего и без перехода по ссылке (O_NOFOLLOW). Где так нельзя (Windows),
    — только если на всём пути нет ни ссылки, ни junction (unlinked). FIFO не ждём: O_NONBLOCK."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_BINARY", 0))
    folder_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
        *folders, file = name.split("/")
        handle = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for folder in folders:
                inner = os.open(folder, folder_flags, dir_fd=handle)
                os.close(handle)
                handle = inner
            return os.open(file, flags, dir_fd=handle)
        finally:
            os.close(handle)
    if not unlinked(root, name):
        raise OSError(f"{name}: путь идёт через ссылку")
    return os.open(os.path.realpath(root / name), flags)


def copied_file(root: Path, name: str, target: Path, *, executable: bool | None = None,
                limit: int | None = None) -> tuple[bytes, tuple[int, int]] | None:
    """Копия одного файла кусками — и хеш его содержимого с битом исполняемости, и его размер
    и время правки на момент копирования. Пропал, не читается, не обычный файл — None.
    executable — бит из индекса, если диску git не верит; limit — сколько ещё влезет в снимок:
    вырос больше — RepositoryError, не дописываем."""
    try:
        handle = open_inside(root, name)
    except OSError:
        return None
    with os.fdopen(handle, "rb") as read:
        info = os.fstat(read.fileno())
        if not stat.S_ISREG(info.st_mode):
            return None
        digest = hashlib.sha256()
        size = 0
        with written(target, name) as write:
            for chunk in iter(lambda: read.read(1 << 16), b""):
                size += len(chunk)
                if limit is not None and size > limit:
                    raise too_big()
                digest.update(chunk)
                write.write(chunk)
    if executable is None:
        executable = bool(info.st_mode & 0o111) and os.name != "nt"
    if executable and os.name != "nt":
        target.chmod(0o755)   # исполняемый — и в снимке: модели видят, что это запускают
    return digest.digest() + (b"x" if executable else b"-"), (info.st_size, info.st_mtime_ns)


@contextmanager
def written(target: Path, name: str) -> Iterator[BinaryIO]:
    """Файл снимка на запись. Путь в снимке длиннее исходного (временный каталог), и предел
    системы может кончиться — это причина отказа, а не внутренняя ошибка."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file = target.open("wb")
    except OSError as exc:
        raise RepositoryError(f"Не записать в снимок {shown(name)}: "
                              f"{exc.strerror or exc}") from exc
    with file:
        yield file


def inventory_prompt(found: Inventory) -> str:
    lines: list[str] = []
    used = 0
    for name in found.files[:INVENTORY_MAX]:
        used += len(shown(name)) + 1
        if used > INVENTORY_CHARS:
            break
        lines.append(shown(name))
    text = "\n".join(lines)
    if len(found.files) > len(lines):
        text += f"\n… и ещё {len(found.files) - len(lines)} файлов: ищите по репозиторию сами"
    if found.outside:
        text += (f"\n… файлов коммита вне sparse checkout: {found.outside} — их нет ни на диске, "
                 "ни в снимке: коммит виден не весь")
    if found.omitted:
        told = capped(found.omitted)
        more = len(found.omitted) - len(told)
        text += f"\n… нет в снимке: {'; '.join(told)}{f'; и ещё {more}' if more else ''}"
    return text


def capped(names: Sequence[str]) -> list[str]:
    """Первые имена — не больше ABSENT_SHOWN и ABSENT_CHARS символов: список идёт в промпты."""
    taken: list[str] = []
    used = 0
    for name in names[:ABSENT_SHOWN]:
        used += len(name) + 2
        if used > ABSENT_CHARS:
            break
        taken.append(name)
    return taken


def shown(name: str) -> str:
    """Имя файла, каким его видят модели и человек: байты не из UTF-8 и управляющие символы
    (перевод строки разбил бы имя на два «файла» списка) — как \\xNN, байтами (как есть их в
    промпт не положить и не сохранить), а сама «\\» — как «\\\\»: иначе байт и те же буквы в
    имени другого файла выглядели бы одинаково. Обратно переводит Context.path_of."""
    if name.isprintable() and "\\" not in name:
        return name
    return "\\\\".join("".join(map(escaped, part.decode("utf-8", "backslashreplace")))
                       for part in os.fsencode(name).split(b"\\"))


def escaped(char: str) -> str:
    if unicodedata.category(char)[0] == "C" or unicodedata.category(char) in ("Zl", "Zp"):
        return "".join(f"\\x{byte:02x}" for byte in char.encode())
    return char


def sha_prompt(found: Inventory) -> str:
    if not found.commit_sha:
        return "нет коммитов: репозиторий новый, есть только рабочая копия"
    return found.commit_sha + (" (в рабочей копии есть незакоммиченные изменения: читайте её)"
                               if found.dirty else "")


# --- разбор


@dataclass(frozen=True)
class Context:
    """На что могут ссылаться находки: файлы репозитория. roots — где лежит снимок: модель
    может назвать файл и полным путём в нём."""

    files: frozenset[str]
    roots: tuple[Path, ...] = field(default_factory=tuple)

    def path_of(self, value: object) -> str:
        """Путь файла, как его назвала модель, — относительный, как в inventory. Сначала как
        есть: в POSIX «\\» — буква имени; «/» вместо «\\» — запасной ход для ссылок в духе
        Windows. Имя, каким его показали моделям (shown), — прежде всего: модель берёт его
        из списка. Путь — как есть, не прозой: не режем и пробелы не схлопываем."""
        text = path_text(value)
        variants = (text, text.replace("\\", "/"), text.strip(), text.strip().replace("\\", "/"))
        named = [self.relative(path) for path in dict.fromkeys(variants)]
        for path in named:
            if path in self.originals:
                return self.originals[path]
            if path in self.files:
                return path
        return named[-1]

    @cached_property
    def originals(self) -> dict[str, str]:
        """Имена файлов по тому, как их показали моделям: у имён не из UTF-8 это разное."""
        return {shown(name): name for name in self.files if shown(name) != name}

    def relative(self, path: str) -> str:
        path = path.removeprefix("./")
        for root in self.roots:
            prefix = root.as_posix().rstrip("/") + "/"
            if path.startswith(prefix):
                return path[len(prefix):]
        return path


def text_of(value: object) -> str:
    return reason_of(value)[:TEXT_MAX]


def path_text(value: object) -> str:
    """Путь из ответа — как есть: в имени бывают и два пробела подряд, и 4 КБ."""
    return value[:PATH_CHARS] if isinstance(value, str) else ""


def strings(value: object) -> list[str]:
    items = value if isinstance(value, list) else []
    return list(dict.fromkeys(text for text in (text_of(item) for item in items) if text))


def finding_id(value: object) -> str | None:
    found = FINDING_ID.fullmatch(value.strip()) if isinstance(value, str) else None
    return f"R{int(found.group(1))}" if found else None


def evidence_of(value: object, context: Context) -> list[Evidence]:
    items = value if isinstance(value, list) else []
    found = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = context.path_of(item.get("path"))
        if path not in context.files:
            continue   # файла в репозитории нет — это не подтверждение
        found.append(Evidence(path=shown(path), lines=text_of(item.get("lines")) or None,
                              symbol=text_of(item.get("symbol")) or None))
    return found


def findings_of(value: object, context: Context) -> list[RepositoryFinding]:
    """Находки со своими номерами. Без номера или с повтором — номер наш и не занятый ни одной
    находкой ответа: иначе ссылки на ту находку достались бы этой."""
    items = given_findings(value)
    taken = {finding_id(item.get("id")) for item in items}
    free = (f"R{n}" for n in itertools.count(1) if f"R{n}" not in taken)
    found: dict[str, RepositoryFinding] = {}
    for item in items:
        name = finding_id(item.get("id"))
        if name is None or name in found:
            name = next(free)
        status = item.get("status") if item.get("status") in STATUSES else "unknown"
        evidence = evidence_of(item.get("evidence"), context)
        if status == "verified" and not evidence:
            status = "inferred"   # verified без подтверждения в репозитории — только вывод
        found[name] = RepositoryFinding(id=name, statement=text_of(item.get("statement")),
                                        status=status, evidence=evidence,
                                        relevance=text_of(item.get("relevance")))
    return list(found.values())


def given_findings(value: object) -> list[dict]:
    items = value if isinstance(value, list) else []
    return [item for item in items if isinstance(item, dict) and text_of(item.get("statement"))]


def linkable(findings: list[RepositoryFinding], value: object) -> set[str]:
    """На какие находки ссылки берём: на те, чей номер дал сам ответ, и одной находке. Номер у
    двух — ссылка на неизвестно какую из них; номер наш — ответ его и не знал."""
    named = Counter(finding_id(item.get("id")) for item in given_findings(value))
    return {finding.id for finding in findings if named[finding.id] == 1}


def ids_in(value: object, known: set[str]) -> list[str]:
    items = value if isinstance(value, list) else []
    found = (finding_id(item) for item in items)
    return list(dict.fromkeys(name for name in found if name in known))


def entry_of(value: object, context: Context) -> str:
    """Точка входа потока — файл репозитория, можно с символом: «api/routes.py:handler». Путь —
    самое длинное начало, которое есть в inventory: в именах бывают и пробелы. Файла нет — точки
    входа нет: следующие шаги поверили бы несуществующему компоненту."""
    text = path_text(value)       # как есть: пробел в начале — тоже имя; обрезает path_of
    ends = [len(text), *sorted({i for i, char in enumerate(text) if char in ": ("}, reverse=True)]
    for end in ends:
        path = context.path_of(text[:end])
        if path in context.files:
            rest = text[end:]
            return shown(path) + (rest[:1] + reason_of(rest[1:]))[:TEXT_MAX]
    return ""


def flows_of(value: object, known: set[str], context: Context) -> list[RepositoryFlow]:
    items = value if isinstance(value, list) else []
    return [RepositoryFlow(
        name=text_of(item.get("name")), entry_point=entry_of(item.get("entry_point"), context),
        steps=[FlowStep(description=text_of(step.get("description")),
                        finding_ids=ids_in(step.get("finding_ids"), known))
               for step in (item.get("steps") if isinstance(item.get("steps"), list) else [])
               if isinstance(step, dict) and text_of(step.get("description"))])
        for item in items if isinstance(item, dict) and text_of(item.get("name"))]


def coverage_of(value: object, known: set[str]) -> list[CoverageArea]:
    items = value if isinstance(value, list) else []
    return [CoverageArea(
        area=text_of(item.get("area")),
        status=item.get("status") if item.get("status") in COVERAGE else "not_investigated",
        evidence_ids=ids_in(item.get("evidence_ids"), known), reason=text_of(item.get("reason")))
        for item in items if isinstance(item, dict) and text_of(item.get("area"))]


def unknowns_of(value: object) -> list[RepositoryUnknown]:
    items = value if isinstance(value, list) else []
    return [RepositoryUnknown(question=text_of(item.get("question")),
                              reason=text_of(item.get("reason")),
                              investigate=strings(item.get("investigate")))
            for item in items if isinstance(item, dict) and text_of(item.get("question"))]


def conflicts_of(value: object) -> list[str]:
    """Расхождения документации и кода: формат не задан — строка или объект словами."""
    items = value if isinstance(value, list) else []
    texts = []
    for item in items:
        if isinstance(item, dict):
            text = " — ".join(text_of(v) for v in item.values() if text_of(v))
        else:
            text = text_of(item)
        if text:
            texts.append(text)
    return texts


def map_of(data: dict, context: Context) -> RepositoryMap:
    """Карта из ответа участника или судьи. Без списка findings ответ негодный; пустой
    список — честное «ничего относящегося к идее не нашлось»."""
    if not isinstance(data.get("findings"), list):
        raise BadAnswer("нет списка findings")
    findings = findings_of(data.get("findings"), context)
    known = linkable(findings, data.get("findings"))
    return RepositoryMap(findings=findings, flows=flows_of(data.get("flows"), known, context),
                         coverage=coverage_of(data.get("coverage"), known),
                         unknowns=unknowns_of(data.get("unknowns")),
                         documentation_conflicts=conflicts_of(data.get("documentation_conflicts")))


@dataclass(frozen=True)
class Judged:
    complete: bool
    result: RepositoryMap
    follow_up: tuple[FollowUp, ...]


def judged_map(data: dict, context: Context) -> Judged:
    """Итог судьи: проверенная карта и, если исследование недостаточно, задания follow_up.
    complete — заданий нет; needs_investigation без заданий — доисследовать нечего, и это
    тоже конец."""
    status = data.get("status")
    if status not in ("complete", "needs_investigation"):
        raise BadAnswer(f"неизвестный status: {status!r}")
    result = map_of(data, context)
    known = linkable(result.findings, data.get("findings"))
    items = data.get("follow_up") if isinstance(data.get("follow_up"), list) else []
    follow_up = tuple(FollowUp(objective=text_of(item.get("objective")),
                               reason=text_of(item.get("reason")),
                               targets=strings(item.get("targets")),
                               related_finding_ids=ids_in(item.get("related_finding_ids"), known))
                      for item in items
                      if isinstance(item, dict) and text_of(item.get("objective")))
    if status == "complete" or not follow_up:
        return Judged(True, result, ())
    return Judged(False, result, follow_up)


def as_prompt(result: RepositoryMap) -> dict:
    """Карта — в той форме, в какой её просили у моделей."""
    return result.model_dump(mode="json")


def context_prompt(result: RepositoryMap | None, commit_sha: str = "", *,
                   dirty: bool = False, outside: int = 0, omitted: Sequence[str] = (),
                   omitted_count: int = 0, complete: bool = True,
                   follow_up: Sequence[FollowUp] = ()) -> str:
    """Что получают следующие шаги: проверенная карта репозитория или честное «не
    сканировали». uncommitted_changes — карта снята с рабочей копии с незакоммиченными
    правками, а не с самого коммита: следующие шаги не припишут ему то, чего в нём нет;
    files_outside_checkout — сколько файлов коммита вне sparse checkout, а not_in_snapshot —
    чего ещё нет в снимке (нескачанные подмодули, ссылки; первые, всего — _count): этого модели
    не видели; complete — судья счёл исследование достаточным, а remaining_follow_up — что
    доисследовать не успели: недоисследованное — не установленное."""
    if result is None:
        return "Репозиторий не исследовался: существующей реализации шаг не видел."
    return json.dumps({"commit_sha": commit_sha, "uncommitted_changes": dirty,
                       "files_outside_checkout": outside,
                       "not_in_snapshot": capped(omitted),
                       "not_in_snapshot_count": max(omitted_count, len(omitted)),
                       "complete": complete,
                       "remaining_follow_up": [
                           {"objective": item.objective, "reason": item.reason,
                            "targets": item.targets} for item in follow_up[:ABSENT_SHOWN]],
                       **as_prompt(result)},
                      ensure_ascii=False, indent=2)
