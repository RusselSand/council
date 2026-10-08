"""Репозиторий потока: inventory рабочей копии и разбор ответов участников и судьи.

Inventory — обычный список файлов, его даёт git при запуске скана: отслеживаемые и новые,
не игнорируемые, и только те, что на диске есть, — то, что модели и будут читать. Git зовётся
только на чтение: каталог может быть смонтирован read-only, а владелец — не тот, кто запускает
(safe.directory). Корень рабочей копии — внутри каталога репозиториев, иначе модели увидели
бы то, что он отрезает. Отпечаток рабочей копии — путь, коммит и её правки: оплаченный ответ
к другому коду повтор не возьмёт.

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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
    commit_sha: str
    dirty: bool
    files: tuple[str, ...]
    # Какая это рабочая копия и в каком состоянии: путь, коммит, правки и новые файлы.
    fingerprint: str = ""


class Digest(Protocol):
    """Куда складывать вывод: хеш, который принимает его кусками."""

    def update(self, data: bytes, /) -> None: ...


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


def git_stream(root: Path, digest: Digest, *args: str) -> None:
    """Вывод git — прямо в хеш, кусками: патч большого бинарника целиком в памяти не держим.
    stderr — во временный файл: в трубе он мог бы заполнить её и остановить git."""
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(git_command(root, *args), stdout=subprocess.PIPE,
                                       stderr=errors)
        except OSError as exc:
            raise RepositoryError(f"git не запускается: {exc}") from exc
        with process:
            for chunk in iter(lambda: process.stdout.read(1 << 16), b""):
                digest.update(chunk)
            code = process.wait(timeout=120)
        if code != 0:
            errors.seek(0)
            detail = errors.read().decode("utf-8", errors="replace").strip()
            raise RepositoryError(detail or f"git {args[0]} не удался")


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


def inventory(path: Path) -> Inventory:
    """Корень рабочей копии, её коммит, есть ли незакоммиченные правки, список файлов — тех,
    что на диске есть (удалённый, но отслеживаемый, и вне sparse checkout — не файлы), — и
    отпечаток её состояния."""
    root = Path(git(path, "rev-parse", "--show-toplevel").strip()).resolve()
    sha = git(root, "rev-parse", "HEAD").strip()
    dirty = bool(git(root, "status", "--porcelain").strip())
    # Отслеживаемые — и в checked-out подмодулях (их файлы модели тоже читают), новые — отдельно:
    # --recurse-submodules с --others git не умеет.
    fresh = untracked(root)
    listed = [*names(git_bytes(root, "ls-files", "-z", "--cached", "--recurse-submodules")), *fresh]
    files = tuple(sorted({name for name in listed if (root / name).exists()}))
    return Inventory(root, sha, dirty, files, fingerprint(root, sha, fresh))


def fingerprint(root: Path, sha: str, fresh: list[str]) -> str:
    """Состояние рабочей копии: путь, коммит, правки отслеживаемых файлов — и внутри
    подмодулей — и новые файлы (fresh), и в подмодулях тоже. Одинаковый у одного и того же
    кода в одной и той же копии."""
    digest = hashlib.sha256(f"{root}\0{sha}\0".encode())
    git_stream(root, digest, "diff", "HEAD", "--binary", "--no-ext-diff", "--submodule=diff")
    for name in sorted(fresh):
        digest.update(name.encode() + b"\0" + file_state(root / name) + b"\0")
    return digest.hexdigest()


def file_state(path: Path) -> bytes:
    """Состояние нового файла для отпечатка. Ссылку не разыменовываем — это её цель словами: за
    ней может быть что угодно, вплоть до /dev/zero. Обычный файл — хеш содержимого, кусками: а
    то большой артефакт занял бы всю память. Прочее (FIFO, устройство) — по типу: его не читают.
    Не прочитать — тоже состояние."""
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            return b"link:" + os.readlink(path).encode()
        if stat.S_ISREG(info.st_mode):
            with path.open("rb") as file:
                return hashlib.file_digest(file, "sha256").digest()
        return b"special"
    except OSError:
        return b"-"


def inventory_prompt(found: Inventory) -> str:
    shown = found.files[:INVENTORY_MAX]
    text = "\n".join(shown)
    if len(found.files) > len(shown):
        text += f"\n… и ещё {len(found.files) - len(shown)} файлов: ищите по репозиторию сами"
    return text


def sha_prompt(found: Inventory) -> str:
    return found.commit_sha + (" (в рабочей копии есть незакоммиченные изменения: читайте её)"
                               if found.dirty else "")


# --- разбор


@dataclass(frozen=True)
class Context:
    """На что могут ссылаться находки: файлы репозитория."""

    files: frozenset[str]


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
        path = text_of(item.get("path")).replace("\\", "/").removeprefix("./")
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


def flows_of(value: object, known: set[str]) -> list[RepositoryFlow]:
    items = value if isinstance(value, list) else []
    return [RepositoryFlow(
        name=text_of(item.get("name")), entry_point=text_of(item.get("entry_point")),
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
    return RepositoryMap(findings=findings, flows=flows_of(data.get("flows"), known),
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
