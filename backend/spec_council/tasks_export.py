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
from .export import (
    ISSUE,
    Part,
    Shelf,
    blocks_of,
    keyed,
    matched,
    migrated,
    note_key,
    numbering_problem,
    numbers_in_prose,
    planned,
)
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
from .tasks import Names, line, relabeled

# Название задачи — заголовок её файла: первая строка «# …» (без закрывающих «#»). Первая
# строка не заголовок (файл правили руками) — названия нет.
TITLE = re.compile(r"[ ]{0,3}#[ \t]+(.+?)(?:[ \t]+#+)?[ \t\r]*(?=\n|\Z)")
# Заголовок раздела файла задачи «## …» — и с отступом до трёх пробелов, и с табуляцией.
SECTION = re.compile(r"[ ]{0,3}##(?:[ \t\r]|$)")
# Пункт списка задач, после которых делать эту: «- ISS-0012: название».
AFTER = re.compile(r"^([ \t]*-[ \t]*(ISS-\d+)[ \t]*:[ \t]*).*$")


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


def issue_title(issue: Issue, names: Mapping[str, str],
                renumber: Callable[[str], str] | None = None, keep: Collection[str] = ()) -> str:
    """Название задачи, как оно ляжет и в её файл, и в строку «- ISS-…: …» задач, что ждут её:
    одной строкой — и номера в ней по ней же."""
    title = relabeled(line(issue.title), names, keep)
    return renumber(title) if renumber else title


def issue_text(issue: Issue, number: str, outcome: tuple[str, str],
               adrs: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]],
               keep: Sequence[str], risks: Sequence[str], words: Mapping[str, str],
               names: Mapping[str, str] | None = None,
               renumber: Callable[[str], str] | None = None,
               phrases: Collection[str] = ()) -> str:
    """Задача для coding agent: кому и зачем, где менять и что там сейчас, что сделать, на чём
    стоит, что соблюдать, что неясно и после каких задач (after — с названиями из issue_title), —
    и номер для финального коммита. Задачи плана текст называет I-n, а агент найдёт их по
    номерам на весь проект: names, кроме сочетаний phrases («I1 cache»). Номера потока своего
    итога в тексте модели — номерами заметок: renumber. Итог и решения — как в каталоге."""
    names = names or {}

    def fixed(value: str) -> str:
        return renumber(value) if renumber else value

    def named(value: str) -> str:
        return fixed(relabeled(value, names, phrases))

    lines = [f"# {issue_title(issue, names, renumber, phrases)}", "",
             named(issue.user_story.strip())]

    def section(title: str, items: Iterable[str]) -> None:
        items = list(items)
        if items:
            lines.extend(["", f"## {title}", *items])

    now = issue.current_state.strip()
    section(words["entry"], (f"- {line(item)}" for item in issue.main_entry_points))
    section(words["now"], [named(now)] if now else [])
    # Пункт ляжет одной строкой — номера в нём ищут уже в ней: «Пример:\n\n    Q1» станет
    # прозой, а не блоком кода.
    section(words["scope"], (f"- {named(line(item))}" for item in issue.scope))
    section(words["outcomes"], [f"- {outcome[0]}: {line(outcome[1])}"])
    section(words["decisions"], (f"- {name}: {line(text)}" for name, text in adrs))
    section(words["keep"], (f"- {line(text)}" for text in keep))
    section(words["risks"], (f"- {line(text)}" for text in risks))
    section(words["open"], (f"- {named(line(item))}" for item in issue.open_questions))
    section(words["after"], (f"- {name}: {line(text)}" for name, text in after))
    lines += ["", words["commit"].format(id=number)]
    return "\n".join(lines)


def written_by_plan(issue: Issue) -> list[str]:
    """Что в задаче написала модель плана: название, история, что там сейчас, что сделать,
    что неясно, — как это ляжет в файл: название и пункты списков — одной строкой."""
    return [line(issue.title), issue.user_story, issue.current_state,
            *map(line, issue.scope), *map(line, issue.open_questions)]


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
    # Модели плана видели номера заметок и писали их в текст задач: какую с тех пор удалили, на
    # ту задача сослалась бы впустую. Номер с нулями или без — одна заметка.
    known = {note_key(note_id) for note_id in catalog.notes}

    def names_of(issue: Issue) -> Names | None:
        names = (streams or {}).get(issue.outcome_id)
        return names.within(catalog.notes) if names is not None else None

    def renumber(issue: Issue) -> Callable[[str], str] | None:
        names = names_of(issue)
        return (lambda text: names(text, words["quote"])) if names else None

    def kept(issue: Issue) -> frozenset[str]:
        names = names_of(issue)
        return names.phrases if names is not None else frozenset()

    def final(issue: Issue, text: str) -> str:
        """Текст, как он ляжет: на месте номера без заметки — его текст, а в нём могут быть свои
        номера заметок."""
        change = renumber(issue)
        return change(text) if change else text

    # Номер в сочетании из исходных текстов потока («ADR-9999 fixture») — их слово, не ссылка.
    dead = sorted({found for issue in plan.issues for text in written_by_plan(issue)
                   for found in numbers_in_prose(final(issue, text), kept(issue))
                   if not found.startswith("ISS-") and note_key(found) not in known})
    if dead:
        raise NotesError(f"В каталоге заметок больше нет {', '.join(dead)}, а задачи плана их "
                         "называют: верните заметки или выгрузите потоки заново и спланируйте "
                         "снова")
    labels = {name: number.id for name, number in by_issue.items()}

    titles = {issue.id: issue_title(issue, labels, renumber(issue), kept(issue))
              for issue in plan.issues}
    notes: list[NotePlan] = []
    for issue in plan.issues:
        number = by_issue[issue.id]
        # Итог и решения — как в каталоге: номера потока в них ушли при выгрузке, а правку
        # человека в заметке пересчитывать нельзя. Кроме заметок потока, чья запись — до
        # номеров заметок (Names.settled): там номера потока остались.
        names = names_of(issue)

        def settled(note_id: str, text: str, names: Names | None = names) -> str:
            return names.settled(note_id, text, words["quote"]) if names else text

        outcome = (issue.outcome_id,
                   settled(issue.outcome_id, title_of(catalog, issue.outcome_id)))
        adrs = [(name, settled(name, catalog.notes[name].body.strip()))
                for name in issue.adr_ids if name in catalog.notes]
        after = [(by_issue[name].id, titles[name]) for name in issue.depends_on
                 if name in by_issue]
        text = issue_text(issue, number.id, outcome, adrs, after,
                          [fragments[i].text for i in issue.constraint_ids if i in fragments],
                          [fragments[i].text for i in issue.risk_ids if i in fragments], words,
                          labels, renumber(issue), kept(issue))
        links = tuple(dict.fromkeys(name for name, _ in (outcome, *adrs, *after)))
        old = filed.get(number.id)
        notes.append(planned(Part(number.key, "issue", text, links), {number.key: number.id},
                             migrated(old, text, renumber(issue)), old.key if old else None,
                             shelf, reuse))
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


def aligned(notes: Sequence[NotePlan], texts: Mapping[str, str] | None = None,
            fresh: Collection[str] = ()) -> dict[str, str]:
    """Файлы задач (по ключу), где задача, после которой делать эту, названа не так, как в её
    собственном файле, — с её названием оттуда. Каждый файл переводят своим ходом судьи, и одна
    задача выходила бы под разными названиями; правку названия человеком тоже подхватывают
    строки других файлов. texts — тексты, как файлы лягут (с правками); нет — текст черновика.
    fresh — ключи файлов, что только что перевели. Файл, правленный руками, не трогается, но
    название в нём — какое есть."""
    def current(note: NotePlan) -> str:
        if note.action == "edited":
            return note.current or ""
        return (texts or {}).get(note.key, note.text)

    titles = {note.id: found.group(1) for note in notes
              if (found := TITLE.match(current(note))) is not None}
    def closing(note: NotePlan) -> str | None:
        """Строка о номере для коммита этого файла: у только что переведённого — его последняя
        строка с его номером (перевод хранит строение текста, а слова у каждого файла свои),
        иначе — последняя строка черновика, как она есть: правку человека не угадывать."""
        last = filled(current(note) if note.key in fresh else note.text)
        return last if last is not None and note.id in last else None

    changed: dict[str, str] = {}
    for note in notes:
        if note.action == "edited":
            continue
        text = current(note)
        # Список задач, после которых делать эту, issue_text кладёт последним разделом.
        section = sum(bool(SECTION.match(row)) for row in note.generated.split("\n")) - 1
        waits = {link for link in note.links if link != note.id and ISSUE.fullmatch(link)}
        new = retitled(text, {link: titles[link] for link in waits if link in titles}, waits,
                       section, closing(note))
        # Название с номером заметки или задачи (правили руками) принесло бы его в чужой файл
        # без ссылки во frontmatter: такой файл — как был.
        if new != text and numbering_problem(text, new) is None:
            changed[note.key] = new
    return changed


def filled(text: str) -> str | None:
    """Последняя непустая строка текста."""
    rows = [row.strip() for row in text.split("\n") if row.strip()]
    return rows[-1] if rows else None


def retitled(text: str, titles: Mapping[str, str], waits: Collection[str], section: int,
             commit: str | None) -> str:
    """Список задач, после которых делать эту, — с названиями из их файлов (titles; у какой
    названия не узнать — её строка как есть). Это раздел «## …», где, кроме пустых, только
    строки «- ISS-…: …» задач, которых ждут (waits), до строки о номере для коммита (commit):
    issue_text ставит её после списка, а что дописали после неё — уже не список.
    Таких разделов несколько (человек дописал похожий) — тот, что под тем же номером (section,
    с нуля), что и в тексте совета: разделы переставили или убрали, а список один — он. Не
    узнать — текст как есть."""
    lines = text.split("\n")
    # Пример кода в задаче — не её разделы: «##» в нём не заголовок, а строка — не пункт.
    code = blocks_of(text).code
    heads = [n for n, row in enumerate(lines) if n not in code and SECTION.match(row)]
    if not heads:
        return text
    # Строка о коммите кончает список — и тогда, когда человек дописал что-то после неё.
    closing = next((n for n in range(len(lines) - 1, -1, -1)
                    if n not in code and commit and lines[n].strip() == commit), None)
    found: list[tuple[int, list[tuple[int, re.Match[str]]]]] = []
    for place, (start, end) in enumerate(zip(heads, [*heads[1:], len(lines)], strict=True)):
        if closing is not None and start < closing < end:
            end = closing
        rows = [n for n in range(start + 1, end) if lines[n].strip()]
        items = [(n, match) for n in rows
                 if n not in code and (match := AFTER.match(lines[n])) is not None]
        # Список — все задачи, которых ждут, по строке на каждую, и только они: пункт об одной
        # из них или повтор — ещё не он.
        if (rows and len(items) == len(rows) == len(waits)
                and {m.group(2) for _, m in items} == set(waits)):
            found.append((place, items))
    chosen = found[0][1] if len(found) == 1 else next(
        (items for place, items in found if place == section), None)
    if chosen is None:
        return text
    for n, match in chosen:
        if match.group(2) in titles:
            ending = "\r" if lines[n].endswith("\r") else ""
            lines[n] = match.group(1) + titles[match.group(2)] + ending
    return "\n".join(lines)
