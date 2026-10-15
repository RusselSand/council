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
"""

from collections.abc import Collection, Iterable, Mapping, Sequence

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
from .notes import Catalog, issues_in
from .questions import same_question
from .tasks import relabeled


def numbered(issues: Sequence[Issue], catalog: Catalog, previous: TasksExport | None,
             reserved: Collection[str] = (), files: Collection[str] = (),
             occupied: Collection[str] = ()) -> list[IssueNumber]:
    """Номера задач на весь проект: прежняя задача (по названию и сути) — прежний номер, новая —
    следующий после самого большого в каталоге заметок, прежней выгрузке и папке задач (files —
    номера её файлов: новая задача не ляжет в чужой файл). Прежний номер, который упомянут в
    каталоге, занял другой совет (reserved) или под ним в папке лежит файл другой задачи
    (occupied), — уже не наш: тогда новый."""
    known = {number.key: number.id for number in previous.numbers} if previous else {}
    foreign = {issue for note in catalog.notes.values() for issue in issues_in(note.body)}
    foreign |= set(reserved) | set(occupied)
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


def issue_text(issue: Issue, number: str, outcome: tuple[str, str],
               adrs: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]],
               keep: Sequence[str], risks: Sequence[str], words: Mapping[str, str],
               names: Mapping[str, str] | None = None) -> str:
    """Задача для coding agent: кому и зачем, где менять и что там сейчас, что сделать, на чём
    стоит, что соблюдать, что неясно и после каких задач, — и номер для финального коммита.
    Задачи плана текст называет I-n, а агент найдёт их по номерам на весь проект: names."""
    names = names or {}

    def named(value: str) -> str:
        return relabeled(value, names)

    lines = [f"# {line(named(issue.title))}", "", named(issue.user_story.strip())]

    def section(title: str, items: Iterable[str]) -> None:
        items = list(items)
        if items:
            lines.extend(["", f"## {title}", *items])

    now = issue.current_state.strip()
    section(words["entry"], (f"- {line(item)}" for item in issue.main_entry_points))
    section(words["now"], [named(now)] if now else [])
    section(words["scope"], (f"- {line(named(item))}" for item in issue.scope))
    section(words["outcomes"], [f"- {outcome[0]}: {line(outcome[1])}"])
    section(words["decisions"], (f"- {name}: {line(text)}" for name, text in adrs))
    section(words["keep"], (f"- {line(text)}" for text in keep))
    section(words["risks"], (f"- {line(text)}" for text in risks))
    section(words["open"], (f"- {line(named(item))}" for item in issue.open_questions))
    section(words["after"], (f"- {name}: {line(text)}" for name, text in after))
    lines += ["", words["commit"].format(id=number)]
    return "\n".join(lines)


def title_of(catalog: Catalog, note_id: str) -> str:
    """Заметка коротко — её первая строка: у итога это название."""
    note = catalog.notes.get(note_id)
    return note.body.strip().split("\n", 1)[0] if note is not None else ""


def drafted_tasks(plan: TaskPlan, fragments: Mapping[int, LabeledFragment], shelf: Shelf,
                  previous: TasksExport | None, words: Mapping[str, str], language: str,
                  reserved: Collection[str] = ()
                  ) -> tuple[list[NotePlan], list[VanishedNote], list[IssueNumber]]:
    """Черновик выгрузки плана: файл на каждую задачу с номером, текстом и тем, что с ним будет;
    исчезнувшие файлы прежней выгрузки; номера задач. language — язык заметок: не тот, что у
    прошлой выгрузки, — прежние тексты не берутся, их напишет перевод заново (файлы, правленные
    руками, — нет)."""
    catalog = shelf.catalog
    numbers = numbered(plan.issues, catalog, previous, reserved, shelf.files,
                       issue_files.occupied(shelf.files))
    by_issue = {number.issue_id: number for number in numbers}
    filed = {note.id: note for note in previous.notes} if previous else {}
    reuse = previous is not None and previous.language == language
    notes: list[NotePlan] = []
    for issue in plan.issues:
        number = by_issue[issue.id]
        outcome = (issue.outcome_id, title_of(catalog, issue.outcome_id))
        adrs = [(name, catalog.notes[name].body.strip()) for name in issue.adr_ids
                if name in catalog.notes]
        after = [(by_issue[name].id, by_issue[name].title) for name in issue.depends_on
                 if name in by_issue]
        text = issue_text(issue, number.id, outcome, adrs, after,
                          [fragments[i].text for i in issue.constraint_ids if i in fragments],
                          [fragments[i].text for i in issue.risk_ids if i in fragments], words,
                          {name: number.id for name, number in by_issue.items()})
        links = tuple(dict.fromkeys(name for name, _ in (outcome, *adrs, *after)))
        old = filed.get(number.id)
        notes.append(planned(Part(number.key, "issue", text, links), {number.key: number.id},
                             old, old.key if old else None, shelf, reuse))
    current = {number.id for number in numbers}
    vanished = [VanishedNote(id=old.id, type="issue", text=shelf.files[old.id].body)
                for old in filed.values()
                if old.id not in current and old.id in shelf.files and old.id not in reserved]
    return notes, vanished, numbers
