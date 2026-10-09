"""Заметки проекта: IDEA → OPEN QUESTION → PROPOSAL → ADR → OUTCOME файлами Markdown.

Формат — как в Causa, чтобы граф читали и её инструменты: файл на заметку в папке своего типа
(`ideas/IDEA-0001.md`, `open_questions/OQ-0001.md`, `proposals/PRO-0001.md`,
`adrs/ADR-0001.md`, `outcomes/OUT-0001.md`), во frontmatter `id`, `type` и `links` —
ближайшие вышестоящие заметки, в теле — текст. Правила графа — тоже её:
- IDEA ни на что не ссылается;
- OPEN QUESTION — ровно на одну IDEA, PROPOSAL или ADR (вопрос может вырасти из решения);
- PROPOSAL — ровно на один OPEN QUESTION, ADR — ровно на один PROPOSAL;
- OUTCOME — на один или несколько ADR одной и той же корневой IDEA;
- у каждой заметки одна корневая IDEA.

Номера — общие на весь каталог: следующий свободный номер типа, с нулями до четырёх знаков.

Команда для агентов — только чтение, ответ в JSON:
    python -m spec_council.notes <каталог> get ADR-0003
    python -m spec_council.notes <каталог> chain IDEA-0002
    python -m spec_council.notes <каталог> list --type adr
    python -m spec_council.notes <каталог> links OQ-0007
    python -m spec_council.notes <каталог> search "офлайн"
    python -m spec_council.notes <каталог> validate
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

TYPES = ("idea", "open_question", "proposal", "adr", "outcome")
PREFIXES = {"idea": "IDEA", "open_question": "OQ", "proposal": "PRO", "adr": "ADR",
            "outcome": "OUT"}
FOLDERS = {"idea": "ideas", "open_question": "open_questions", "proposal": "proposals",
           "adr": "adrs", "outcome": "outcomes"}
UPSTREAM = {"idea": frozenset(), "open_question": frozenset({"idea", "proposal", "adr"}),
            "proposal": frozenset({"open_question"}), "adr": frozenset({"proposal"}),
            "outcome": frozenset({"adr"})}
ISSUE_ID = re.compile(r"\bISS-\d+\b")
# Строка задачи в теле итога: «- ISS-0012: название». Номер в другом месте — упоминание.
ISSUE_LINE = re.compile(r"- (ISS-\d+):")
# Подписи критериев готовности в итоге (export.WORDS): список под ними — критерии, пусть и из
# строк «- ISS-…:».
CRITERIA = frozenset({"критерии готовности", "acceptance criteria"})
NUMBERED = re.compile(r"([A-Z]+)-(\d+)")
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


class NotesError(ValueError):
    """Заметку не прочитать или граф нарушает правила — текст для человека и агента."""


@dataclass(frozen=True)
class Note:
    id: str
    type: str
    body: str
    links: tuple[str, ...] = ()
    path: Path | None = field(default=None, compare=False)

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "type": self.type, "body": self.body, "links": list(self.links)}


# --- файл заметки


def scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parsed(text: str, path: Path | None = None) -> Note:
    """Заметка из файла. Frontmatter — подмножество YAML, которое пишет Causa (`links: []`,
    `links:` со строками `- ID`) и которое пишут руками (`links: [A, B]`)."""
    found = FRONTMATTER.match(text)
    where = f" {path}" if path else ""
    if found is None:
        raise NotesError(f"В заметке{where} нет frontmatter между строками ---")
    meta: dict[str, object] = {}
    key = None
    for line in found.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"\s*-\s*(.+)$", line)
        if item and key == "links" and isinstance(meta.get("links"), list):
            meta["links"].append(scalar(item.group(1)))
            continue
        pair = re.match(r"([A-Za-z_]+)\s*:\s*(.*)$", line)
        if pair is None:
            raise NotesError(f"Непонятная строка frontmatter в заметке{where}: {line.strip()}")
        key, value = pair.group(1), pair.group(2).strip()
        if key == "links":
            if value in ("", "[]"):
                meta["links"] = []
            elif value.startswith("[") and value.endswith("]"):
                meta["links"] = [scalar(v) for v in value[1:-1].split(",") if v.strip()]
            else:
                raise NotesError(f"В заметке{where} links — не список")
        else:
            meta[key] = scalar(value)
    note_id, kind = meta.get("id"), meta.get("type")
    if not isinstance(note_id, str) or not note_id:
        raise NotesError(f"В заметке{where} нет id")
    if kind not in TYPES:
        raise NotesError(f"У заметки {note_id} неизвестный type: {kind!r}")
    # Номер — префикс типа и число (ADR-7 и ADR-0007): по нему отбор решений узнаёт номер, а
    # next_id — следующий.
    if re.fullmatch(rf"{PREFIXES[str(kind)]}-\d+", note_id) is None:
        raise NotesError(f"Заметка{where} {note_id}: номер не по формату "
                         f"{PREFIXES[str(kind)]}-0001 для type {kind}")
    links = meta.get("links", [])
    return Note(note_id, str(kind), found.group(2).strip(), tuple(links), path)


def rendered(note: Note) -> str:
    """Заметка файлом — как пишет Causa."""
    links = "links: []" if not note.links else "links:\n" + "\n".join(
        f"- {link}" for link in note.links)
    return f"---\nid: {note.id}\ntype: {note.type}\n{links}\n---\n\n{note.body.strip()}\n"


def path_of(root: Path, note: Note) -> Path:
    """Где заметка: прочитанная из каталога — там, откуда прочли (файл могли переименовать),
    новая — в папке своего типа, под своим номером."""
    return note.path if note.path is not None else root / FOLDERS[note.type] / f"{note.id}.md"


# --- каталог


@dataclass(frozen=True)
class Catalog:
    """Все заметки каталога и связи между ними в обе стороны."""

    notes: Mapping[str, Note]

    @classmethod
    def load(cls, root: Path) -> Catalog:
        """Заметки из папок типов. Другие .md в каталоге не читаются; два файла с одним id (или
        одним номером, записанным по-разному) — ошибка."""
        notes: dict[str, Note] = {}
        numbers: dict[tuple[str, int], Note] = {}     # ADR-7 и ADR-0007 — один номер
        for kind, folder in FOLDERS.items():
            for path in sorted((root / folder).glob("*.md")) if (root / folder).is_dir() else ():
                try:
                    note = parsed(path.read_text(encoding="utf-8"), path)
                except (OSError, UnicodeError) as exc:
                    raise NotesError(f"Заметку {path} не прочитать: {exc}") from None
                if note.type != kind:
                    raise NotesError(f"Заметка {note.id} типа {note.type} лежит в {folder}/")
                twin = numbers.setdefault(number_of(note.id), note)
                if twin is not note:
                    raise NotesError(f"Две заметки с id {note.id}: {twin.path} и {path}"
                                     if twin.id == note.id else
                                     f"{twin.id} и {note.id} — один номер, записанный "
                                     f"по-разному: {twin.path} и {path}")
                notes[note.id] = note
        return cls(notes)

    def children(self, note_id: str) -> list[Note]:
        return sorted((note for note in self.notes.values() if note_id in note.links),
                      key=order)

    def roots(self, note_id: str) -> set[str]:
        """Корневые IDEA заметки — по ссылкам вверх."""
        found: set[str] = set()
        seen: set[str] = set()
        stack = [note_id]
        while stack:
            current = stack.pop()
            if current in seen or current not in self.notes:
                continue
            seen.add(current)
            note = self.notes[current]
            if note.type == "idea":
                found.add(current)
            stack.extend(note.links)
        return found

    def problems(self) -> list[str]:
        """Что в графе не по правилам: висячие ссылки, не те типы связей, не то их число,
        несколько корней, круги."""
        found: list[str] = []
        for note in sorted(self.notes.values(), key=order):
            found += link_problems(note, self.notes)
            if note.type != "idea" and len(self.roots(note.id)) > 1:
                found.append(f"{note.id}: несколько корневых IDEA "
                             f"({', '.join(sorted(self.roots(note.id)))})")
            if self.circular(note.id):
                found.append(f"{note.id}: ссылки идут по кругу")
        return found

    def circular(self, note_id: str) -> bool:
        stack = [(link, {note_id}) for link in self.notes[note_id].links]
        while stack:
            current, path = stack.pop()
            if current == note_id:
                return True
            if current in path or current not in self.notes:
                continue
            stack.extend((link, path | {current}) for link in self.notes[current].links)
        return False

    def chain(self, idea_id: str) -> list[Note]:
        """Всё, что растёт из идеи, — по типам и номерам."""
        return sorted((note for note in self.notes.values()
                       if note.id == idea_id or self.roots(note.id) == {idea_id}), key=order)

    def occupant(self, note_id: str) -> Note | None:
        """Другая заметка в файле с именем note_id (ADR-0001.md) — его переименовали: новая
        заметка с этим номером легла бы туда и затёрла её."""
        return next((note for note in self.notes.values() if note.path is not None
                     and note.path.stem == note_id and note.id != note_id), None)

    def next_id(self, kind: str, taken: Iterable[str] = ()) -> str:
        """Следующий свободный номер типа — после самого большого в каталоге и в taken. Имя
        файла тоже занимает номер: в ADR-0002.md могла лечь другая заметка, и новая ADR-0002
        её бы затёрла."""
        prefix = PREFIXES[kind]
        pattern = re.compile(rf"{prefix}-(\d+)")
        names = [note.path.stem for note in self.notes.values() if note.path is not None]
        numbers = [int(found.group(1)) for note_id in (*self.notes, *taken, *names)
                   if (found := pattern.fullmatch(note_id))]
        return f"{prefix}-{max(numbers, default=0) + 1:04d}"

    def status(self, adr_id: str) -> tuple[str, str | None]:
        """Действует ли решение: из ADR вырос вопрос (его пересматривают) — under_review, пока
        на вопрос нет нового ADR, и superseded, когда он есть (и каким). Пересмотров несколько
        и хоть один уже решён — заменено, сколько бы других ещё ни шло."""
        replaced = None
        pending = False
        for question in self.children(adr_id):
            if question.type != "open_question":
                continue
            answers = [adr for proposal in self.children(question.id)
                       for adr in self.children(proposal.id) if adr.type == "adr"]
            if answers:
                replaced = replaced or answers[-1].id
            else:
                pending = True
        if replaced:
            return "superseded", replaced
        return ("under_review", None) if pending else ("active", None)


def order(note: Note) -> tuple[int, str]:
    return TYPES.index(note.type), note.id


def link_problems(note: Note, notes: Mapping[str, Note]) -> list[str]:
    found: list[str] = []
    allowed = UPSTREAM[note.type]
    count = len(note.links)
    if note.type == "idea" and count:
        found.append(f"{note.id}: IDEA ни на что не ссылается")
    if note.type in ("open_question", "proposal", "adr") and count != 1:
        found.append(f"{note.id}: нужна ровно одна вышестоящая заметка, а их {count}")
    if note.type == "outcome" and not count:
        found.append(f"{note.id}: OUTCOME ссылается хотя бы на один ADR")
    for link in note.links:
        target = notes.get(link)
        if target is None:
            found.append(f"{note.id}: ссылка на несуществующую заметку {link}")
        elif target.type not in allowed:
            found.append(f"{note.id}: {note.type} не может ссылаться на {target.type} ({link})")
    return found


def issues_in(text: str) -> list[str]:
    """Номера задач (ISS-…) в тексте — в заметке итога или сообщении коммита."""
    return list(dict.fromkeys(ISSUE_ID.findall(text)))


def declared_issues(text: str) -> list[str]:
    """Задачи итога — его список задач: последний блок, строка-подпись («Задачи:», «Issues:» —
    на любом языке, только не подпись критериев) и под ней только строки «- ISS-…: название».
    Номер в другом месте, и в критериях готовности тоже, — упоминание, а не задача итога."""
    blocks = [block for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    lines = [line.strip() for line in blocks[-1].splitlines()] if blocks else []
    if (len(lines) < 2 or not lines[0].endswith(":")
            or lines[0][:-1].strip().casefold() in CRITERIA):
        return []
    found = [ISSUE_LINE.match(line) for line in lines[1:]]
    if not all(found):
        return []
    return list(dict.fromkeys(match.group(1) for match in found if match))


def number_of(note_id: str) -> tuple[str, int]:
    found = NUMBERED.fullmatch(note_id)
    return (found.group(1), int(found.group(2))) if found else (note_id, -1)


# --- команда для агентов


def links_of(catalog: Catalog, note_id: str) -> dict[str, object]:
    note = catalog.notes[note_id]
    return {"id": note_id, "upstream": list(note.links),
            "downstream": [child.id for child in catalog.children(note_id)]}


def described(catalog: Catalog, note: Note) -> dict[str, object]:
    found = {**note.as_dict(), "downstream": [child.id for child in catalog.children(note.id)]}
    if note.type == "adr":
        status, by = catalog.status(note.id)
        found |= {"status": status, "superseded_by": by}
    return found


def answered(args: argparse.Namespace) -> object:
    catalog = Catalog.load(Path(args.root))
    if args.command == "validate":
        return {"problems": catalog.problems()}
    if args.command == "list":
        return [described(catalog, note) for note in sorted(catalog.notes.values(), key=order)
                if args.type is None or note.type == args.type]
    if args.command == "search":
        needle = args.text.casefold()
        return [described(catalog, note) for note in sorted(catalog.notes.values(), key=order)
                if needle in note.body.casefold()]
    if args.id not in catalog.notes:
        raise NotesError(f"Заметки {args.id} нет")
    if args.command == "get":
        return described(catalog, catalog.notes[args.id])
    if args.command == "links":
        return links_of(catalog, args.id)
    if catalog.notes[args.id].type != "idea":
        raise NotesError(f"{args.id} — не IDEA: цепочка растёт из идеи")
    return [described(catalog, note) for note in catalog.chain(args.id)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m spec_council.notes",
        description="Заметки проекта — только чтение, ответ в JSON.")
    parser.add_argument("root", help="каталог заметок (COUNCIL_NOTES)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, helped in (("get", "заметка"), ("chain", "всё, что растёт из IDEA"),
                         ("links", "вышестоящие и нижестоящие заметки")):
        commands.add_parser(name, help=helped).add_argument("id")
    listing = commands.add_parser("list", help="заметки, все или одного типа")
    listing.add_argument("--type", choices=TYPES)
    commands.add_parser("search", help="заметки с этим текстом").add_argument("text")
    commands.add_parser("validate", help="что в графе не по правилам")
    args = parser.parse_args(argv)
    try:
        result = answered(args)
    except NotesError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
