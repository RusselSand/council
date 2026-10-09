"""Выгрузка потока в заметки проекта (notes.py): IDEA, отобранные вопросы, их варианты,
принятые решения и утверждённые итоги — каждое своей заметкой, со ссылками на ближайшие
вышестоящие. Задачи заметками не становятся: они строками в теле своего итога, с номерами на
весь проект (ISS-0012), — их пишут в финальный коммит.

Выгрузка — в два хода. Черновик (drafted): какие заметки лягут, под какими номерами, с каким
текстом и что с ними будет — новая, перепишется, уже такая, правили руками. Запись (written):
то, что человек подтвердил, с его правками текста и отмеченными к удалению исчезнувшими.

Повторная выгрузка узнаёт свои прежние заметки по ключу части потока: вопрос из текста — по
фрагменту, остальные — по формулировке; вариант — по вопросу и фрагменту или формулировке;
решение — по вопросу и выбранному варианту (выбрали другой — это другое решение и новая
заметка); итог и задача — по названию. Совет написал бы то же, что в прошлый раз, — остаётся
то, что тогда записали, с правками человека. Файл, который правили руками после выгрузки,
совет не трогает. Исчезнувшее само не удаляется.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .models import (
    Decision,
    ExportedNote,
    IssueNumber,
    LabeledFragment,
    NotePlan,
    NotesExport,
    OpenQuestion,
    Proposal,
    Stream,
    VanishedNote,
)
from .notes import Catalog, Note, NotesError, issues_in, path_of, rendered
from .questions import same_question

# Связки в тексте заметок — на языке работы; перевод, если нужен, — потом, целиком.
WORDS = {
    "russian": {"because": "потому что", "criteria": "Критерии готовности", "issues": "Задачи"},
    "english": {"because": "because", "criteria": "Acceptance criteria", "issues": "Issues"},
}
ALIASES = {"русский": "russian", "ru": "russian", "en": "english", "английский": "english"}
ISSUE = re.compile(r"ISS-(\d+)")


def words_for(language: str) -> dict[str, str]:
    name = language.strip().lower()
    return WORDS.get(ALIASES.get(name, name), WORDS["english"])


@dataclass(frozen=True)
class Part:
    """Часть потока, которая станет заметкой. links — ключи других частей или номера заметок
    каталога (у вопроса, который пересматривает прошлое решение, — этот ADR)."""

    key: str
    type: str
    text: str
    links: tuple[str, ...]


def question_key(question: OpenQuestion) -> str:
    if question.source == "user" and question.source_question_id is not None:
        return f"q:F{question.source_question_id}"
    return f"q:{same_question(question.text)}"


def option_key(option: Mapping[str, object]) -> str:
    identifier = str(option["id"])
    return identifier if identifier.startswith("F") else same_question(str(option["text"]))


def options_of(question: OpenQuestion, fragments: Mapping[int, LabeledFragment],
               found: Mapping[str, list[Proposal]]) -> list[dict[str, str]]:
    """Варианты вопроса: из текста группы и найденные советом."""
    return ([{"id": f"F{i}", "text": fragments[i].text} for i in question.proposal_ids
             if i in fragments]
            + [{"id": p.id, "text": p.text} for p in found.get(question.id, [])])


def because(decision: str, rationale: str | None, words: Mapping[str, str]) -> str:
    """ADR одной фразой: «решение, потому что обоснование». Без обоснования — само решение."""
    decision = " ".join(decision.split())
    if not rationale or not rationale.strip():
        return decision
    reason = " ".join(rationale.split())
    if reason[:1].isupper() and not reason[1:2].isupper():
        reason = reason[:1].lower() + reason[1:]
    return f"{decision.rstrip('.!')}, {words['because']} {reason}"


def outcome_text(title: str, behavior: str, criteria: Sequence[str],
                 issues: Sequence[IssueNumber], words: Mapping[str, str]) -> str:
    lines = [title.strip(), "", behavior.strip()]
    if criteria:
        lines += ["", f"{words['criteria']}:", *(f"- {item}" for item in criteria)]
    if issues:
        lines += ["", f"{words['issues']}:", *(f"- {issue.id}: {issue.title}" for issue in issues)]
    return "\n".join(lines)


def parts_of(stream: Stream, fragments: Mapping[int, LabeledFragment],
             numbers: Sequence[IssueNumber], catalog: Catalog,
             words: Mapping[str, str]) -> tuple[list[Part], list[str]]:
    """Части потока в порядке заметок: идея, вопросы, варианты, решения, итоги. И что не
    выгружается — с причиной."""
    found = {options.question_id: options.proposals
             for options in (stream.proposals.options if stream.proposals else [])}
    decisions = {decision.question_id: decision for decision in stream.decisions or []}
    questions: list[Part] = []
    proposals: list[Part] = []
    adrs: list[Part] = []
    adr_of: dict[str, str] = {}          # ADR-n потока → ключ части
    external: set[str] = set()           # решения вопросов, что растут из прошлых решений
    for n, question in enumerate(stream.scope or [], 1):
        asked, offered, adr = question_parts(question, options_of(question, fragments, found),
                                             decisions.get(question.id), catalog, words)
        questions.append(asked)
        proposals += offered
        if adr is not None:
            adrs.append(adr)
            adr_of[f"ADR-{n}"] = adr.key
            if asked.links != ("idea",):
                external.add(adr.key)
    outcomes, skipped = outcome_parts(stream, numbers, adr_of, external, words)
    return [Part("idea", "idea", stream.idea.text, ()), *questions, *proposals, *adrs,
            *outcomes], skipped


def question_parts(question: OpenQuestion, options: list[dict[str, str]],
                   decision: Decision | None, catalog: Catalog,
                   words: Mapping[str, str]) -> tuple[Part, list[Part], Part | None]:
    """Вопрос, его варианты и решение, если оно принято. Вопрос, который пересматривает
    прошлое решение, растёт из того ADR, а не из идеи."""
    key = question_key(question)
    revisited = catalog.notes.get(question.revisits or "")
    links = (revisited.id,) if revisited is not None and revisited.type == "adr" else ("idea",)
    asked = Part(key, "open_question", question.note or question.text, links)
    offered: list[Part] = []
    adr = None
    for option in options:
        option_part = f"p:{key[2:]}:{option_key(option)}"
        offered.append(Part(option_part, "proposal", option["text"], (key,)))
        if decision is not None and decision.proposal == option["id"]:
            adr = Part(f"a:{key[2:]}:{option_key(option)}", "adr",
                       because(option["text"], decision.rationale, words), (option_part,))
    return asked, offered, adr


def outcome_parts(stream: Stream, numbers: Sequence[IssueNumber], adr_of: Mapping[str, str],
                  external: set[str], words: Mapping[str, str]) -> tuple[list[Part], list[str]]:
    """Итоги со своими задачами. Итог ссылается только на решения своей идеи: без них он не
    выгружается."""
    by_outcome: dict[str, list[IssueNumber]] = {}
    for number in numbers:
        for outcome_id in number.outcome_ids:
            by_outcome.setdefault(outcome_id, []).append(number)
    parts: list[Part] = []
    skipped: list[str] = []
    for outcome in stream.outcomes.outcomes if stream.outcomes else []:
        linked = [adr_of[name] for name in outcome.adr_ids if name in adr_of]
        own = [key for key in linked if key not in external]
        if len(own) < len(linked):
            skipped.append(f"{outcome.id}: решения, которые пересматривают прошлые, в итоге не "
                           "связаны — итог стоит на решениях своей идеи")
        if not own:
            skipped.append(f"{outcome.id} «{outcome.title}» не выгружается: у него нет решений "
                           "этой идеи, а итог ссылается хотя бы на одно")
            continue
        text = outcome_text(outcome.title, outcome.behavior, outcome.acceptance_criteria,
                            by_outcome.get(outcome.id, []), words)
        parts.append(Part(f"o:{same_question(outcome.title)}", "outcome", text,
                          tuple(dict.fromkeys(own))))
    return parts, skipped


def numbered_issues(stream: Stream, catalog: Catalog,
                    previous: NotesExport | None) -> list[IssueNumber]:
    """Номера задач на весь проект: прежняя задача (по названию) — прежний номер, новая —
    следующий после самого большого в каталоге и прежней выгрузке."""
    known = {number.key: number.id for number in previous.numbers} if previous else {}
    used = [int(found.group(1)) for note in catalog.notes.values()
            for issue in issues_in(note.body) if (found := ISSUE.fullmatch(issue))]
    used += [int(found.group(1)) for number in known.values()
             if (found := ISSUE.fullmatch(number))]
    top = max(used, default=0)
    numbers: list[IssueNumber] = []
    for issue in stream.issues.issues if stream.issues else []:
        key = f"i:{same_question(issue.title)}"
        if key in known:
            identifier = known[key]
        else:
            top += 1
            identifier = f"ISS-{top:04d}"
        numbers.append(IssueNumber(key=key, id=identifier, issue_id=issue.id, title=issue.title,
                                   outcome_ids=list(issue.outcome_ids)))
    return numbers


def digest_of(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def drafted(stream: Stream, fragments: Mapping[int, LabeledFragment], catalog: Catalog,
            root: Path, previous: NotesExport | None,
            words: Mapping[str, str]) -> tuple[list[NotePlan], list[VanishedNote],
                                               list[IssueNumber], list[str]]:
    """Черновик выгрузки: заметки с номерами, текстом и тем, что с ними будет; исчезнувшие;
    номера задач; что не выгружается."""
    numbers = numbered_issues(stream, catalog, previous)
    parts, skipped = parts_of(stream, fragments, numbers, catalog, words)
    before = {note.key: note for note in previous.notes} if previous else {}
    ids: dict[str, str] = {}
    for part in parts:
        old = before.get(part.key)
        held = catalog.notes.get(old.id) if old else None
        if old and old.type == part.type and (held is None or held.type == part.type):
            ids[part.key] = old.id
    for part in parts:
        if part.key not in ids:
            ids[part.key] = catalog.next_id(part.type, taken=ids.values())
    notes = [planned(part, ids, before.get(part.key), catalog, root) for part in parts]
    ours = {note.id for note in notes} | {note.id for note in before.values()}
    vanished = [VanishedNote(id=old.id, type=old.type, text=catalog.notes[old.id].body,
                             linked_from=sorted(note.id for note in catalog.notes.values()
                                                if old.id in note.links and note.id not in ours))
                for key, old in before.items()
                if key not in ids and old.id in catalog.notes]
    return notes, vanished, numbers, skipped


def planned(part: Part, ids: Mapping[str, str], old: ExportedNote | None, catalog: Catalog,
            root: Path) -> NotePlan:
    note_id = ids[part.key]
    links = [ids.get(link, link) for link in part.links]
    text = old.written if old and old.generated == part.text else part.text
    plan = NotePlan(key=part.key, id=note_id, type=part.type, text=text, generated=part.text,
                    links=links, action="create")
    return settled(plan, old, catalog, root)


def settled(plan: NotePlan, old: ExportedNote | None, catalog: Catalog,
            root: Path) -> NotePlan:
    """Что будет с заметкой при записи — по тому, что лежит в каталоге сейчас."""
    held = catalog.notes.get(plan.id)
    if held is None:
        return plan.model_copy(update={"action": "create", "current": None})
    path = path_of(root, held)
    if old is not None and digest_of(path) != old.digest:
        return plan.model_copy(update={"action": "edited", "current": held.body})
    if held.body == plan.text.strip() and list(held.links) == plan.links:
        return plan.model_copy(update={"action": "same", "current": None})
    return plan.model_copy(update={"action": "update", "current": held.body})


def written(notes: Sequence[NotePlan], vanished: Sequence[VanishedNote],
            edits: Mapping[str, str], delete: Sequence[str], root: Path,
            previous: NotesExport | None) -> list[ExportedNote]:
    """Записывает подтверждённое: заметки с правками человека (edits — по ключу), удаляет
    отмеченные исчезнувшие. Файлы, правленные руками, — не трогает. Вернёт, что выгружено."""
    gone = deletable(vanished, delete)
    before = {note.key: note for note in previous.notes} if previous else {}
    exported: list[ExportedNote] = []
    for plan in notes:
        path = path_of(root, Note(plan.id, plan.type, ""))
        if plan.action == "edited":
            old = before[plan.key]
            exported.append(old.model_copy(update={"generated": plan.generated}))
            continue
        text = edits.get(plan.key, plan.text).strip()
        if not text:
            raise NotesError(f"У заметки {plan.id} пустой текст")
        note = Note(plan.id, plan.type, text, tuple(plan.links))
        if plan.action != "same" or text != plan.text.strip():
            write_file(path, rendered(note))
        exported.append(ExportedNote(key=plan.key, id=plan.id, type=plan.type,
                                     generated=plan.generated, written=text, links=plan.links,
                                     digest=digest_of(path)))
    for note_id in delete:
        path_of(root, Note(note_id, gone[note_id].type, "")).unlink(missing_ok=True)
    return exported


def deletable(vanished: Sequence[VanishedNote], delete: Sequence[str]) -> dict[str, VanishedNote]:
    """Удалить можно только исчезнувшую заметку, на которую ничего вне потока не ссылается."""
    gone = {note.id: note for note in vanished}
    for note_id in delete:
        if note_id not in gone:
            raise NotesError(f"Заметки {note_id} нет среди исчезнувших")
        if gone[note_id].linked_from:
            raise NotesError(f"{note_id} не удалить: на неё ссылаются "
                             f"{', '.join(gone[note_id].linked_from)}")
    return gone


def write_file(path: Path, text: str) -> None:
    """Через временный файл и подмену: оборванная запись заметку не испортит."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".md.part")
    try:
        part.write_text(text, encoding="utf-8", newline="\n")
        part.replace(path)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise NotesError(f"Заметку {path.name} не записать: {exc.strerror or exc}") from exc
