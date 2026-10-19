"""Выгрузка плана задач совета в папку задач проекта: файл на задачу (issue_files.py) с номером
на весь проект (ISS-0012) — его пишут в финальный коммит задачи. Во frontmatter — итог задачи,
её решения и задачи, после которых её делать (номерами заметок и задач), в теле — кому и зачем,
где менять и что там сейчас, что сделать, итог и решения с их текстом, что соблюдать, риски, что
неясно в реализации, задачи до неё и строка о номере для коммита.

Связь с итогами односторонняя: файл задачи называет свой итог, а заметка итога задач не
перечисляет. Выгрузка — как у потока (export.py): черновик, перевод, если язык заметок другой,
и запись подтверждённого одной сделкой. Повторная выгрузка узнаёт свои задачи по названию и
сути: прежняя задача — прежний номер и файл, новая — следующий номер после самого большого,
какой есть в каталоге заметок, прежней выгрузке и папке задач.

Задачу везде зовут одним названием — заголовком её файла, и после перевода тоже (aligned).
Номера потока (Q1, F3…) в тексте задачи — номерами заметок, как и в самих заметках.
"""

import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

from . import issue_files
from .export import ISSUE, Part, Shelf, keyed, matched, planned
from .models import (
    Issue,
    IssueNumber,
    LabeledFragment,
    NotePlan,
    TaskPlan,
    TasksExport,
    VanishedNote,
)
from .notes import Catalog, NotesError, issues_in
from .questions import same_question
from .tasks import Names, relabeled

# Название задачи — заголовок её файла: первая строка «# …».
TITLE = re.compile(r"^# +(.+?)[ \t]*$", re.MULTILINE)


def numbered(issues: Sequence[Issue], catalog: Catalog, previous: TasksExport | None,
             reserved: Collection[str] = (), files: Collection[str] = (),
             occupied: Collection[str] = ()) -> list[IssueNumber]:
    """Номера задач на весь проект: прежняя задача (по названию и сути) — прежний номер, новая —
    следующий после самого большого в каталоге заметок, прежней выгрузке и папке задач (files —
    номера её файлов: новая задача не ляжет в чужой файл). Прежний номер, который занял другой
    совет (reserved), под ним в папке лежит файл другой задачи (occupied) или его упоминает
    каталог, хотя прежняя выгрузка его не раздавала, — уже не наш: тогда новый. Свой номер,
    упомянутый в заметке, — всё ещё свой: заметка на эту задачу и ссылается."""
    known = {number.key: number.id for number in previous.numbers} if previous else {}
    ours = set(known.values())
    foreign = {issue for note in catalog.notes.values() for issue in issues_in(note.body)}
    foreign = (foreign - ours) | set(reserved) | set(occupied)
    used = [int(found.group(1)) for note in catalog.notes.values()
            for issue in issues_in(note.body) if (found := ISSUE.fullmatch(issue))]
    used += [int(found.group(1)) for number in (*known.values(), *reserved, *files, *occupied)
             if (found := ISSUE.fullmatch(number))]
    top = max(used, default=0)
    keys = keyed([f"i:{same_question(issue.title)}" for issue in issues],
                 [same_question(issue.user_story) for issue in issues], set())
    alias = matched(keys, known)
    numbers: list[IssueNumber] = []
    for issue, key in zip(issues, keys, strict=True):
        was = alias.get(key)
        if was is not None and known[was] not in foreign:
            identifier = known[was]
        else:
            top += 1
            identifier = f"ISS-{top:04d}"
        numbers.append(IssueNumber(key=key, id=identifier, issue_id=issue.id, title=issue.title,
                                   outcome_ids=[issue.outcome_id]))
    return numbers


def line(text: str) -> str:
    """Пункт списка — одной строкой: перенос внутри разорвал бы список."""
    return " ".join(text.split())


def issue_title(issue: Issue, names: Mapping[str, str],
                renumber: Callable[[str], str] | None = None) -> str:
    """Название задачи, как оно ляжет и в её файл, и в строку «- ISS-…: …» задач, что ждут её."""
    title = relabeled(issue.title, names)
    return line(renumber(title) if renumber else title)


def issue_text(issue: Issue, number: str, outcome: tuple[str, str],
               adrs: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]],
               keep: Sequence[str], risks: Sequence[str], words: Mapping[str, str],
               names: Mapping[str, str] | None = None,
               renumber: Callable[[str], str] | None = None) -> str:
    """Задача для coding agent: кому и зачем, где менять и что там сейчас, что сделать, на чём
    стоит, что соблюдать, что неясно и после каких задач (after — с названиями из issue_title), —
    и номер для финального коммита. Задачи плана текст называет I-n, а агент найдёт их по
    номерам на весь проект: names. Номера потока своего итога — номерами заметок: renumber (в
    тексте решений — уже: decisions_of)."""
    names = names or {}

    def fixed(value: str) -> str:
        return renumber(value) if renumber else value

    def named(value: str) -> str:
        return fixed(relabeled(value, names))

    lines = [f"# {issue_title(issue, names, renumber)}", "", named(issue.user_story.strip())]

    def section(title: str, items: Iterable[str]) -> None:
        items = list(items)
        if items:
            lines.extend(["", f"## {title}", *items])

    now = issue.current_state.strip()
    section(words["entry"], (f"- {line(item)}" for item in issue.main_entry_points))
    section(words["now"], [named(now)] if now else [])
    section(words["scope"], (f"- {line(named(item))}" for item in issue.scope))
    section(words["outcomes"], [f"- {outcome[0]}: {line(fixed(outcome[1]))}"])
    section(words["decisions"], (f"- {name}: {line(text)}" for name, text in adrs))
    section(words["keep"], (f"- {line(text)}" for text in keep))
    section(words["risks"], (f"- {line(text)}" for text in risks))
    section(words["open"], (f"- {line(named(item))}" for item in issue.open_questions))
    section(words["after"], (f"- {name}: {line(text)}" for name, text in after))
    lines += ["", words["commit"].format(id=number)]
    return "\n".join(lines)


def decisions_of(issue: Issue, catalog: Catalog, names: Names | None,
                 quote: str) -> list[tuple[str, str]]:
    """Решения задачи с текстом из каталога. Номера потока — номерами заметок только в решениях
    её потока: прошлое решение проекта называет свои вопросы своими номерами."""
    return [(name, names(body, quote) if names is not None and names.owns(name) else body)
            for name in issue.adr_ids if name in catalog.notes
            for body in [catalog.notes[name].body.strip()]]


def title_of(catalog: Catalog, note_id: str) -> str:
    """Заметка коротко — её первая строка: у итога это название."""
    note = catalog.notes.get(note_id)
    return note.body.strip().split("\n", 1)[0] if note is not None else ""


def drafted_tasks(plan: TaskPlan, fragments: Mapping[int, LabeledFragment], shelf: Shelf,
                  previous: TasksExport | None, words: Mapping[str, str], language: str,
                  reserved: Collection[str] = (), streams: Mapping[str, Names] | None = None
                  ) -> tuple[list[NotePlan], list[VanishedNote], list[IssueNumber]]:
    """Черновик выгрузки плана: файл на каждую задачу с номером, текстом и тем, что с ним будет;
    исчезнувшие файлы прежней выгрузки; номера задач. language — язык заметок: не тот, что у
    прошлой выгрузки, — прежние тексты не берутся, их напишет перевод заново (файлы, правленные
    руками, — нет). streams — номера потока у каждого итога (по номеру заметки итога): ими
    файл задачи называет части потока своего итога."""
    catalog = shelf.catalog
    numbers = numbered(plan.issues, catalog, previous, reserved, shelf.files,
                       issue_files.occupied(shelf.files))
    by_issue = {number.issue_id: number for number in numbers}
    filed = {note.id: note for note in previous.notes} if previous else {}
    reuse = previous is not None and previous.language == language
    # Итог и решения задачи — заметки каталога: какую с тех пор удалили, на ту файл задачи
    # сослался бы впустую.
    gone = sorted({name for issue in plan.issues for name in (issue.outcome_id, *issue.adr_ids)
                   if name not in catalog.notes})
    if gone:
        raise NotesError(f"В каталоге заметок больше нет {', '.join(gone)}, а план на них стоит: "
                         "верните заметки или выгрузите потоки заново и спланируйте снова")
    labels = {name: number.id for name, number in by_issue.items()}

    def renumber(issue: Issue) -> Callable[[str], str] | None:
        names = (streams or {}).get(issue.outcome_id)
        return (lambda text: names(text, words["quote"])) if names else None

    titles = {issue.id: issue_title(issue, labels, renumber(issue)) for issue in plan.issues}
    notes: list[NotePlan] = []
    for issue in plan.issues:
        number = by_issue[issue.id]
        outcome = (issue.outcome_id, title_of(catalog, issue.outcome_id))
        adrs = decisions_of(issue, catalog, (streams or {}).get(issue.outcome_id),
                            words["quote"])
        after = [(by_issue[name].id, titles[name]) for name in issue.depends_on
                 if name in by_issue]
        text = issue_text(issue, number.id, outcome, adrs, after,
                          [fragments[i].text for i in issue.constraint_ids if i in fragments],
                          [fragments[i].text for i in issue.risk_ids if i in fragments], words,
                          labels, renumber(issue))
        links = tuple(dict.fromkeys(name for name, _ in (outcome, *adrs, *after)))
        old = filed.get(number.id)
        notes.append(planned(Part(number.key, "issue", text, links), {number.key: number.id},
                             old, old.key if old else None, shelf, reuse))
    current = {number.id for number in numbers}
    # Файлы, что останутся в папке как есть: не из плана или правленные руками. Исчезнувшую
    # задачу, на которую они ссылаются, удалить нельзя.
    staying = [note for note in shelf.files.values()
               if note.id not in current
               or any(plan_note.id == note.id and plan_note.action == "edited"
                      for plan_note in notes)]
    vanished = [VanishedNote(id=old.id, type="issue", text=shelf.files[old.id].body,
                             linked_from=sorted(note.id for note in staying
                                                if old.id in note.links and note.id != old.id))
                for old in filed.values()
                if old.id not in current and old.id in shelf.files and old.id not in reserved]
    return notes, vanished, numbers


def aligned(notes: Sequence[NotePlan], texts: Mapping[str, str] | None = None) -> dict[str, str]:
    """Файлы задач (по ключу), где задача, после которой делать эту, названа не так, как в её
    собственном файле, — с её названием оттуда. Каждый файл переводят своим ходом судьи, и одна
    задача выходила бы под разными названиями; правку названия человеком тоже подхватывают
    строки других файлов. texts — тексты, как файлы лягут (с правками); нет — текст черновика.
    Файл, правленный руками, не трогается, но название в нём — какое есть."""
    def current(note: NotePlan) -> str:
        if note.action == "edited":
            return note.current or ""
        return (texts or {}).get(note.key, note.text)

    titles = {note.id: found.group(1) for note in notes
              if (found := TITLE.search(current(note))) is not None}
    changed: dict[str, str] = {}
    for note in notes:
        if note.action == "edited":
            continue
        text = new = current(note)
        for link in note.links:
            if link != note.id and link in titles:
                new = retitled(new, link, titles[link])
        if new != text:
            changed[note.key] = new
    return changed


def retitled(text: str, issue: str, title: str) -> str:
    """Строка «- ISS-…: …» этой задачи — с этим названием. Таких несколько — последняя: список
    задач, после которых делать эту, в файле последний."""
    found = list(re.finditer(rf"^([ \t]*-[ \t]*{re.escape(issue)}[ \t]*:[ \t]*).*$", text,
                             re.MULTILINE))
    if not found:
        return text
    last = found[-1]
    return text[:last.start()] + last.group(1) + title + text[last.end():]
