"""План задач на весь совет: что видят модели и как проверяется их ответ.

План строят, когда во всех потоках итоги утверждены и выгружены в заметки: тогда у каждого
итога и решения есть номер заметки (OUT-…, ADR-…), и модели называют их им — те же номера ложатся
в файлы задач, и ссылки в тексте задачи сразу верные. Итог, что в заметки не лёг (у него нет
решений своей идеи), в план не входит — это видно.

Ответ модели проверяет код: у задачи ровно один итог — из плана; решения, ограничения и риски —
только те, что есть у её итога; зависимости — только на задачи раньше неё по плану (на задачу
дальше — негодный ответ: порядок плана и есть порядок работы). Номера задач код раздаёт заново по
порядку плана: I1, I2…
"""

import json
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from .export import (
    in_prose,
    note_key,
    numbers_in_prose,
    phrases_of,
    renumbered,
    stream_texts,
    terms_of,
)
from .models import Council, Issue, LabeledFragment, Outcome, Stream
from .slicing import BadAnswer

TEXT_MAX = 4000
ITEMS_MAX = 20


@dataclass(frozen=True)
class Allowed:
    """На что может сослаться задача одного итога: его решения (которые он реализует, на которые
    опирается, и прошлые решения проекта), его ограничения и риски."""

    adrs: frozenset[str]
    constraints: frozenset[int]
    risks: frozenset[int]


@dataclass(frozen=True)
class Context:
    """Итоги плана — номерами заметок — и на что может сослаться задача каждого из них. И
    сочетания исходных текстов у потока каждого итога (Names.phrases): номер задачи в «I1
    cache» — слово, и новым номером он не становится."""

    outcomes: Mapping[str, Allowed]
    phrases: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Names:
    """Номера потока (Q1, P2, F3, ADR-n, O-n, находки скана) и что за ними: номер заметки, а нет
    её — текст. Тексты потока называют ими свои части, а в плане и в файлах задач нужны номера
    заметок (renumbered)."""

    numbers: Mapping[str, str]
    texts: Mapping[str, str]
    # Двусмысленные номера: их не трогают нигде (terms_of).
    terms: frozenset[str] = frozenset()
    # Сочетания исходных текстов со словом, похожим на номер («F1 score», «I1 cache»): номером
    # они не становятся (phrases_of).
    phrases: frozenset[str] = frozenset()
    # Заметки потока, чья запись — до номеров заметок (их файлы правили руками, и выгрузка их
    # оставила): в их тексте номера потока (Q1).
    legacy: frozenset[str] = frozenset()
    # Что за номерами в текстах самого потока: находки — его скана, а не исследования совета
    # (texts — для текстов плана, что читал исследование). Пусто — те же texts.
    owned: Mapping[str, str] = field(default_factory=dict)

    def __call__(self, text: str, quote: str = "«{}»") -> str:
        return renumbered(text, self.numbers, self.texts, quote, self.terms, self.phrases)

    def settled(self, note_id: str, text: str, quote: str = "«{}»") -> str:
        """Текст заметки потока с номерами заметок: в записи до них (legacy) — номера потока, и
        R1 в нём — находка скана потока (owned)."""
        if note_id not in self.legacy:
            return text
        return renumbered(text, self.numbers, self.owned or self.texts, quote, self.terms,
                          self.phrases)

    def within(self, notes: Collection[str]) -> Names:
        """Только номера заметок, что есть в каталоге (notes): заметку вопроса или варианта
        могли удалить руками, и ссылка на неё вела бы в никуда — тогда в тексте встанет то,
        что за номером. Номер с нулями или без — одна заметка: ссылка — как её зовёт каталог."""
        spelled = {note_key(note_id): note_id for note_id in notes}
        return replace(self, numbers={name: spelled[note_key(number)]
                                      for name, number in self.numbers.items()
                                      if note_key(number) in spelled})


def exported_of(council: Council) -> frozenset[str]:
    """Номера заметок, что выгрузили потоки совета."""
    return frozenset(note.id for stream in council.streams or [] if stream.notes
                     for note in stream.notes.notes)


def research_cited(research: Mapping[str, str], catalog: Collection[str]) -> list[str]:
    """Номера заметок каталога (catalog — что в нём сейчас), которые называет проза находок
    исследования (research_texts): это ссылки, а не слова. Запоминают, когда строят план
    (TaskPlan.cited): заметку потом могут удалить."""
    keys = {note_key(note_id) for note_id in catalog}
    return sorted({found for text in research.values() for found in numbers_in_prose(text)
                   if note_key(found) in keys})


def names_of(stream: Stream, fragments: Mapping[int, LabeledFragment],
             research: Mapping[str, str] | None = None,
             exported: Collection[str] = (), cited: Collection[str] = ()) -> Names:
    """Номера потока по его выгрузке. research — находки исследования совета: план читал его
    карту кода и описание макета, и тексты задач называют их находки, а не копии потока.
    Сочетания — и из выгруженных заметок потока: модели плана видят их тексты, а человек мог
    дописать туда своё «Q1 reporting». exported — номера заметок всех потоков совета
    (exported_of); cited — номера каталога, что называет исследование (research_cited)."""
    found = dict(research or {})
    notes = stream.notes.notes if stream.notes else []
    written = [note.written for note in notes]
    # Номер заметки любого потока совета, отобранного решения проекта или заметки каталога, что
    # была там, когда текст записывали (references), в выгруженном тексте — ссылка.
    known = {*(stream.notes.refs.values() if stream.notes else ()), *exported,
             *(decision.adr_id for decision in stream.project_decisions or []),
             *(reference for note in notes for reference in note.references)}
    # Номера каталога, что называют исходные тексты потока (при его выгрузке) и исследование
    # (cited — когда строили план).
    cited = [*(stream.notes.cited if stream.notes else []), *cited]
    owned = stream_texts(stream, fragments)
    return Names(stream.notes.refs if stream.notes else {}, owned | found,
                 terms_of(stream, cited),
                 phrases_of(stream, fragments, found.values(), written, known, cited),
                 frozenset(note.id for note in notes if not note.note_numbers), owned)


def research_texts(council: Council) -> dict[str, str]:
    """Находки исследования совета — карты кода (R…) и описания макета (D…), — если шаг
    пройден этим сканом: пропущенный или пройденный другим план не читал."""
    research = council.research
    if research is None:
        return {}
    steps = ((research.repository, research.scan), (research.design, research.design_scan))
    return {finding.id: finding.statement for step, scan in steps
            if step is not None and step.by == "scan" and scan is not None
            and scan.run == step.scan_run and scan.result is not None
            for finding in scan.result.findings}


def own_fragments(council: Council, stream: Stream,
                  fragments: Mapping[int, LabeledFragment]) -> dict[int, LabeledFragment]:
    """Фрагменты группы потока: по ним шли его вопросы, варианты и итоги — и выгрузка его
    заметок. Термин другой группы — не термин этого потока."""
    groups = council.structure.groups if council.structure else []
    group = next((group for group in groups if group.id == stream.group), None)
    return {i: fragment for i, fragment in fragments.items()
            if group is None or i in group.fragment_ids}


def outcome_names(council: Council, fragments: Mapping[int, LabeledFragment],
                  cited: Collection[str] = ()) -> dict[str, Names]:
    """Номера потока у каждого итога плана — по номеру заметки итога: файл задачи называет
    части потока своего итога. cited — номера каталога, что называло исследование, когда
    строили план (TaskPlan.cited)."""
    research = research_texts(council)
    exported = exported_of(council)
    found: dict[str, Names] = {}
    for stream in council.streams or []:
        names = names_of(stream, own_fragments(council, stream, fragments), research, exported,
                         cited)
        for outcome in stream.outcomes.outcomes if stream.outcomes else []:
            if outcome.id in names.numbers:
                found[names.numbers[outcome.id]] = names
    return found


@dataclass(frozen=True)
class Inputs:
    """Что видят модели (values — подстановки промптов, кроме кода и макета), на что можно
    сослаться, итоги плана по порядку, что в план не вошло и к чему он (basis)."""

    values: dict[str, str]
    context: Context
    outcomes: list[str]
    skipped: list[str]
    basis: dict[str, str]
    # Номера каталога, что называет исследование, — пока они в каталоге (research_cited).
    cited: list[str] = field(default_factory=list)


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


RESEARCH = "research"


def basis_of(council: Council) -> dict[str, str]:
    """К чему план: у каждого потока — его утверждённые итоги и выгрузка, а у исследования
    (RESEARCH) — как пройдены его шаги: план читает его карту кода и описание макета."""
    research = council.research
    steps = [research.repository, research.design] if research else [None, None]
    return {**{stream.group: f"{stream.outcomes.run if stream.outcomes else ''}:"
                             f"{stream.notes.run if stream.notes else ''}"
               for stream in council.streams or []},
            RESEARCH: "|".join(f"{step.by}:{step.scan_run}" if step else "" for step in steps)}


def not_ready(council: Council, notes: str | None) -> list[str]:
    """Почему план строить рано: какой поток не утвердил итоги или не выгружен к ним в нынешний
    каталог заметок — или выгружен, когда совет ещё не помнил номера заметок (`refs`) или помнил
    только у решений и итогов: тогда модели не узнали бы, как зовут его итоги, а тексты — его
    вопросы и варианты. Идея ложится всегда, так что её I1 есть в каждой нынешней выгрузке.
    Пусто — можно."""
    if not council.streams:
        return ["Группы ещё не подтверждены"]
    problems = []
    for stream in council.streams:
        outcomes = stream.outcomes
        if outcomes is None or not outcomes.approved:
            problems.append(f"Поток {stream.group}: итоги не утверждены")
        elif (stream.notes is None or notes is None or stream.notes.root != notes
              or stream.notes.outcomes != outcomes.run):
            problems.append(f"Поток {stream.group}: не выгружен в заметки к утверждённым итогам")
        elif "I1" not in stream.notes.refs:
            problems.append(f"Поток {stream.group}: выгружен до того, как совет стал помнить "
                            "номера заметок, — выгрузите его заново")
    return problems


def ideas_text(council: Council) -> str:
    titles = {group.id: group.title for group in council.structure.groups}
    return "\n".join(f"{stream.group}. {titles.get(stream.group, '')}: {stream.idea.text}"
                     for stream in council.streams or [] if stream.idea is not None)


def inputs_of(council: Council) -> Inputs:
    """Итоги всех потоков с номерами заметок, их решения, решения проекта, на которые они
    опираются, ограничения и риски."""
    fragments = {f.id: f for f in council.slicing.fragments} if council.slicing else {}
    outcomes: list[dict] = []
    allowed: dict[str, Allowed] = {}
    decisions: dict[str, dict] = {}
    constraints: set[int] = set()
    risks: set[int] = set()
    skipped: list[str] = []
    exported = exported_of(council)
    for stream in council.streams or []:
        refs = stream.notes.refs if stream.notes else {}
        names = names_of(stream, own_fragments(council, stream, fragments), exported=exported)
        written = {note.id: note.written for note in stream.notes.notes} if stream.notes else {}
        for outcome in stream.outcomes.outcomes if stream.outcomes else []:
            note = refs.get(outcome.id)
            if note is None:
                skipped.append(f"Поток {stream.group}: {outcome.id} «{outcome.title}» не лёг в "
                               "заметки — в план не входит")
                continue
            entry = outcome_entry(outcome, note, stream.group, refs, names)
            outcomes.append(entry)
            allowed[note] = Allowed(
                frozenset([*entry["implements"], *entry["relies_on"],
                           *entry["project_decisions"]]),
                frozenset(outcome.constraint_ids), frozenset(outcome.risk_ids))
            constraints |= set(outcome.constraint_ids)
            risks |= set(outcome.risk_ids)
            for name in (*outcome.adr_ids, *outcome.relies_on_adr_ids):
                if name in refs:
                    decisions[refs[name]] = adr_entry(stream, name, refs[name], written,
                                                      names)
            projects = {d.adr_id: d for d in stream.project_decisions or []}
            for adr_id in outcome.project_decision_ids:
                if adr_id in projects:
                    found = projects[adr_id]
                    decisions[adr_id] = {"id": adr_id, "project": True, "idea": found.idea,
                                         "question": found.question, "decision": found.decision,
                                         "status": found.status,
                                         "superseded_by": found.superseded_by}
    values = {"ideas": ideas_text(council), "outcomes": as_json(outcomes),
              "decisions": as_json(list(decisions.values())),
              "constraints_and_risks": as_json(limits_prompt(fragments, constraints | risks))}
    context = Context(allowed, {note: names.phrases
                                for note, names in outcome_names(council, fragments).items()})
    return Inputs(values, context, [o["id"] for o in outcomes], skipped, basis_of(council))


def outcome_entry(outcome: Outcome, note: str, group: str, refs: Mapping[str, str],
                  named: Names) -> dict:
    """Итог, как его видят модели: номер заметки, поток, что меняется и чем проверить, какие
    решения он реализует и на какие опирается, — номерами заметок, и в тексте тоже (names):
    что модели прочтут, то и перепишут в задачи."""
    return {"id": note, "group": group, "title": named(outcome.title),
            "behavior": named(outcome.behavior),
            "acceptance_criteria": [named(item) for item in outcome.acceptance_criteria],
            "implements": [refs[name] for name in outcome.adr_ids if name in refs],
            "follows": {refs[name]: named(text) for name, text in outcome.adr_notes.items()
                        if name in refs},
            "relies_on": [refs[name] for name in outcome.relies_on_adr_ids if name in refs],
            "project_decisions": outcome.project_decision_ids,
            "constraint_ids": outcome.constraint_ids, "risk_ids": outcome.risk_ids}


def adr_entry(stream: Stream, name: str, note: str, written: Mapping[str, str],
              named: Names) -> dict:
    """Решение потока: номер заметки, вопрос и текст, как они легли в заметки («решение,
    потому что обоснование»): номера потока в них ушли при выгрузке, а правку человека
    пересчитывать нельзя — кроме записи до номеров заметок (Names.settled). Вопроса в заметках
    нет — его текст в потоке, с номерами заметок (names)."""
    n = int(name.split("-")[1])
    scope = stream.scope or []
    question = scope[n - 1] if 0 < n <= len(scope) else None
    asked_note = named.numbers.get(question.id, "") if question else ""
    asked = named.settled(asked_note, written.get(asked_note, ""))
    return {"id": note,
            "question": asked or (named(question.note or question.text) if question else ""),
            "decision": named.settled(note, written.get(note, ""))}


def limits_prompt(fragments: Mapping[int, LabeledFragment], ids: Iterable[int]) -> list[dict]:
    return [{"id": i, "type": fragments[i].label, "text": fragments[i].text}
            for i in sorted(ids) if i in fragments]


def text_of(value: object, what: str, required: bool = True) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if required and not text:
        raise BadAnswer(f"у задачи нет {what}")
    if len(text) > TEXT_MAX:
        raise BadAnswer(f"{what} задачи длиннее {TEXT_MAX} знаков")
    return text


def texts_of(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()][:ITEMS_MAX]


def line(text: str) -> str:
    """Пункт списка и название задачи — одной строкой: перенос внутри разорвал бы список. И
    номера в нём ищут уже в этой строке: «Пример:\n\n    I2» — проза, а не блок кода."""
    return " ".join(text.split())


def relabeled(text: str, names: Mapping[str, str], keep: Collection[str] = ()) -> str:
    """Номера задач в тексте — новыми (names: прежний → новый), за один проход: I1 ↔ I2 не
    путаются. Сочетания keep («I1 cache») — как есть: там номер — слово; код и адреса ссылок —
    тоже (in_prose)."""
    if not names:
        return text
    pattern = re.compile(r"(?<![\w-])(" + "|".join(
        re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")(?![\w-])")

    def renamed(part: str) -> str:
        return pattern.sub(lambda found: names[found.group(1)], part)

    return in_prose(text, renamed, keep)


def plan_of(data: dict, context: Context) -> list[Issue]:
    """План из ответа модели: задачи по порядку, с номерами I1, I2… — и в тексте задач тоже.
    Задача, чей итог не из плана, отбрасывается — как и ссылки на решения, ограничения и риски,
    которых у её итога нет. Задача ждёт только задачи раньше себя: зависимость от задачи дальше
    по плану — негодный ответ, порядок плана и есть порядок работы."""
    items = data.get("issues")
    if not isinstance(items, list):
        raise BadAnswer("нет списка issues")
    kept: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("outcome_id"), str) \
                or item["outcome_id"] not in context.outcomes:
            continue
        name = item.get("id") if isinstance(item.get("id"), str) else ""
        if name in seen:
            raise BadAnswer(f"номер {name} у двух задач")
        seen.add(name)
        kept.append((name, item))
    renamed = {name: f"I{n}" for n, (name, _) in enumerate(kept, 1) if name}
    issues = []
    for n, (_, item) in enumerate(kept, 1):
        issue_id = f"I{n}"
        after = [renamed[d] for d in texts_of(item.get("depends_on"))
                 if d in renamed and renamed[d] != issue_id]
        later = [name for name in after if int(name[1:]) > n]
        if later:
            raise BadAnswer(f"{issue_id} ждёт задачи после себя: {', '.join(later)} — порядок "
                            "плана и есть порядок работы")
        own = context.outcomes[item["outcome_id"]]
        keep = context.phrases.get(item["outcome_id"], frozenset())

        def text(value: str, keep: frozenset[str] = keep) -> str:
            return relabeled(value, renamed, keep)

        issues.append(Issue(
            id=issue_id, title=text(line(text_of(item.get("title"), "названия"))),
            user_story=text(text_of(item.get("user_story"), "user story")),
            main_entry_points=texts_of(item.get("main_entry_points")),
            current_state=text(text_of(item.get("current_state"), "нынешнего состояния", False)),
            scope=[text(line(entry)) for entry in texts_of(item.get("scope"))],
            outcome_id=item["outcome_id"],
            adr_ids=[a for a in texts_of(item.get("adr_ids")) if a in own.adrs],
            constraint_ids=ints_in(item.get("constraint_ids"), own.constraints),
            risk_ids=ints_in(item.get("risk_ids"), own.risks),
            depends_on=list(dict.fromkeys(after)),
            open_questions=[text(line(entry))
                            for entry in texts_of(item.get("open_questions"))]))
    return issues


def ints_in(value: object, allowed: frozenset[int]) -> list[int]:
    if not isinstance(value, list):
        return []
    found = [item for item in value if isinstance(item, int) and not isinstance(item, bool)]
    return sorted({item for item in found if item in allowed})


def same_plan(plans: Sequence[Sequence[Issue]]) -> bool:
    """Планы совпали — судья не нужен."""
    shapes = {json.dumps([issue.model_dump() for issue in plan], ensure_ascii=False,
                         sort_keys=True) for plan in plans}
    return len(shapes) == 1


def plan_prompt(plan: Sequence[Issue]) -> list[dict]:
    """План участника, как его видит судья."""
    return [issue.model_dump() for issue in plan]
