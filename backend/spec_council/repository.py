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
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

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
# Снимок ложится на диск сервера: рабочую копию больше этого не копируем, а отказываем, —
# и по байтам, и по числу файлов (крошечных их бывает миллион: кончились бы память и inode).
SNAPSHOT_MAX = 512 * 2**20
FILES_MAX = 100_000
# Больше вывода от одной команды git не читаем.
OUTPUT_MAX = 64 * 2**20
GIT_TIMEOUT = 120
TEXT_MAX = 2000
FINDING_ID = re.compile(r"R?(\d+)", re.IGNORECASE)
STATUSES = ("verified", "inferred", "unknown")
COVERAGE = ("covered", "partial", "not_investigated", "not_applicable")


class RepositoryError(ValueError):
    """Каталог не годится для скана: его нет, это не рабочая копия git или git не запускается.
    Текст — для человека."""


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


def git_command(root: Path, *args: str) -> list[str]:
    # --no-optional-locks: status не пытается обновить индекс — каталог может быть read-only.
    return ["git", "-c", "safe.directory=*", "--no-optional-locks", "-C", str(root), *args]


def git_bytes(root: Path, *args: str) -> bytes:
    """Вывод git — кусками и не больше OUTPUT_MAX: больше — RepositoryError, а git
    останавливаем. В рабочей копии с миллионами файлов один список занял бы всю память."""
    command = git_command(root, *args)
    expired = threading.Event()
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
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
        if code != 0:
            errors.seek(0)
            detail = errors.read(8192).decode("utf-8", errors="replace").strip()
            raise RepositoryError(detail or f"git {args[0]} не удался")
    return bytes(output)


def git(root: Path, *args: str) -> str:
    return git_bytes(root, *args).decode("utf-8", errors="replace")


class Copy(NamedTuple):
    """Рабочая копия — корень или вложенная: каталог, путь от корня с «/» на конце (у корня —
    ""), её отслеживаемые и новые, не игнорируемые файлы."""

    folder: Path
    prefix: str
    cached: list[str]
    others: list[str]


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
    queue = [(root, "")]
    while queue:
        folder, prefix = queue.pop(0)
        index = index_of(folder)
        cached = [name for *_, name in index]
        others = names(git_bytes(folder, "ls-files", "-z", "--others", "--exclude-standard"))
        found.append(Copy(folder, prefix, cached, others))
        if sum(len(copy.cached) + len(copy.others) for copy in found) > FILES_MAX:
            raise too_many()            # пока обходим: подмодулей бывает и тысяча
        links = [name for _, mode, _, name in index if mode == b"160000"]
        for link in [*links, *inner_copies(folder, cached, others)]:
            path = folder / link
            real = os.path.realpath(path)
            try:
                is_folder = stat.S_ISDIR(path.lstat().st_mode)
            except OSError:
                continue
            if (not is_folder or real != os.path.abspath(path) or real in seen
                    or not Path(real).is_relative_to(top) or not (path / ".git").exists()):
                continue
            seen.add(real)
            queue.append((path, f"{prefix}{link}/"))
    return found


def inner_copies(folder: Path, *listings: list[str]) -> list[str]:
    """Репозитории внутри, не подмодули: каталоги с .git, где лежат файлы из списков. --others
    показывает такой каталог одной строкой («tools/gen/»), а если в нём есть и отслеживаемые
    файлы внешней копии — поштучно. Игнорируемые каталоги в списки не попадают — в них не ищем."""
    folders: set[str] = set()
    for name in itertools.chain(*listings):
        parts = name.removesuffix("/").split("/")
        whole = name.endswith("/")                   # «tools/gen/» — сам каталог тоже
        folders.update("/".join(parts[:i]) for i in range(1, len(parts) + whole))
    return sorted(inner for inner in folders if os.path.lexists(folder / inner / ".git"))


def names(output: bytes) -> list[str]:
    """Пути из вывода с -z: через NUL, без кавычек и восьмеричных escape-кодов. Байты — как в
    файловой системе (os.fsdecode): имя не в UTF-8 остаётся тем же файлом, а не «�»."""
    return [os.fsdecode(name) for name in output.split(b"\0") if name]


def located(text: str, base: Path | None) -> Path:
    """Каталог рабочей копии по тексту человека. С каталогом репозиториев путь — от него и
    только внутри него; без него — абсолютный."""
    text = text.strip()
    if not text:
        raise RepositoryError("Укажите путь к рабочей копии репозитория")
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
    может оказаться выше выбранной папки."""
    found = inventory(located(text, base))
    if base is not None and not found.root.is_relative_to(base.resolve()):
        raise RepositoryError(f"Корень рабочей копии {found.root} вне каталога репозиториев {base}")
    fits(found)
    return found


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
    (hash-object — с теми же фильтрами, что и git add)."""
    flagged: dict[str, str] = {}
    changed: list[str] = []
    for tag, mode, sha, name in index_of(root):
        if not (tag.islower() or tag == b"S") or mode not in (b"100644", b"100755"):
            continue
        if plain(root, name):
            flagged[name] = sha
        elif tag.upper() != b"S":
            # assume-unchanged, а файла нет или он уже не файл — правка; у skip-worktree это
            # обычный sparse checkout.
            changed.append(name)
    names = list(flagged)
    for start in range(0, len(names), 100):        # по сотне — командная строка не бесконечна
        chunk = names[start:start + 100]
        shas = git(root, "hash-object", "--", *chunk).split()
        changed += [name for name, sha in zip(chunk, shas, strict=True) if sha != flagged[name]]
    return b"\0".join(os.fsencode(name) for name in changed)


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
    try:
        return git(root, "config", "--type=bool", "--get", "core.fileMode").strip() != "false"
    except RepositoryError:
        return True                                  # не задан — сверяет


def status_of(root: Path) -> bytes:
    """--ignore-submodules=dirty: подмодуль не на записанном в родителе коммите — это правка
    (снимок уже не показанный коммит), а что внутри него, git сам не смотрит: это его статус."""
    return git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                     "--ignore-submodules=dirty")


def inventory(path: Path) -> Inventory:
    """Корень рабочей копии, её коммит, есть ли незакоммиченные правки, и список файлов — тех,
    что на диске есть, это обычные файлы и лежат в рабочей копии (удалённый, но отслеживаемый,
    вне sparse checkout, ссылка и файл за каталогом-ссылкой — не её файлы)."""
    root = Path(git(path, "rev-parse", "--show-toplevel").strip()).resolve()
    copies = copies_of(root)
    found = levels(copies)
    listing = set(listed(copies))
    if len(listing) > FILES_MAX:
        raise too_many()                  # до lstat каждого: их может быть миллион
    files = tuple(sorted(name for name in listing if plain(root, name)))
    size = sum(stamp[0] for stamp in (stamp_of(root / name) for name in files) if stamp)
    return Inventory(root, found[0][1], any(status for _, _, status in found), files,
                     state_of(found), modes_of(copies), size)


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
    if state_of(levels(copies_of(found.root))) != found.state or any(
            stamp_of(found.root / name) != stamp for name, stamp in taken.items()):
        raise RepositoryError("Рабочая копия менялась, пока делался её снимок, — запустите скан "
                              "снова, когда правки закончатся")
    if missed:
        shown = ", ".join(missed[:5]) + (f" и ещё {len(missed) - 5}" if len(missed) > 5 else "")
        raise RepositoryError(f"Не прочитать файлы рабочей копии: {shown} — без них карта вышла "
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
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with target.open("wb") as write:
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
    return text


def shown(name: str) -> str:
    """Имя файла, каким его видят модели и человек: байты не из UTF-8 — как \\xNN (как есть
    его в промпт не положить и не сохранить). Обратно его переводит Context.path_of."""
    return os.fsencode(name).decode("utf-8", "backslashreplace")


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
        Windows. Имя, каким его показали моделям (shown), — тоже этот файл."""
        text = text_of(value)
        named = [self.relative(path) for path in dict.fromkeys((text, text.replace("\\", "/")))]
        for path in named:
            if path in self.files:
                return path
            if path in self.originals:
                return self.originals[path]
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
    text = text_of(value)
    ends = [len(text), *sorted({i for i, char in enumerate(text) if char in ": ("}, reverse=True)]
    for end in ends:
        path = context.path_of(text[:end])
        if path in context.files:
            return shown(path) + text[end:]
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
                   dirty: bool = False) -> str:
    """Что получают следующие шаги: проверенная карта репозитория или честное «не
    сканировали». uncommitted_changes — карта снята с рабочей копии с незакоммиченными
    правками, а не с самого коммита: следующие шаги не припишут ему то, чего в нём нет."""
    if result is None:
        return "Репозиторий не исследовался: существующей реализации шаг не видел."
    return json.dumps({"commit_sha": commit_sha, "uncommitted_changes": dirty,
                       **as_prompt(result)}, ensure_ascii=False, indent=2)
