"""Решения проекта для потока: каталог прошлых ADR из заметок (notes.py), след каждого в коде и
разбор того, какие из них участники и судья сочли относящимися к идее.

Каталог — по одной записи на ADR: к какой идее, на какой вопрос, что решено, действует ли оно.
След в коде собирает код, а не модель: по файлам, на которые опирается утверждённая карта
репозитория, `git log` находит коммиты с номерами задач (ISS-0012), по заметкам — итог этой
задачи, а по итогу — его ADR. Модель номер не придумает. Коммитов с номерами может и не быть
(код старше, клон без истории) — тогда следа нет, и остаётся отбор по смыслу.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from .models import CodeTrail, ProjectDecision, RepositoryScan
from .notes import Catalog, issues_in
from .repository import RepositoryError, git_bytes
from .repository import text_of as reason_text
from .slicing import BadAnswer

# Сколько файлов карты и коммитов на файл смотреть: след — довод, а не полный аудит.
FILES_MAX = 100
COMMITS_MAX = 200
RELEVANCE = ("applicable", "potential_conflict", "uncertain")
ADR_ID = re.compile(r"\s*([A-Za-z]+)-0*(\d+)\s*")


def records(catalog: Catalog, trails: Mapping[str, list[CodeTrail]],
            excluded: Iterable[str] = ()) -> list[ProjectDecision]:
    """Каталог решений проекта: каждое ADR — с идеей, вопросом и статусом. excluded — решения
    самого потока из его прошлой выгрузки: себе они не «прошлые решения»."""
    skip = set(excluded)
    found: list[ProjectDecision] = []
    adrs = sorted((note for note in catalog.notes.values() if note.type == "adr"),
                  key=lambda note: note.id)
    for adr in adrs:
        if adr.id in skip:
            continue
        status, by = catalog.status(adr.id)
        roots = sorted(catalog.roots(adr.id))
        found.append(ProjectDecision(
            adr_id=adr.id, idea=catalog.notes[roots[0]].body if roots else "",
            question=question_of(catalog, adr.links), decision=adr.body, status=status,
            superseded_by=by, found_in_code=trails.get(adr.id, [])))
    return found


def question_of(catalog: Catalog, links: Sequence[str]) -> str:
    """Вопрос, на который отвечает решение: ADR → его вариант → вопрос варианта."""
    proposal = catalog.notes.get(links[0]) if links else None
    question = catalog.notes.get(proposal.links[0]) if proposal and proposal.links else None
    return question.body if question is not None else ""


def issue_outcomes(catalog: Catalog) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    """Задача → её итоги и решения каждого — по строкам задач в заметках итогов. Задача может
    делать несколько итогов: тогда в каждом строка с её номером."""
    found: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for note in sorted(catalog.notes.values(), key=lambda note: note.id):
        if note.type == "outcome":
            for issue in issues_in(note.body):
                found.setdefault(issue, []).append((note.id, note.links))
    return found


def evidence_files(scan: RepositoryScan) -> list[tuple[Path, str, str]]:
    """Файлы, на которые опирается карта: (корень рабочей копии, путь в ней, путь в карте).
    У нескольких копий путь в карте начинается с её папки."""
    roots = {source.name: Path(source.root) for source in scan.repositories if source.root}
    paths = dict.fromkeys(evidence.path for finding in (scan.result.findings if scan.result
                                                        else [])
                          for evidence in finding.evidence)
    files: list[tuple[Path, str, str]] = []
    for shown in paths:
        folder, _, rest = shown.partition("/") if len(roots) > 1 else ("", "", shown)
        if folder in roots and rest and "\\" not in rest:
            files.append((roots[folder], rest, shown))
    return files[:FILES_MAX]


def trails_of(files: Sequence[tuple[Path, str, str]],
              outcomes: Mapping[str, Sequence[tuple[str, tuple[str, ...]]]]
              ) -> dict[str, list[CodeTrail]]:
    """След решений в коде: коммиты по файлам карты с номерами задач, которые есть в заметках.
    git не запускается или файла нет в истории — у этого файла следа просто нет."""
    found: dict[str, dict[tuple[str, str], CodeTrail]] = {}
    for root, path, shown in files:
        try:
            output = git_bytes(root, "log", "-n", str(COMMITS_MAX),
                               "--format=%h%x1f%s%x1f%b%x1e", "--", path)
        except RepositoryError:
            continue
        for record in output.decode("utf-8", "replace").split("\x1e"):
            commit, _, message = record.strip().partition("\x1f")
            for issue in issues_in(message):
                for outcome, adrs in outcomes.get(issue, ()):
                    for adr in adrs:
                        found.setdefault(adr, {}).setdefault(
                            (issue, shown), CodeTrail(issue=issue, outcome=outcome,
                                                      commit=commit, file=shown))
    return {adr: list(trail.values()) for adr, trail in found.items()}


def decision_id(value: object, known: Mapping[tuple[str, int], str]) -> str | None:
    """Номер решения из ответа — из каталога; без нулей («ADR-7») — то же, что «ADR-0007»."""
    found = ADR_ID.fullmatch(value) if isinstance(value, str) else None
    return known.get((found.group(1).upper(), int(found.group(2)))) if found else None


def selected(data: dict, catalog: Sequence[ProjectDecision],
             allowed: set[str] | None = None) -> list[ProjectDecision]:
    """Отобранные решения из ответа: номер из каталога (у судьи — из предложенных участниками),
    категория из трёх, причина. Чужой номер или категория — мимо; повтор — первый."""
    items = data.get("decisions")
    if not isinstance(items, list):
        raise BadAnswer("нет списка decisions")
    by_id = {record.adr_id: record for record in catalog}
    known = {}
    for adr_id in by_id:
        found = ADR_ID.fullmatch(adr_id)
        if found:
            known[(found.group(1).upper(), int(found.group(2)))] = adr_id
    chosen: dict[str, ProjectDecision] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        adr_id = decision_id(item.get("adr_id"), known)
        relevance = item.get("relevance")
        if (adr_id is None or adr_id in chosen or relevance not in RELEVANCE
                or (allowed is not None and adr_id not in allowed)):
            continue
        chosen[adr_id] = by_id[adr_id].model_copy(update={
            "relevance": relevance, "reason": reason_text(item.get("reason"))})
    return list(chosen.values())


def same_selection(lists: Sequence[Sequence[ProjectDecision]]) -> bool:
    """Участники сошлись: те же решения с теми же категориями — судья не нужен."""
    return len({frozenset((d.adr_id, d.relevance) for d in found) for found in lists}) == 1


def catalog_prompt(catalog: Sequence[ProjectDecision]) -> list[dict]:
    """Каталог для промпта — записи без оценки: её и просят у моделей."""
    return [record.model_dump(mode="json", exclude={"relevance", "reason"})
            for record in catalog]
