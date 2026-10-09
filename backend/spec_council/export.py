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
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
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
from .notes import Catalog, Note, NotesError, declared_issues, issues_in, path_of, rendered
from .questions import same_question
from .slicing import BadAnswer

# Связки в тексте заметок — на языке работы; перевод, если нужен, — потом, целиком.
WORDS = {
    "russian": {"because": "потому что", "criteria": "Критерии готовности", "issues": "Задачи"},
    "english": {"because": "because", "criteria": "Acceptance criteria", "issues": "Issues"},
}
ALIASES = {"русский": "russian", "ru": "russian", "en": "english", "английский": "english"}
ISSUE = re.compile(r"ISS-(\d+)")
# Между названием итога (задачи) и его сутью в ключе. same_question такого знака не оставит:
# для split он пробел.
SEP = "\x1f"
NUMBER = re.compile(r"\b(?:IDEA|OQ|PRO|ADR|OUT|ISS)-\d+\b")


def words_for(language: str) -> dict[str, str]:
    """Связки на языке работы; язык, которого совет не знает, — по-английски: их доведёт
    перевод (knows_words)."""
    return WORDS.get(word_language(language), WORDS["english"])


def knows_words(language: str) -> bool:
    return word_language(language) in WORDS


def word_language(language: str) -> str:
    name = language.strip().lower()
    return ALIASES.get(name, name)


def keyed(bases: Sequence[str], details: Sequence[str], taken: set[str]) -> list[str]:
    """Ключи итогов и задач: название и суть — поведение итога, история задачи. Ключ держится за
    суть, а не за место в списке и не за то, есть ли у итога тёзка: модель, отдавшая их в другом
    порядке, или второй итог с тем же названием не поменяют номера. Поправили только суть —
    прежнюю заметку найдёт matched."""
    return [unique(f"{base}{SEP}{detail}", taken)
            for base, detail in zip(bases, details, strict=True)]


def title_of(key: str) -> str:
    return key.split(SEP, 1)[0]


def matched(keys: Sequence[str], previous: Iterable[str]) -> dict[str, str]:
    """Какую часть прошлой выгрузки продолжает каждая нынешняя: с тем же ключом — её. Нет такой
    у итога или задачи — ту, что с тем же названием, если такое название и среди нынешних без
    пары, и среди прежних без пары одно: поменялась только суть, а итог тот же."""
    before = list(previous)
    known = set(before)
    found = {key: key for key in keys if key in known}
    rest = [key for key in before if key not in found]
    loose = [key for key in keys if key not in found]
    for key in loose:
        if SEP not in key:
            continue
        now = [other for other in loose if title_of(other) == title_of(key)]
        then = [other for other in rest if title_of(other) == title_of(key)]
        if len(now) == 1 and len(then) == 1:
            found[key] = then[0]
    return found


def unique(key: str, taken: set[str]) -> str:
    """Ключ части — один на часть: две с одной формулировкой (два итога с одним названием)
    иначе легли бы одной заметкой. У второй — «#2», у третьей — «#3»."""
    found, n = key, 1
    while found in taken:
        n += 1
        found = f"{key}#{n}"
    taken.add(found)
    return found


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


def parts_of(stream: Stream, fragments: Mapping[int, LabeledFragment], catalog: Catalog,
             words: Mapping[str, str],
             number: Callable[[set[str]], list[IssueNumber]]
             ) -> tuple[list[Part], list[str], list[IssueNumber]]:
    """Части потока в порядке заметок: идея, вопросы, варианты, решения, итоги. И что не
    выгружается — с причиной, и номера задач: number раздаёт их задачам тех итогов, что лягут в
    каталог."""
    found = {options.question_id: options.proposals
             for options in (stream.proposals.options if stream.proposals else [])}
    decisions = {decision.question_id: decision for decision in stream.decisions or []}
    questions: list[Part] = []
    proposals: list[Part] = []
    adrs: list[Part] = []
    adr_of: dict[str, str] = {}          # ADR-n потока → ключ части
    external: set[str] = set()           # решения вопросов, что растут из прошлых решений
    taken: set[str] = set()
    for n, question in enumerate(stream.scope or [], 1):
        asked, offered, adr = question_parts(question, options_of(question, fragments, found),
                                             decisions.get(question.id), catalog, words, taken)
        questions.append(asked)
        proposals += offered
        if adr is not None:
            adrs.append(adr)
            adr_of[f"ADR-{n}"] = adr.key
            if asked.links != ("idea",):
                external.add(adr.key)
    exported = {outcome.id for outcome in (stream.outcomes.outcomes if stream.outcomes else [])
                if any(adr_of[name] not in external for name in outcome.adr_ids
                       if name in adr_of)}
    numbers = number(exported)
    outcomes, skipped = outcome_parts(stream, numbers, adr_of, external, words, taken)
    numbered = {n.issue_id for n in numbers}
    skipped += [f"{issue.id} «{issue.title}» без номера: её итоги не выгружаются, и номеру "
                "негде закрепиться в каталоге"
                for issue in (stream.issues.issues if stream.issues else [])
                if issue.id not in numbered]
    return [Part("idea", "idea", stream.idea.text, ()), *questions, *proposals, *adrs,
            *outcomes], skipped, numbers


def question_parts(question: OpenQuestion, options: list[dict[str, str]],
                   decision: Decision | None, catalog: Catalog, words: Mapping[str, str],
                   taken: set[str]) -> tuple[Part, list[Part], Part | None]:
    """Вопрос, его варианты и решение, если оно принято. Вопрос, который пересматривает
    прошлое решение, растёт из того ADR, а не из идеи; ADR из каталога пропал — выгружать
    нельзя: вопрос и его решение молча легли бы в цепочку новой идеи."""
    key = unique(question_key(question), taken)
    revisited = catalog.notes.get(question.revisits or "")
    if question.revisits and (revisited is None or revisited.type != "adr"):
        raise NotesError(f"{question.id} пересматривает {question.revisits}, а такого решения в "
                         "каталоге заметок уже нет: верните заметку или отберите решения проекта "
                         "заново")
    links = (revisited.id,) if revisited is not None else ("idea",)
    asked = Part(key, "open_question", question.note or question.text, links)
    offered: list[Part] = []
    adr = None
    for option in options:
        option_part = unique(f"p:{key[2:]}:{option_key(option)}", taken)
        offered.append(Part(option_part, "proposal", option["text"], (key,)))
        if decision is not None and decision.proposal == option["id"]:
            adr = Part(f"a:{option_part[2:]}", "adr",
                       because(option["text"], decision.rationale, words), (option_part,))
    return asked, offered, adr


def outcome_parts(stream: Stream, numbers: Sequence[IssueNumber], adr_of: Mapping[str, str],
                  external: set[str], words: Mapping[str, str],
                  taken: set[str]) -> tuple[list[Part], list[str]]:
    """Итоги со своими задачами. Итог ссылается только на решения своей идеи: без них он не
    выгружается."""
    by_outcome: dict[str, list[IssueNumber]] = {}
    for number in numbers:
        for outcome_id in number.outcome_ids:
            by_outcome.setdefault(outcome_id, []).append(number)
    parts: list[Part] = []
    skipped: list[str] = []
    outcomes = stream.outcomes.outcomes if stream.outcomes else []
    keys = keyed([f"o:{same_question(outcome.title)}" for outcome in outcomes],
                 [same_question(outcome.behavior) for outcome in outcomes], taken)
    for outcome, key in zip(outcomes, keys, strict=True):
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
        parts.append(Part(key, "outcome", text, tuple(dict.fromkeys(own))))
    return parts, skipped


def numbered_issues(stream: Stream, catalog: Catalog, previous: NotesExport | None,
                    exported: set[str] | None = None) -> list[IssueNumber]:
    """Номера задач на весь проект: прежняя задача (по названию) — прежний номер, новая —
    следующий после самого большого в каталоге и прежней выгрузке. Прежний номер, которого в
    каталоге уже нет (строку задачи убрали руками), мог занять другой поток — тогда новый.
    exported — итоги, что лягут в каталог: задача без них номера не получает."""
    known = {number.key: number.id for number in previous.numbers} if previous else {}
    # Занятым считается и номер, который лишь упомянут: новая задача под ним сделала бы
    # упоминание ссылкой на себя.
    ours = {note.id for note in previous.notes} if previous else set()
    foreign = {issue for note in catalog.notes.values() if note.id not in ours
               for issue in issues_in(note.body)}
    used = [int(found.group(1)) for note in catalog.notes.values()
            for issue in issues_in(note.body) if (found := ISSUE.fullmatch(issue))]
    used += [int(found.group(1)) for number in known.values()
             if (found := ISSUE.fullmatch(number))]
    top = max(used, default=0)
    numbers: list[IssueNumber] = []
    issues = stream.issues.issues if stream.issues else []
    keys = keyed([f"i:{same_question(issue.title)}" for issue in issues],
                 [same_question(issue.user_story) for issue in issues], set())
    alias = matched(keys, known)
    for issue, key in zip(issues, keys, strict=True):
        # Номер закрепляет строка задачи в заметке итога: итоги не выгружаются — не раздаём,
        # иначе другой поток выдал бы тот же номер.
        if exported is not None and not set(issue.outcome_ids) & exported:
            continue
        was = alias.get(key)
        if was is not None and known[was] not in foreign:
            identifier = known[was]
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
            root: Path, previous: NotesExport | None, words: Mapping[str, str],
            language: str) -> tuple[list[NotePlan], list[VanishedNote], list[IssueNumber],
                                    list[str]]:
    """Черновик выгрузки: заметки с номерами, текстом и тем, что с ними будет; исчезнувшие;
    номера задач; что не выгружается. language — язык заметок: не тот, что у прошлой выгрузки, —
    прежние тексты не берутся, их напишет перевод заново (файлы, правленные руками, — нет)."""
    parts, skipped, numbers = parts_of(
        stream, fragments, catalog, words,
        lambda exported: numbered_issues(stream, catalog, previous, exported))
    before = {note.key: note for note in previous.notes} if previous else {}
    alias = matched([part.key for part in parts], before)
    olds = {key: before[was] for key, was in alias.items()}
    reuse = previous is not None and previous.language == language
    ids: dict[str, str] = {}
    for part in parts:
        old = olds.get(part.key)
        held = catalog.notes.get(old.id) if old else None
        if old and old.type == part.type and (held is None or held.type == part.type):
            ids[part.key] = old.id
    for part in parts:
        if part.key not in ids:
            ids[part.key] = catalog.next_id(part.type, taken=ids.values())
    notes = [planned(part, ids, olds.get(part.key), alias.get(part.key), catalog, root, reuse)
             for part in parts]
    ours = {note.id for note in notes} | {note.id for note in before.values()}
    claimed = set(alias.values())
    vanished = [VanishedNote(id=old.id, type=old.type, text=catalog.notes[old.id].body,
                             linked_from=sorted(note.id for note in catalog.notes.values()
                                                if old.id in note.links and note.id not in ours))
                for key, old in before.items()
                if key not in claimed and old.id in catalog.notes]
    return notes, vanished, numbers, skipped


def planned(part: Part, ids: Mapping[str, str], old: ExportedNote | None, was: str | None,
            catalog: Catalog, root: Path, reuse: bool) -> NotePlan:
    note_id = ids[part.key]
    links = [ids.get(link, link) for link in part.links]
    text = old.written if old and reuse and old.generated == part.text else part.text
    plan = NotePlan(key=part.key, id=note_id, type=part.type, text=text, generated=part.text,
                    links=links, action="create", was=was)
    return settled(plan, old, catalog, root)


def previous_of(plan: NotePlan, before: Mapping[str, ExportedNote]) -> ExportedNote | None:
    """Прежняя выгрузка заметки, которую продолжает plan."""
    return before.get(plan.was) if plan.was else None


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
            previous: NotesExport | None, catalog: Catalog,
            keep: Callable[[list[ExportedNote]], None] | None = None) -> list[ExportedNote]:
    """Записывает подтверждённое: заметки с правками человека (edits — по ключу), удаляет
    отмеченные исчезнувшие. Файлы, правленные руками, — не трогает. Вернёт, что выгружено, —
    и исчезнувшие, что человек оставил в каталоге: они всё ещё потока.

    Сначала пустой текст и временные файлы, потом подмена и удаление одним шагом с откатом
    (committed), потом keep — запись о выгрузке. Отказ на любом шаге, и в keep тоже, вернёт
    каталог как был: файлы и запись о них не разойдутся. Заметка из каталога — там, где лежит."""

    def where(note_id: str, kind: str) -> Path:
        return path_of(root, catalog.notes.get(note_id) or Note(note_id, kind, ""))

    gone = deletable(vanished, delete)
    before = {note.key: note for note in previous.notes} if previous else {}
    texts = {plan.key: edits.get(plan.key, plan.text).strip() for plan in notes
             if plan.action != "edited"}
    empty = [plan.id for plan in notes if texts.get(plan.key) == ""]
    if empty:
        raise NotesError(f"У заметки {empty[0]} пустой текст")
    changed = [plan for plan in notes if plan.action != "edited"
               and (plan.action != "same" or texts[plan.key] != plan.text.strip())]
    staged: list[tuple[Path, Path]] = []
    try:
        for plan in changed:
            path = where(plan.id, plan.type)
            note = Note(plan.id, plan.type, texts[plan.key], tuple(plan.links))
            staged.append((staged_file(path, rendered(note)), path))
    except NotesError:
        for part, _ in staged:
            part.unlink(missing_ok=True)
        raise
    commit = committed(staged, [where(note_id, gone[note_id].type) for note_id in delete])
    try:
        exported: list[ExportedNote] = []
        for plan in notes:
            if plan.action == "edited":
                # Файл не тронут — и база та же, из которой его выгрузили: откатят правку —
                # новый текст совета предложится снова.
                exported.append(before[plan.was or plan.key].model_copy(update={"key": plan.key}))
                continue
            exported.append(ExportedNote(key=plan.key, id=plan.id, type=plan.type,
                                         generated=plan.generated, written=texts[plan.key],
                                         links=plan.links,
                                         digest=digest_of(where(plan.id, plan.type))))
        exported += [old.model_copy(update={"kept": True}) for old in before.values()
                     if old.id in gone and old.id not in delete]
        if keep is not None:
            keep(exported)
    except BaseException:
        commit.undo()
        raise
    commit.finish()
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


def graph_problems(catalog: Catalog, notes: Sequence[NotePlan], vanished: Sequence[VanishedNote],
                   edits: Mapping[str, str], delete: Sequence[str]) -> None:
    """Граф после записи — по правилам: проверяем до того, как трогать файлы. Поломки, что
    были в каталоге и до выгрузки, её не держат; держат поломки заметок потока и новые — например,
    исчезнувший итог остался, а его ADR удаляют."""
    deletable(vanished, delete)
    after = dict(catalog.notes)
    for plan in notes:
        if plan.action != "edited":
            after[plan.id] = Note(plan.id, plan.type, edits.get(plan.key, plan.text),
                                  tuple(plan.links))
    for note_id in delete:
        after.pop(note_id, None)
    ours = {plan.id for plan in notes}
    before = set(catalog.problems())
    found = [problem for problem in Catalog(after).problems()
             if problem.split(":", 1)[0] in ours or problem not in before]
    if found:
        raise NotesError("Граф заметок вышел бы не по правилам: " + "; ".join(found))


def untranslated(notes: Sequence[NotePlan]) -> dict[str, str]:
    """Что переводить на язык документации: текст, который совет написал заново. Прежний
    текст (совет написал бы то же) уже переведён в прошлый раз и, может быть, поправлен."""
    return {note.key: note.text for note in notes
            if note.text == note.generated and note.action != "edited"}


def translations(data: dict, sources: Mapping[str, str]) -> dict[str, str]:
    """Перевод заметок из ответа: каждая — и ровно с теми же номерами заметок и задач внутри.
    Лишний номер тоже негоден: ISS-… в итоге — задача, по нему считают след и новые номера."""
    items = data.get("notes")
    if not isinstance(items, list):
        raise BadAnswer("нет списка notes")
    found = {item["key"]: item["text"].strip() for item in items
             if isinstance(item, dict) and item.get("key") in sources
             and isinstance(item.get("text"), str) and item["text"].strip()}
    missing = [key for key in sources if key not in found]
    if missing:
        raise BadAnswer(f"нет перевода заметок: {', '.join(missing[:5])}")
    for key, text in found.items():
        source, translated = set(NUMBER.findall(sources[key])), set(NUMBER.findall(text))
        if source - translated:
            raise BadAnswer(f"в переводе {key} потеряны номера "
                            f"{', '.join(sorted(source - translated))}")
        if translated - source:
            raise BadAnswer(f"в переводе {key} лишние номера "
                            f"{', '.join(sorted(translated - source))}")
        if declared_issues(sources[key]) != declared_issues(text):
            raise BadAnswer(f"в переводе {key} строки задач не те: каждая — «- ISS-…: название», "
                            "как в исходном тексте")
    return found


def staged_file(path: Path, text: str) -> Path:
    """Заметка во временном файле рядом: на её место его поставит committed."""
    part = path.with_suffix(".md.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise NotesError(f"Заметку {path.name} не записать: {exc.strerror or exc}") from exc
    return part


@dataclass
class Commit:
    """Подмена, которая уже сделана, но ещё не окончательна: finish убирает .bak, undo
    возвращает всё как было."""

    staged: Sequence[tuple[Path, Path]]
    placed: list[Path]
    backups: list[tuple[Path, Path]]

    def finish(self) -> None:
        for _, backup in self.backups:
            with suppress(OSError):
                backup.unlink()

    def undo(self) -> None:
        rolled_back(self.staged, self.placed, self.backups)


def committed(staged: Sequence[tuple[Path, Path]], deleted: Sequence[Path]) -> Commit:
    """Подмена заметок временными файлами и удаление — одним шагом, который откатывается:
    прежние файлы сначала уходят в .bak, временные встают на их место; .bak убирает
    Commit.finish. Не вышло на любом шаге — всё назад, каталог как был. Каталог читает только
    .md: .part и .bak, если их не убрать, в заметки не попадут."""
    backups: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    try:
        for path, verb in [*((path, "записать") for _, path in staged),
                           *((path, "удалить") for path in deleted)]:
            if path.exists():
                backup = path.with_suffix(".md.bak")
                moved(path, backup, path, verb)
                backups.append((path, backup))
        for part, path in staged:
            moved(part, path, path, "записать")
            placed.append(path)
    except NotesError:
        rolled_back(staged, placed, backups)
        raise
    return Commit(staged, placed, backups)


def moved(source: Path, target: Path, note: Path, verb: str) -> None:
    try:
        source.replace(target)
    except OSError as exc:
        raise NotesError(f"Заметку {note.name} не {verb}: {exc.strerror or exc}") from exc


def rolled_back(staged: Sequence[tuple[Path, Path]], placed: Sequence[Path],
                backups: Sequence[tuple[Path, Path]]) -> None:
    """Всё назад, насколько выйдет: вставшее — убрать, прежнее — из .bak, временное — стереть."""
    for path in placed:
        with suppress(OSError):
            path.unlink()
    for path, backup in backups:
        with suppress(OSError):
            backup.replace(path)
    for part, _ in staged:
        with suppress(OSError):
            part.unlink(missing_ok=True)
