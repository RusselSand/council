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
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

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


def git_command(root: Path, *args: str) -> list[str]:
    # --no-optional-locks: status не пытается обновить индекс — каталог может быть read-only.
    return ["git", "-c", "safe.directory=*", "--no-optional-locks", "-C", str(root), *args]


def git_bytes(root: Path, *args: str) -> bytes:
    command = git_command(root, *args)
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RepositoryError(f"git не запускается: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RepositoryError(detail or f"git {args[0]} не удался")
    return result.stdout


def git(root: Path, *args: str) -> str:
    return git_bytes(root, *args).decode("utf-8", errors="replace")


def untracked(root: Path, prefix: str = "") -> list[str]:
    """Новые, не игнорируемые файлы — и внутри checked-out подмодулей: --others в них не
    заходит, а модели их читают."""
    found = [prefix + name
             for name in names(git_bytes(root, "ls-files", "-z", "--others", "--exclude-standard"))]
    for link in gitlinks(root):
        if (root / link / ".git").exists():
            found += untracked(root / link, f"{prefix}{link}/")
    return found


def gitlinks(root: Path) -> list[str]:
    """Пути подмодулей: записи индекса с режимом 160000 («<режим> <sha> <стадия>\t<путь>»)."""
    entries = names(git_bytes(root, "ls-files", "-z", "--stage"))
    return [entry.split("\t", 1)[1] for entry in entries if entry.startswith("160000 ")]


def names(output: bytes) -> list[str]:
    """Пути из вывода с -z: через NUL, без кавычек и восьмеричных escape-кодов."""
    return [name.decode("utf-8", errors="replace") for name in output.split(b"\0") if name]


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
    return found


def head(root: Path) -> str:
    """Коммит рабочей копии; пусто — коммитов ещё нет, а файлы есть."""
    try:
        return git(root, "rev-parse", "--verify", "-q", "HEAD").strip()
    except RepositoryError:
        return ""


def state_of(root: Path) -> bytes:
    """Коммит и git status — с каждым новым файлом и подмодулями: поменялись — рабочую копию
    правили."""
    status = git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                       "--ignore-submodules=none")
    return head(root).encode() + b"\0" + status


def inventory(path: Path) -> Inventory:
    """Корень рабочей копии, её коммит, есть ли незакоммиченные правки, и список файлов — тех,
    что на диске есть, это обычные файлы и лежат в рабочей копии (удалённый, но отслеживаемый,
    вне sparse checkout, ссылка и файл за каталогом-ссылкой — не её файлы)."""
    root = Path(git(path, "rev-parse", "--show-toplevel").strip()).resolve()
    state = state_of(root)
    sha, status = state.split(b"\0", 1)
    listed = [*names(git_bytes(root, "ls-files", "-z", "--cached", "--recurse-submodules")),
              *untracked(root)]
    files = tuple(sorted({name for name in listed if plain(root, name)}))
    return Inventory(root, sha.decode(), bool(status.strip(b"\0 ")), files, state)


def plain(root: Path, name: str) -> bool:
    """Обычный файл, и путь к нему — внутри рабочей копии: ни он сам, ни каталоги по дороге не
    ссылки наружу. За ссылкой может быть что угодно, вплоть до /dev/zero или чужих ключей."""
    path = root / name
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return False
    except OSError:
        return False
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(root))


def snapshot(found: Inventory, into: Path) -> tuple[str, frozenset[str]]:
    """Снимок рабочей копии, который читают модели: только файлы inventory — без .git и
    игнорируемого (там бывают .env и ключи) — и только обычные файлы внутри неё. Пока идёт
    скан, рабочую копию могут править, а снимок неподвижен: все участники и все проходы читают
    один и тот же код. Правили, пока он делался, — снимок был бы смесью старого и нового:
    RepositoryError. Отпечаток — по содержимому снимка и битам исполняемости: им ключуются
    оплаченные ответы, и тот же код в другой копии — тот же ключ. Вернёт отпечаток и какие
    файлы в снимок легли."""
    digest = hashlib.sha256()
    taken: dict[str, tuple[int, int]] = {}
    for name in found.files:
        copied = copied_file(found.root, name, into / name)
        if copied is not None:
            part, stamp = copied
            digest.update(name.encode() + b"\0" + part + b"\0")
            taken[name] = stamp
    if state_of(found.root) != found.state or any(
            stamp_of(found.root / name) != stamp for name, stamp in taken.items()):
        raise RepositoryError("Рабочая копия менялась, пока делался её снимок, — запустите скан "
                              "снова, когда правки закончатся")
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
    — по пути без ссылок (realpath) и только внутри рабочей копии. FIFO не ждём: O_NONBLOCK."""
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
    real = os.path.realpath(root / name)
    if not Path(real).is_relative_to(os.path.realpath(root)):
        raise OSError(f"{name}: вне рабочей копии")
    return os.open(real, flags)


def copied_file(root: Path, name: str, target: Path) -> tuple[bytes, tuple[int, int]] | None:
    """Копия одного файла кусками — и хеш его содержимого с битом исполняемости, и его размер
    и время правки на момент копирования. Пропал, не читается, не обычный файл — None."""
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
        with target.open("wb") as write:
            for chunk in iter(lambda: read.read(1 << 16), b""):
                digest.update(chunk)
                write.write(chunk)
    executable = bool(info.st_mode & 0o111) and os.name != "nt"
    if executable:
        target.chmod(0o755)   # исполняемый — и в снимке: модели видят, что это запускают
    return digest.digest() + (b"x" if executable else b"-"), (info.st_size, info.st_mtime_ns)


def inventory_prompt(found: Inventory) -> str:
    shown = found.files[:INVENTORY_MAX]
    text = "\n".join(shown)
    if len(found.files) > len(shown):
        text += f"\n… и ещё {len(found.files) - len(shown)} файлов: ищите по репозиторию сами"
    return text


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
        """Путь файла, как его назвала модель, — относительный, как в inventory."""
        path = text_of(value).replace("\\", "/").removeprefix("./")
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
        found.append(Evidence(path=path, lines=text_of(item.get("lines")) or None,
                              symbol=text_of(item.get("symbol")) or None))
    return found


def findings_of(value: object, context: Context) -> list[RepositoryFinding]:
    items = value if isinstance(value, list) else []
    found: dict[str, RepositoryFinding] = {}
    for item in items:
        if not isinstance(item, dict) or not text_of(item.get("statement")):
            continue
        name = finding_id(item.get("id")) or f"R{len(found) + 1}"
        while name in found:
            name = f"R{int(name[1:]) + 1}"
        status = item.get("status") if item.get("status") in STATUSES else "unknown"
        evidence = evidence_of(item.get("evidence"), context)
        if status == "verified" and not evidence:
            status = "inferred"   # verified без подтверждения в репозитории — только вывод
        found[name] = RepositoryFinding(id=name, statement=text_of(item.get("statement")),
                                        status=status, evidence=evidence,
                                        relevance=text_of(item.get("relevance")))
    return list(found.values())


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
            return path + text[end:]
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
    known = {finding.id for finding in findings}
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
    known = {finding.id for finding in result.findings}
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


def context_prompt(result: RepositoryMap | None, commit_sha: str = "") -> str:
    """Что получают следующие шаги: проверенная карта репозитория или честное «не
    сканировали»."""
    if result is None:
        return "Репозиторий не исследовался: существующей реализации шаг не видел."
    return json.dumps({"commit_sha": commit_sha, **as_prompt(result)}, ensure_ascii=False,
                      indent=2)
