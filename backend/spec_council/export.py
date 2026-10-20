"""Выгрузка потока в заметки проекта (notes.py): IDEA, отобранные вопросы, их варианты,
принятые решения и утверждённые итоги — каждое своей заметкой, со ссылками на ближайшие
вышестоящие. Поток выгружают, как только утвердили итоги, до задач: так следующий поток видит
его решения через «решения проекта». Задач в заметках потока нет — связь у них односторонняя:
файл задачи называет свой итог, а заметка итога задач не перечисляет.

Выгрузка — в два хода. Черновик (drafted): какие заметки лягут, под какими номерами, с каким
текстом и что с ними будет — новая, перепишется, уже такая, правили руками. Запись (written):
то, что человек подтвердил, с его правками текста и отмеченными к удалению исчезнувшими.

Повторная выгрузка узнаёт свои прежние заметки по ключу части потока: вопрос из текста — по
фрагменту, остальные — по формулировке; вариант — по вопросу и фрагменту или формулировке;
решение — по вопросу и выбранному варианту (выбрали другой — это другое решение и новая
заметка); итог — по названию. Правка варианта — по вопросу и исходному варианту: сколько её
ни правь, это его заметка, и её решение — решение исходного. Совет написал бы то же, что в
прошлый раз, — остаётся то, что тогда записали, с правками человека. Файл, который правили
руками после выгрузки, совет не трогает. Исчезнувшее само не удаляется.

Тексты потока называют его части его же номерами: «по Q1», «(F3)». В заметки они ложатся
номерами заметок, а у чего заметки нет — без номера (renumbered).
"""

import hashlib
import re
import string
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from functools import partial
from html import unescape
from itertools import accumulate, groupby
from pathlib import Path
from typing import NamedTuple

from markdown_it import MarkdownIt, rules_inline
from markdown_it.common import html_re
from markdown_it.common.html_blocks import block_names
from markdown_it.rules_inline import StateInline

from . import issue_files
from .design import context_prompt as design_context
from .models import (
    Choice,
    Decision,
    ExportedNote,
    LabeledFragment,
    NotePlan,
    NotesExport,
    OpenQuestion,
    Proposal,
    Research,
    Stream,
    VanishedNote,
)
from .notes import Catalog, Note, NotesError, declared_issues, path_of, rendered
from .proposals import found_by_question
from .questions import same_question
from .repository import context_prompt
from .slicing import BadAnswer

# Связки в тексте заметок и файлов задач — на языке работы; перевод, если нужен, — потом,
# целиком.
WORDS = {
    "russian": {"because": "потому что", "criteria": "Критерии готовности", "issues": "Задачи",
                "entry": "Где менять", "now": "Что там сейчас", "scope": "Что сделать",
                "outcomes": "Итоги", "decisions": "Решения", "keep": "Соблюдать",
                "risks": "Риски", "after": "После задач", "open": "Открытые вопросы",
                "commit": "В финальном коммите укажите номер задачи — {id}.",
                "quote": "«{}»"},
    "english": {"because": "because", "criteria": "Acceptance criteria", "issues": "Issues",
                "entry": "Where to change", "now": "What is there now", "scope": "To do",
                "outcomes": "Outcomes", "decisions": "Decisions", "keep": "Keep",
                "risks": "Risks", "after": "After the issues", "open": "Open questions",
                "commit": "Put the issue number {id} into the final commit.",
                "quote": "“{}”"},
}
ALIASES = {"русский": "russian", "ru": "russian", "en": "english", "английский": "english"}
ISSUE = re.compile(r"ISS-(\d+)")
# Между названием итога (задачи) и его сутью в ключе. same_question такого знака не оставит:
# для split он пробел.
SEP = "\x1f"
NUMBER = re.compile(r"(?<![\w-])(?:IDEA|OQ|PRO|ADR|OUT|ISS)-\d+(?![\w-])")
# Слово, похожее на номер потока, заметки или задачи плана: Q1, F3, ADR-9999, I1.
WORDLIKE = re.compile(r"(?<![\w-])(?:(?:IDEA|OQ|PRO|ADR|OUT|ISS)-\d+|[IQPFORD][1-9]\d*)(?![\w-])")
# Решение из каталога: его номер с нулями или без («ADR-0007», «ADR-7») — одно решение.
PAST_ADR = re.compile(r"ADR-0*([1-9]\d*)", re.IGNORECASE)
# Номера внутри потока: идея, вопрос, вариант (и фрагмент текста группы), решение, итог,
# находки скана репозитория и макета. В документации они ничего не значат.
LOCAL = re.compile(r"(?<![\w-])(?:ADR-[1-9]\d*|[IQPFORD][1-9]\d*)(?![\w-])")
# Блоки кода и HTML — строки, которые они занимают, на любой глубине (в цитате, в пункте
# списка): их ищет разбор Markdown. Номера в них — не ссылки. Ссылку с любым адресом разбор
# считает ссылкой, как CommonMark: javascript: — тоже.
MARKDOWN = MarkdownIt("commonmark")
MARKDOWN.validateLink = lambda url: True
BLOCKS = ("fence", "code_block", "html_block")


# Атрибуты тега HTML по CommonMark: значение в "…", '…' или без кавычек — «>» в кавычках тег не
# обрывает. И элементы, чьё содержимое — код или сырой текст.
ATTRIBUTES = (r"""(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*"""
              r"""(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*""")
RAW = "code|pre|kbd|samp|tt|var|script|style|textarea"
# Из них — сырой текст: тег внутри — текст до своего закрывающего.
RAW_TEXT = frozenset(("script", "style", "textarea"))
# Открывающий и закрывающий тег такого элемента: его содержимое ищет raw_elements.
RAW_TAG = re.compile(rf"(?i:<(?P<open>{RAW})\b{ATTRIBUTES}\s*>|</(?P<close>{RAW})\s*>)")
# Что не трогают в строке прозы сверх того, что находит её разбор (marking): почта сама по себе.
UNTOUCHED = re.compile(
    r"<?[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*>?")
# Начало адреса самого по себе: «https://».
SCHEME = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://")
# Что in_prose прячет от change (код, адрес ссылки, тег), — знаком из этих: change видит текст
# блока целиком, а спрятанное не тронет.
MASK = 0xF0000
MASKED = re.compile("[\U000F0000-\U000FFFFD]")
# Скобки, где одни номера — потока или заметок: «(F3)», «(Q1, F3)», «(R8 и R12)», — и с
# разметкой вокруг номера: «(**F3**)», «([F3](…))», «(<b>F3</b>)» (адрес ссылки и теги спрятаны,
# MASKED).
CITED_NUMBER = r"(?:(?:IDEA|OQ|PRO|ADR|OUT|ISS)-\d+|[IQPFORD][1-9]\d*)(?![\w-])"
MARKED_NUMBER = (rf"(?:[*_\[]|{MASKED.pattern})*{CITED_NUMBER}"
                 rf"(?:[*_\]]|{MASKED.pattern})*")
CITED = re.compile(rf"\(\s*{MARKED_NUMBER}(?:(?:\s*[,;/]|\s+(?:and|и))\s*{MARKED_NUMBER})*\s*\)")
# Критерий, что начинается как строка задачи: «ISS-0042: …».
ISSUE_START = re.compile(r"\s*(ISS-\d+)\s*:")


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
    каталога (у вопроса, который пересматривает прошлое решение, — этот ADR). was — под каким
    ключом часть могла лечь в прошлый раз, если не под своим: правка варианта, которую выгрузили
    своим вариантом до того, как отметили, — под ключом своей формулировки, и её решение — тоже."""

    key: str
    type: str
    text: str
    links: tuple[str, ...]
    was: str | None = None


@dataclass(frozen=True)
class Shelf:
    """Куда ложится выгрузка: заметки — в каталог root, файлы задач — в папку issues (None — у
    проекта её нет: задачи только строками в итогах). files — файлы задач, что в ней уже лежат,
    по номеру."""

    catalog: Catalog
    root: Path
    issues: Path | None = None
    files: Mapping[str, Note] = field(default_factory=dict)

    def held(self, note_id: str, kind: str) -> Note | None:
        """Что лежит на месте заметки или файла задачи сейчас."""
        return (self.files if kind == "issue" else self.catalog.notes).get(note_id)

    def path(self, note_id: str, kind: str) -> Path:
        """Где файл: прочитанный — там, откуда прочли, новый — на своём месте."""
        held = self.held(note_id, kind) or Note(note_id, kind, "")
        if kind == "issue" and self.issues is not None:
            return issue_files.path_of(self.issues, held)
        return path_of(self.root, held)


def file_text(note: Note) -> str:
    return issue_files.rendered(note) if note.type == "issue" else rendered(note)


def question_key(question: OpenQuestion) -> str:
    if question.source == "user" and question.source_question_id is not None:
        return f"q:F{question.source_question_id}"
    return f"q:{same_question(question.text)}"


def option_key(option: Mapping[str, object]) -> str:
    """Чем вариант узнают при повторной выгрузке: фрагмент — номером, остальные — формулировкой,
    правка — исходным вариантом (key)."""
    if "key" in option:
        return str(option["key"])
    identifier = str(option["id"])
    return identifier if identifier.startswith("F") else same_question(str(option["text"]))


def options_of(question: OpenQuestion, fragments: Mapping[int, LabeledFragment],
               found: Mapping[str, list[Proposal]], choice: Choice | None = None,
               decision: Decision | None = None) -> list[dict[str, str]]:
    """Варианты вопроса: из текста группы, найденные советом и свой вариант человека. Свой
    вариант — правка другого — встаёт на его место: тот лишь вышел неполным, его никто не
    отклонял. Ключ у правки — исходного (key): его заметку она и продолжит, сколько её ни правь;
    was — ключ её формулировки, если её выгрузили своим вариантом до пометки. Решили всё же
    исходным — остаются оба."""
    options = ([{"id": f"F{i}", "text": fragments[i].text} for i in question.proposal_ids
                if i in fragments]
               + [{"id": p.id, "text": p.text} for p in found.get(question.id, [])])
    if choice is None or choice.text is None or choice.based_on is None:
        return options
    base = choice.based_on
    own = next((option for option in options if option["id"] == choice.proposal), None)
    was = next((option for option in options if option["id"] == base), None)
    if own is None or was is None or (decision is not None and decision.proposal == base):
        return options
    refined = own | {"key": option_key(was), "was": option_key(own)}
    return [refined if option is was else option for option in options if option is not own]


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
                 words: Mapping[str, str]) -> str:
    lines = [title.strip(), "", behavior.strip()]
    if criteria:
        lines += ["", f"{words['criteria']}:", *(f"- {criterion(item)}" for item in criteria)]
    return "\n".join(lines)


def criterion(item: str) -> str:
    """Критерий готовности строкой списка — никогда не строкой задачи. «- ISS-0042: …» под
    критериями итога без задач — последним блоком — прочли бы задачей итога, а подпись
    критериев на языке заметок узнать нельзя: двоеточие после номера — тире. Перевод строк
    задач не добавит: их сверяет translations."""
    return ISSUE_START.sub(r"\1 —", item, count=1) if ISSUE_START.match(item) else item


def parts_of(stream: Stream, fragments: Mapping[int, LabeledFragment], catalog: Catalog,
             words: Mapping[str, str]
             ) -> tuple[list[Part], list[str], dict[str, str], dict[str, dict[str, str]]]:
    """Части потока в порядке заметок: идея, вопросы, варианты, решения, итоги. И что не
    выгружается — с причиной, и какой частью ложится всё, что тексты потока называют его
    номерами: идея (I1), вопрос, вариант (Pn и Fn), решение (ADR-n), итог (O1). По ним план
    задач называет итоги и решения номерами заметок, а тексты заметок и задач — всё остальное.
    Фрагмент текста группы бывает вариантом нескольких вопросов: «F3» в решении вопроса — его
    вариант, а вне вопросов такой номер ничей. Потому и номера вариантов у частей каждого
    вопроса — по ключу части."""
    found = found_by_question(stream.proposals, stream.choices)
    choices = {choice.question_id: choice for choice in stream.choices or []}
    decisions = {decision.question_id: decision for decision in stream.decisions or []}
    questions: list[Part] = []
    proposals: list[Part] = []
    adrs: list[Part] = []
    adr_of: dict[str, str] = {}          # ADR-n потока → ключ части
    named: dict[str, str] = {"I1": "idea"}
    local: dict[str, dict[str, str]] = {}  # ключ части → номера вариантов её вопроса
    offered_in: Counter[str] = Counter()   # у скольких вопросов такой вариант
    external: set[str] = set()           # решения вопросов, что растут из прошлых решений
    taken: set[str] = set()
    for n, question in enumerate(stream.scope or [], 1):
        decision = decisions.get(question.id)
        choice = choices.get(question.id)
        options = options_of(question, fragments, found, choice, decision)
        asked, offered, adr = question_parts(question, options, decision, catalog, words, taken)
        questions.append(asked)
        proposals += offered
        named[question.id] = asked.key
        if question.source == "user" and question.source_question_id is not None:
            # Вопрос из текста группы называют и номером его фрагмента.
            named.setdefault(f"F{question.source_question_id}", asked.key)
        own = {option["id"]: part.key for option, part in zip(options, offered, strict=True)}
        if choice is not None and choice.based_on is not None and choice.proposal in own:
            # Правка встала на место исходного: текст, что называет исходный, — о ней.
            own.setdefault(choice.based_on, own[choice.proposal])
        offered_in.update(own.keys())
        for name, key in own.items():
            named.setdefault(name, key)
        for part in (asked, *offered, *([adr] if adr is not None else [])):
            local[part.key] = own
        if adr is not None:
            adrs.append(adr)
            adr_of[f"ADR-{n}"] = adr.key
            if asked.links != ("idea",):
                external.add(adr.key)
    for name, count in offered_in.items():
        if count > 1:
            named.pop(name, None)
    outcomes, skipped, outcome_of = outcome_parts(stream, adr_of, external, words, taken)
    return ([Part("idea", "idea", stream.idea.text, ()), *questions, *proposals, *adrs,
             *outcomes], skipped, named | adr_of | outcome_of, local)


def stream_texts(stream: Stream, fragments: Mapping[int, LabeledFragment]) -> dict[str, str]:
    """Что значит номер потока, если заметки у него нет: идея, фрагмент текста группы, находка
    скана репозитория или макета, вопрос, вариант, итог."""
    texts = {"I1": stream.idea.text} if stream.idea is not None else {}
    texts |= {f"F{i}": fragment.text for i, fragment in fragments.items()}
    for scan in (stream.scan, stream.design_scan):
        if scan is not None and scan.result is not None:
            texts |= {finding.id: finding.statement for finding in scan.result.findings}
    questions = [*(stream.questions.questions if stream.questions else []), *(stream.scope or [])]
    # Как вопрос лёг в заметку (question_parts): его формулировка, а нет её — текст. И номер
    # фрагмента вопроса из текста группы — о нём же.
    texts |= {question.id: question.note or question.text for question in questions}
    texts |= {f"F{question.source_question_id}": question.note or question.text
              for question in questions
              if question.source == "user" and question.source_question_id is not None}
    texts |= {proposal.id: proposal.text
              for options in found_by_question(stream.proposals, stream.choices).values()
              for proposal in options}
    # Правка встала на место исходного (options_of): за номером исходного — уже её текст.
    decided = {decision.question_id: decision.proposal for decision in stream.decisions or []}
    texts |= {choice.based_on: choice.text for choice in stream.choices or []
              if choice.text is not None and choice.based_on is not None
              and decided.get(choice.question_id) != choice.based_on}
    texts |= {outcome.id: outcome.title
              for outcome in (stream.outcomes.outcomes if stream.outcomes else [])}
    return texts


def decision_texts(stream: Stream) -> list[str]:
    """Тексты отобранных для потока решений проекта: идея, вопрос, решение — из каталога."""
    return [text for decision in stream.project_decisions or []
            for text in (decision.idea, decision.question, decision.decision)]


def terms_of(stream: Stream, cited: Collection[str] = ()) -> frozenset[str]:
    """Номера, которых не трогают нигде: решения проекта — отобранное для потока, те, что
    называет проза отобранных, и те, что называют исходные тексты (cited_in), — без нулей в
    номере (ADR-0001 — «ADR-1»). Каталог зовёт решение и так, и «ADR-1» в тексте — не
    обязательно первое решение потока."""
    named = [decision.adr_id for decision in stream.project_decisions or []]
    named += [found for text in decision_texts(stream)
              for found in NUMBER.findall(visible_of(text))]
    named += cited
    return frozenset(f"ADR-{int(found.group(1))}" for name in named
                     if (found := PAST_ADR.fullmatch(name)) is not None)


def note_key(note_id: str) -> tuple[str, int] | str:
    """Номер заметки без нулей: ADR-7 и ADR-0007 — одна заметка."""
    found = re.fullmatch(r"([A-Za-z]+)-0*(\d+)", note_id)
    return (found.group(1).upper(), int(found.group(2))) if found else note_id


def originals_of(stream: Stream, fragments: Mapping[int, LabeledFragment]) -> list[str]:
    """Тексты, что старше совета: текст группы и утверждённая идея."""
    return [*(fragment.text for fragment in fragments.values()),
            *([stream.idea.text] if stream.idea is not None else [])]


def scanned_of(stream: Stream) -> tuple[list[str], set[str]]:
    """Что модели потока читают о его сканах — находки и карты целиком (maps_of), — и номера
    этих находок: в этих текстах номер находки — ссылка на неё («R1 validation»)."""
    scans = [scan.result for scan in (stream.scan, stream.design_scan)
             if scan is not None and scan.result is not None]
    statements = [finding.statement for result in scans for finding in result.findings]
    return ([*statements, *maps_of(stream)],
            {finding.id for result in scans for finding in result.findings})


def sources_of(stream: Stream, fragments: Mapping[int, LabeledFragment],
               more: Iterable[str] = ()) -> list[str]:
    """Исходные тексты потока, что старше номеров заметок: текст группы, его утверждённая идея,
    находки и карты сканов репозитория и макета — и more."""
    return [*originals_of(stream, fragments), *scanned_of(stream)[0], *more]


def repository_map(owner: Stream | Research) -> str:
    """Карта утверждённого скана (потока или исследования совета) или «не сканировали»."""
    step, scan = owner.repository, owner.scan
    if step is None or step.by != "scan" or scan is None or scan.run != step.scan_run:
        return context_prompt(None)
    return context_prompt(scan.result, scan.repositories, complete=scan.complete,
                          follow_up=scan.follow_up)


def design_map(owner: Stream | Research) -> str:
    """Описание утверждённого скана макета (потока или исследования совета) или «не смотрели»."""
    step, scan = owner.design, owner.design_scan
    if step is None or step.by != "scan" or scan is None or scan.run != step.scan_run:
        return design_context(None)
    return design_context(scan.result, scan.source, complete=scan.complete,
                          follow_up=scan.follow_up)


def maps_of(owner: Stream | Research) -> list[str]:
    """Что модели читают об утверждённых сканах целиком: карту кода и описание макета — с
    шагами, данными экранов, неясным и противоречиями, а не только находки. Слово оттуда
    («Cloudflare R2») модели могут переписать в свой текст."""
    return [text for text, empty in ((repository_map(owner), context_prompt(None)),
                                     (design_map(owner), design_context(None)))
            if text != empty]


def cited_in(stream: Stream, fragments: Mapping[int, LabeledFragment],
             catalog: Collection[str], before: Collection[str] = ()) -> list[str]:
    """Номера заметок каталога (catalog — номера, что в нём сейчас), которые называет проза
    исходных текстов потока (sources_of): каталог старше совета, и такой номер в них — ссылка,
    а не слово. Запоминают при выгрузке (NotesExport.cited): заметку потом могут удалить. И
    запомненные прошлой выгрузкой (before) — пока текст их называет: удалили заметку с тех
    пор — номер всё ещё ссылка."""
    keys = {note_key(note_id) for note_id in [*catalog, *before]}
    return sorted({found for text in sources_of(stream, fragments)
                   for found in numbers_in_prose(text) if note_key(found) in keys})


def phrases_of(stream: Stream, fragments: Mapping[int, LabeledFragment],
               more: Iterable[str] = (), notes: Iterable[str] = (),
               known: Collection[str] = (), cited: Collection[str] = (),
               local: Collection[str] = ()) -> frozenset[str]:
    """Где в прозе исходных текстов — текста группы, идеи, находок и карт сканов (и more) —
    слово, похожее на номер («F1 score», «Cloudflare R2», «I1 cache», «ADR-9999 fixture»): оно
    с соседним словом. Номера потока, заметок и задач появились позже этих текстов, и в таком
    сочетании слово — их слово, а не ссылка; то же слово в другом месте текста совета — ссылка.
    Кроме номеров заметок каталога, что они называют (cited_in): это ссылки. В текстах скана
    потока ссылка и номер его находки («R1 validation»), а в more (что план читал об
    исследовании совета) — номер находки исследования (local). notes — тексты заметок: в них
    номер известной заметки (known) — настоящая ссылка, и его сочетание словом не становится.
    Тексты отобранных решений проекта — из каталога: там ссылка — любой номер заметки, а слово —
    только номер потока («Q1 reporting»)."""
    found: set[str] = set()
    keys = {note_key(note_id) for note_id in known}
    catalog = {note_key(note_id) for note_id in cited}

    def known_note(name: str) -> bool:
        return note_key(name) in keys

    def cited_note(name: str) -> bool:
        return note_key(name) in catalog

    def any_note(name: str) -> bool:
        return NUMBER.fullmatch(name) is not None

    scanned, findings = scanned_of(stream)

    def scan_note(name: str) -> bool:
        return cited_note(name) or name in findings

    def research_note(name: str) -> bool:
        return cited_note(name) or name in local

    sources: list[tuple[str, Callable[[str], bool] | None]] = [
        (text, cited_note) for text in originals_of(stream, fragments)]
    sources += [(text, scan_note) for text in scanned]
    sources += [(text, research_note) for text in more]
    sources += [(text, known_note) for text in notes]
    sources += [(text, any_note) for text in decision_texts(stream)]
    for source, linked in sources:
        # Соседнее слово — в видимом тексте: «Cloudflare [**R2**](…) storage» — «Cloudflare R2».
        text = visible_of(source)
        for match in WORDLIKE.finditer(text):
            word = match.group(0)
            if linked is not None and linked(word):
                continue
            if (after := re.match(r"[ \t]+(\w+)", text[match.end():])) is not None:
                found.add(f"{word} {after.group(1)}")
            if (before := re.search(r"(\w+)[ \t]+$", text[:match.start()])) is not None:
                found.add(f"{before.group(1)} {word}")
    return frozenset(found)


# Где в env разбора строк прозы копится то, что он нашёл (marking): что не трогать (SPANS) и
# видимый текст (SEEN) — по нему узнают сочетания (phrases_of, in_prose).
SPANS = "spans"
SEEN = "seen"
# Откуда в содержимом блока отсчитаны места того, что читает разбор: подпись картинки он
# читает отдельно, с её начала.
BASES = "bases"
InlineRule = Callable[[StateInline, bool], bool]
# Что не трогать: строка кода, тег HTML (с комментариями и <?…?>), адрес в <…>, адрес и метка
# ссылки и картинки.
PROTECTED = frozenset(("code", "html", "autolink", "link"))
# Видимый текст — слова и знаки (text, literal), экранированный знак (escape), то, что значит
# мнемоника (entity: «&nbsp;» — пробел, «&amp;» — «&»), мягкий перенос строки — пробел. Граница —
# строка кода, адрес в <…> и жёсткий перенос: соседние с ними слова — не сочетание. Прочее —
# теги, разметка ссылок и выделения — прозрачно: «Cloudflare [**R2**](…)» — это «Cloudflare R2».
VISIBLE = frozenset(("text", "literal"))
BORDER = frozenset(("code", "autolink"))
# Теги, что рвут строку: перенос и все блочные элементы CommonMark (block_names: address, div,
# p, li, td…) — граница, а не прозрачная разметка: «Cloudflare<br>R2» — не «Cloudflare R2».
BREAKS = frozenset(("br", *block_names))
TAG_NAME = re.compile(r"</?([A-Za-z][A-Za-z0-9-]*)")


def breaks(tag: str) -> bool:
    """Тег рвёт строку (BREAKS)."""
    found = TAG_NAME.match(tag)
    return found is not None and found.group(1).lower() in BREAKS


def marking(kind: str, rule: InlineRule) -> InlineRule:
    """Правило разбора строк прозы, что отмечает найденное: что не трогать (SPANS в env) и
    видимый текст (SEEN) — где это в содержимом блока. У ссылки и картинки не трогают только
    адрес «](…)» или метку «][…]»: текст ссылки — проза; а если метка — сам текст ([Q1], [Q1][]),
    то весь «[Q1]»."""

    def marked(state: StateInline, silent: bool) -> bool:
        start = state.pos
        bases = state.env.get(BASES)
        image = kind == "link" and state.src[start] == "!"
        if image and bases is not None:
            # Подпись картинки разбор читает отдельно, с её начала: что найдёт там, — от начала
            # подписи (после «![») в содержимом блока.
            bases.append(bases[-1] + start + 2)
        try:
            found = rule(state, silent)
        finally:
            if image and bases is not None:
                bases.pop()
        spans, seen = state.env.get(SPANS), state.env.get(SEEN)
        if not found or silent or spans is None or seen is None or bases is None:
            return found
        end, base = state.pos, bases[-1]
        # Видимое — как есть в тексте (None) или своим текстом: граница — «\n».
        if kind == "escape":
            # «\*» — видимая «*», «\» в конце строки — перенос.
            sign = state.src[start + 1]
            seen.append((base + start, base + end, "\n") if sign == "\n"
                        else (base + start + (sign in string.punctuation), base + end, None))
        elif kind == "entity":
            shown = unescape(state.src[start:end])
            seen.append((base + start, base + end, " " if shown.isspace() else shown))
        elif kind == "newline":
            # Мягкий перенос строки — пробел; жёсткий (два пробела перед ним) — граница.
            hard = state.src[:start].endswith("  ")
            seen.append((base + start, base + end, "\n" if hard else " "))
        elif kind in VISIBLE or kind in BORDER:
            seen.append((base + start, base + end, None if kind in VISIBLE else "\n"))
        elif kind == "html" and breaks(state.src[start:end]):
            seen.append((base + start, base + end, "\n"))
        if kind == "link":
            close = state.md.helpers.parseLinkLabel(state, start + image, not image)
            if close >= 0 and state.src[close + 1:end] not in ("", "[]"):
                start = close
        if kind in PROTECTED:
            spans.append((kind, base + start, base + end))
        return True

    return marked


def literal(state: StateInline, silent: bool) -> bool:
    """Знак, что не взяло ни одно правило, — текстом, как это делает и сам разбор."""
    if not silent:
        state.pending += state.src[state.pos]
    state.pos += 1
    return True


for name, kind, rule in (("text", "text", rules_inline.text),
                         ("newline", "newline", rules_inline.newline),
                         ("escape", "escape", rules_inline.escape),
                         ("backticks", "code", rules_inline.backtick),
                         ("link", "link", rules_inline.link),
                         ("image", "link", rules_inline.image),
                         ("autolink", "autolink", rules_inline.autolink),
                         ("html_inline", "html", rules_inline.html_inline),
                         ("entity", "entity", rules_inline.entity)):
    MARKDOWN.inline.ruler.at(name, marking(kind, rule))
MARKDOWN.inline.ruler.push("literal", marking("literal", literal))


def placed(content: str, rows: Sequence[str]) -> Callable[[int], int]:
    """Место в тексте блока (rows — его строки, от начала первой) по месту в содержимом, что
    видит разбор строк прозы (content): там строки блока без отступа и знаков контейнеров
    («>», «-»), а пробелы табуляции, что разбор дописал от себя, — в начале своей строки."""
    inners: list[int] = []
    marks: list[tuple[int, int]] = []
    inner = outer = 0
    for row, piece in zip(rows, content.split("\n"), strict=False):
        bare = piece if piece in row else piece.lstrip(" ")
        inners.append(inner)
        marks.append((outer + max(row.rfind(bare), 0), len(piece) - len(bare)))
        inner += len(piece) + 1
        outer += len(row) + 1

    def place(at: int) -> int:
        n = max(bisect_right(inners, at) - 1, 0)
        mark, extra = marks[n]
        return mark + max(at - inners[n] - extra, 0)

    return place


Marked = dict[int, list[tuple[str, int, int]]]
Seen = dict[int, list[tuple[int, str]]]
# Строки блока HTML в in_prose: проза в них — видимый текст, а их теги ищет и raw_elements.
HTML = -2
# Что в блоке HTML целое, по правилам CommonMark: комментарий, инструкция, CDATA, объявление,
# тег с атрибутами. «<code>» в комментарии или в значении атрибута — не тег.
HTML_PIECE = re.compile("|".join((html_re.comment, html_re.processing, html_re.cdata,
                                  html_re.declaration, html_re.open_tag, html_re.close_tag)))


class Blocks(NamedTuple):
    """Текст по разбору Markdown (blocks_of)."""

    # Строки (с нуля), что занимают блоки кода и HTML на любой глубине и определения
    # ссылок-сносок.
    code: set[int]
    # Строки прозы (абзаца, заголовка) — с номером их блока.
    prose: dict[int, int]
    # Что разбор строк нашёл в каждом блоке прозы (marking): что не трогать и видимый текст —
    # по знаку с его местом («\n» — граница). Место — от начала первой строки блока.
    marked: Marked
    seen: Seen
    # Из строк кода — строки блоков HTML: их теги — настоящие.
    html: set[int]


def blocks_of(text: str) -> Blocks:
    """Разбор текста как Markdown: где код, где проза и что в ней (Blocks)."""
    env: dict = {}
    tokens = MARKDOWN.parse(text, env)
    lines = {n for token in tokens if token.type in BLOCKS and token.map
             for n in range(*token.map)}
    html = {n for token in tokens if token.type == "html_block" and token.map
            for n in range(*token.map)}
    lines |= {n for found in [*env.get("references", {}).values(), *env.get("duplicate_refs", [])]
              if found.get("map") for n in range(*found["map"])}
    rows = text.split("\n")
    prose: dict[int, int] = {}
    marked: Marked = {}
    seen: Seen = {}
    for block, token in enumerate(tokens):
        if token.type != "inline" or not token.map:
            continue
        first, last = token.map
        prose.update(dict.fromkeys(range(first, last), block))
        spans: list[tuple[str, int, int]] = []
        shown: list[tuple[int, int, str | None]] = []
        MARKDOWN.inline.parse(token.content, MARKDOWN,
                              {**env, SPANS: spans, SEEN: shown, BASES: [0]}, [])
        place = placed(token.content, rows[first:last])
        marked[block] = [(kind, place(start), place(end)) for kind, start, end in spans]
        # Пробел Юникода (неразрывный и прочие) — пробел: так «Cloudflare R2» узнаётся и с ним.
        seen[block] = [(at, spaced(sign)) for start, end, text in
                       sorted(shown, key=lambda found: found[0])
                       for at, sign in ([(place(at), token.content[at])
                                         for at in range(start, end)]
                                        if text is None else [(place(start), sign)
                                                              for sign in text])]
    return Blocks(lines, prose, marked, seen, html)


def block_starts(text: str, blocks: Blocks) -> dict[int, int]:
    """Где в тексте начинается каждый блок прозы — от него места в Blocks.marked и seen."""
    offsets = list(accumulate((len(row) + 1 for row in text.split("\n")), initial=0))
    starts: dict[int, int] = {}
    for n, block in sorted(blocks.prose.items()):
        starts.setdefault(block, offsets[n])
    return starts


def html_runs(text: str, blocks: Blocks) -> list[tuple[int, int]]:
    """Где в тексте блоки HTML — подряд идущие их строки одним куском."""
    offsets = list(accumulate((len(row) + 1 for row in text.split("\n")), initial=0))
    runs = [[n for _, n in run] for _, run in
            groupby(enumerate(sorted(blocks.html)), key=lambda item: item[1] - item[0])]
    return [(offsets[run[0]], offsets[run[-1] + 1] - 1) for run in runs]


def elements_of(text: str, blocks: Blocks) -> list[tuple[int, int]]:
    """Элементы кода HTML во всём тексте (raw_elements) — по тегам прозы и блоков HTML: <script>
    идёт и через пустую строку, а «</script>» в блоке HTML закрывает элемент абзаца выше."""
    starts = block_starts(text, blocks)
    tags = [(kind, starts[block] + start, starts[block] + end)
            for block, found in blocks.marked.items() for kind, start, end in found]
    tags += [("html", *piece.span()) for start, end in html_runs(text, blocks)
             for piece in HTML_PIECE.finditer(text, start, end)]
    return raw_elements(text, tags)


def visible_of(text: str) -> str:
    """Видимый текст прозы (blocks_of): без кода (и элементов кода HTML: <code>, <pre>…),
    адресов, тегов и разметки ссылок и выделения; блоки и строки кода — через перенос строки. И
    текст блоков HTML — так же. В нём сочетание исходного текста — его слово: `Q1` в коде — не
    его слово, а «Cloudflare [R2](…)» и «<div>Cloudflare R2</div>» — «Cloudflare R2»."""
    blocks = blocks_of(text)
    elements = elements_of(text, blocks)
    starts = block_starts(text, blocks)
    shown = ["".join("\n" if inside(starts[block] + at, elements) else sign
                     for at, sign in signs) for block, signs in blocks.seen.items()]
    shown += [spaced("".join(sign for _, sign in html_signs(text, start, end, elements)))
              for start, end in html_runs(text, blocks)]
    return "\n".join(shown)


def spaced(text: str) -> str:
    """Пробел Юникода (неразрывный и прочие) — пробел, перенос строки — как есть."""
    return re.sub(r"[^\S\n]", " ", text)


def html_signs(text: str, start: int, end: int,
               elements: Iterable[tuple[int, int]]) -> list[tuple[int, str]]:
    """Видимый текст блока HTML (text[start:end]) — по знаку с его местом: тег и комментарий
    прозрачны, а тег, что рвёт строку (BREAKS), и элемент кода (elements) — граница «\n»."""
    drops = sorted([(max(begin, start), min(close, end), "\n") for begin, close in elements
                    if begin < end and close > start]
                   + [(*piece.span(), "\n" if breaks(piece.group(0)) else "")
                      for piece in HTML_PIECE.finditer(text, start, end)],
                   key=lambda drop: (drop[0], -drop[1]))
    signs: list[tuple[int, str]] = []
    last = start
    for begin, close, border in drops:
        if begin >= last:
            signs += decoded(text, last, begin)
            signs += [(begin, border)] if border else []
        last = max(last, close)
    return signs + decoded(text, last, end)


# Мнемоника HTML: «&nbsp;», «&#160;», «&#xA0;».
ENTITY = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


def decoded(text: str, start: int, end: int) -> list[tuple[int, str]]:
    """Знаки text[start:end] с их местами, мнемоника — тем, что она значит (пробельная —
    пробелом), на месте её начала."""
    signs: list[tuple[int, str]] = []
    last = start
    for entity in ENTITY.finditer(text, start, end):
        shown = unescape(entity.group(0))
        signs += [(at, text[at]) for at in range(last, entity.start())]
        signs += [(entity.start(), " " if shown.isspace() else sign) for sign in shown]
        last = entity.end()
    return signs + [(at, text[at]) for at in range(last, end)]


def inside(at: int, spans: Iterable[tuple[int, int]]) -> bool:
    """Место at — внутри одного из spans."""
    return any(start <= at < end for start, end in spans)


def raw_elements(text: str, found: Iterable[tuple[str, int, int]]) -> list[tuple[int, int]]:
    """Где в тексте элемент HTML, чьё содержимое — код (RAW), — с вложенными в него такими же:
    <code>…<code>…</code>…</code> — одно целое. Теги — те, что нашёл разбор (found, «html»):
    <code> в строке кода или в атрибуте — не тег; в сыром тексте (RAW_TEXT:
    <script>"<script>"</script>) тег — текст; незакрытый элемент — не элемент."""
    elements: list[tuple[int, int]] = []
    start = None
    names: list[str] = []
    for kind, begin, end in sorted(found, key=lambda span: span[1]):
        tag = RAW_TAG.fullmatch(text, begin, end) if kind == "html" else None
        if tag is None or (names and names[-1] in RAW_TEXT and tag.group("open")):
            continue
        if tag.group("open"):
            if not names:
                start = begin
            names.append(tag.group("open").lower())
        elif names and tag.group("close").lower() == names[-1]:
            names.pop()
            if not names and start is not None:
                elements.append((start, end))
    return elements


def addresses(text: str, opaque: Collection[tuple[int, int]] = (),
              parsed: Collection[tuple[int, int]] = ()) -> list[tuple[int, int]]:
    """Где в тексте адрес сам по себе («https://…»): до пробела или «<», «>», «]», со скобками
    внутри любой вложенности; «)» в конце, которой нет пары, и знак препинания в конце — не
    адрес. Адрес, что начат в том, что не трогают (opaque: код, тег), — не адрес; то, что нашёл
    разбор (parsed: код, тег, ссылка), его обрывает: `https://host`/Q1."""
    found: list[tuple[int, int]] = []
    for scheme in SCHEME.finditer(text):
        if inside(scheme.start(), opaque):
            continue
        stop = min((start for start, _ in parsed if start > scheme.start()), default=len(text))
        end = scheme.end()
        # Адрес узла IPv6 — в квадратных скобках сразу после «://»: «]» его не обрывает.
        close = text.find("]", end, stop) if text.startswith("[", end) else -1
        if close != -1 and not any(sign.isspace() for sign in text[end:close]):
            end = close + 1
        while end < stop and not text[end].isspace() and text[end] not in "<>]":
            end += 1
        while end > scheme.end() and (
                text[end - 1] in ".,;:!?'\""
                or (text[end - 1] == ")"
                    and text.count(")", scheme.start(), end)
                    > text.count("(", scheme.start(), end))):
            end -= 1
        if end > scheme.end():
            found.append((scheme.start(), end))
    return found


def in_prose(text: str, change: Callable[[str], str], keep: Collection[str] = ()) -> str:
    """Текст, где change — только в прозе: блоки кода на любой глубине и определения
    ссылок-сносок (их строки — по разбору Markdown); в строках прозы — что нашёл их разбор
    (marking: строки кода, теги, адреса и метки ссылок), почта (UNTOUCHED) и адреса сами по
    себе, элементы кода (raw_elements) и сочетания keep («F1 score») — как есть. В блоке HTML
    проза — его видимый текст, а теги, комментарии и элементы кода — как есть."""
    blocks = blocks_of(text)
    code, prose, marked, seen, html = blocks
    lines = [f"{row}\n" for row in text.split("\n")]
    lines[-1] = lines[-1][:-1]
    # Сочетание — его слова через пробелы в видимом тексте прозы: разметка ссылок и выделения
    # и теги между ними прозрачны — «Cloudflare R2» и в «Cloudflare [**R2**](…)».
    # Сочетание — целыми словами: «I1 cache» — не начало «I1 cacheable».
    words = [r"(?<!\w)" + r"[ \t]+".join(map(re.escape, phrase.split())) + r"(?!\w)"
             for phrase in sorted(keep, key=len, reverse=True) if phrase.split()]
    phrases = re.compile("|".join(words)) if words else None

    def kept(signs: list[tuple[int, str]]) -> list[tuple[int, int]]:
        """Где в тексте блока сочетания keep: от места первого знака до места последнего."""
        if phrases is None:
            return []
        shown = "".join(sign for _, sign in signs)
        return [(signs[found.start()][0], signs[found.end() - 1][0] + 1)
                for found in phrases.finditer(shown) if found.end() > found.start()]

    def block(item: tuple[int, str]) -> int | None:
        """Строка блока HTML — HTML, прочего кода — None (как есть), прозы — номер её блока
        (абзаца, заголовка), прочие — -1: ссылка и строка кода не выходят за свой блок, «[»
        абзаца над заголовком — не начало ссылки в нём."""
        if item[0] in html:
            return HTML
        return None if item[0] in code else prose.get(item[0], -1)

    groups = [(key, "".join(row for _, row in rows))
              for key, rows in groupby(enumerate(lines), key=block)]
    starts = list(accumulate((len(part) for _, part in groups), initial=0))
    elements = elements_of(text, blocks)

    def inline(part: str, key: int, at: int) -> str:
        # Что не трогают — может пересекаться. В блоке HTML — теги и комментарии, а видимый
        # текст в нём — проза, как и в абзаце.
        if key == HTML:
            parsed = [piece.span() for piece in HTML_PIECE.finditer(part)]
            signs = [(place - at, spaced(sign))
                     for place, sign in html_signs(text, at, at + len(part), elements)]
        else:
            parsed = [(start, end) for _, start, end in marked.get(key, [])]
            signs = seen.get(key, [])
        opaque = parsed + [found.span() for found in UNTOUCHED.finditer(part)] + kept(signs)
        raw = [(max(start, at) - at, min(end, at + len(part)) - at)
               for start, end in elements if start < at + len(part) and end > at]
        merged: list[list[int]] = []
        for start, end in sorted(opaque + addresses(part, opaque, parsed) + raw):
            if merged and start < merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        if MASKED.search(part) or len(merged) > 0xFFFD:
            # Знаки MASKED уже есть в тексте — change получает прозу по кускам.
            out: list[str] = []
            last = 0
            for start, end in merged:
                out += [change(part[last:start]), part[start:end]]
                last = end
            return "".join([*out, change(part[last:])])
        # change видит блок целиком — «([F3](…))» для него скобки с одним номером, — а то, что
        # не трогают, спрятано за знаками MASKED и встаёт на место после.
        hidden = [part[start:end] for start, end in merged]
        bounds = [0, *(edge for span in merged for edge in span), len(part)]
        masked = "".join(part[bounds[2 * n]:bounds[2 * n + 1]] + chr(MASK + n)
                         for n in range(len(merged))) + part[bounds[-2]:]
        return MASKED.sub(lambda found: hidden[ord(found.group(0)) - MASK], change(masked))

    return "".join(part if key is None else inline(part, key, start)
                   for (key, part), start in zip(groups, starts, strict=False))


def numbers_in_prose(text: str, keep: Collection[str] = ()) -> list[str]:
    """Номера заметок и задач в прозе: в коде, адресах ссылок и сочетаниях keep (in_prose)
    номер — не ссылка."""
    found: list[str] = []

    def collect(part: str) -> str:
        found.extend(NUMBER.findall(part))
        return part

    in_prose(text, collect, keep)
    return found


def renumbered(text: str, numbers: Mapping[str, str], texts: Mapping[str, str],
               quote: str = "«{}»", terms: Collection[str] = (),
               phrases: Collection[str] = ()) -> str:
    """Номера потока в тексте — номерами заметок: в документации Q1, P11 и F3 ничего не
    значат. У чего заметки нет (ограничение из текста группы, находка скана), номер в скобках
    выпадает — фраза его и так пересказывает, — а посреди фразы встаёт сам текст в кавычках
    (quote). Номера заметок и незнакомые — как есть; код, адреса и метки ссылок (in_prose),
    сочетания исходных текстов (phrases_of) и двусмысленные номера (terms_of) — тоже. Текст за
    номером — и сам с номерами заметок; номер в своём же тексте (и в тексте, что его назвал) — как
    есть: ссылки по кругу не размотать."""
    numbers = {name: number for name, number in numbers.items() if name not in terms}
    texts = {name: value for name, value in texts.items() if name not in terms}

    def number(match: re.Match[str]) -> str:
        return numbers.get(match.group(0), match.group(0))

    def quoted(match: re.Match[str]) -> str:
        name = match.group(0)
        if name in numbers or name not in texts:
            return numbers.get(name, name)
        rest = {other: value for other, value in texts.items() if other != name}
        inner = renumbered(texts[name], numbers, rest, quote, terms, phrases)
        return quote.format(" ".join(inner.split()).rstrip(".!"))

    def prose(text: str) -> str:
        out: list[str] = []
        last = 0
        for match in CITED.finditer(text):
            names = re.findall(CITED_NUMBER, match.group(0))
            kept = [numbers.get(name, name) for name in names
                    if name in numbers or name not in texts]
            head = text[last:match.start()]
            if not kept:
                out.append(head.rstrip(" "))
            elif len(kept) == len(names):
                out += [head, LOCAL.sub(number, match.group(0))]
            else:
                out += [head, f"({', '.join(kept)})"]
            last = match.end()
        out.append(text[last:])
        return LOCAL.sub(quoted, "".join(out))

    return in_prose(text, prose, phrases)


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
        # Правку могли выгрузить своим вариантом прежде, чем отметили, что она правит.
        was = f"p:{key[2:]}:{option['was']}" if "was" in option else None
        offered.append(Part(option_part, "proposal", option["text"], (key,), was))
        if decision is not None and decision.proposal == option["id"]:
            adr = Part(f"a:{option_part[2:]}", "adr",
                       because(option["text"], decision.rationale, words), (option_part,),
                       f"a:{was[2:]}" if was else None)
    return asked, offered, adr


def outcome_parts(stream: Stream, adr_of: Mapping[str, str], external: set[str],
                  words: Mapping[str, str], taken: set[str]
                  ) -> tuple[list[Part], list[str], dict[str, str]]:
    """Итоги, что лягут, — и ключ части каждого. Итог ссылается только на решения своей идеи:
    без них он не выгружается."""
    parts: list[Part] = []
    skipped: list[str] = []
    outcome_of: dict[str, str] = {}
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
        text = outcome_text(outcome.title, outcome.behavior, outcome.acceptance_criteria, words)
        parts.append(Part(key, "outcome", text, tuple(dict.fromkeys(own))))
        outcome_of[outcome.id] = key
    return parts, skipped, outcome_of


def digest_of(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def drafted(stream: Stream, fragments: Mapping[int, LabeledFragment], shelf: Shelf,
            previous: NotesExport | None, words: Mapping[str, str],
            language: str, reserved: Collection[str] = ()
            ) -> tuple[list[NotePlan], list[VanishedNote], list[str], dict[str, str]]:
    """Черновик выгрузки: заметки с номерами, текстом и тем, что с ними будет; исчезнувшие; что
    не выгружается; номер заметки у всего, что тексты потока называют его номерами (parts_of).
    language — язык заметок: не тот, что у прошлой выгрузки, — прежние тексты не берутся, их
    напишет перевод заново (файлы, правленные руками, — нет). reserved — номера
    заметок из выгрузок других потоков: их заметку могли удалить руками, но номер всё ещё их —
    новой заметке его не дают, а прежний номер потока, который записан и за другим, — уже не
    его."""
    catalog = shelf.catalog
    parts, skipped, named, local = parts_of(stream, fragments, catalog, words)
    before = {note.key: note for note in previous.notes if note.type != "issue"} if previous else {}
    alias = matched([part.key for part in parts], before)
    # Правка, которую выгрузили своим вариантом до пометки, а заметки исходного уже нет, —
    # продолжает свою прежнюю заметку.
    claimed = set(alias.values())
    for part in parts:
        if part.key not in alias and part.was in before and part.was not in claimed:
            alias[part.key] = part.was
            claimed.add(part.was)
    olds = {key: before[was] for key, was in alias.items()}
    reuse = previous is not None and previous.language == language
    ids: dict[str, str] = {}
    for part in parts:
        old = olds.get(part.key)
        held = catalog.notes.get(old.id) if old else None
        # Прежний номер — если он всё ещё наш: заметка с ним того же типа, а нет её — файл
        # с этим именем свободен (в него не переименовали чужую) и номер не за другим потоком.
        if old and old.type == part.type and old.id not in reserved and (
                held.type == part.type if held is not None
                else catalog.occupant(old.id) is None):
            ids[part.key] = old.id
    for part in parts:
        if part.key not in ids:
            ids[part.key] = catalog.next_id(part.type, taken=[*ids.values(), *reserved])
    numbers = {name: ids[key] for name, key in named.items()}
    texts = stream_texts(stream, fragments)
    cited = cited_in(stream, fragments, catalog.notes, previous.cited if previous else ())
    terms, phrases = terms_of(stream, cited), phrases_of(stream, fragments, cited=cited)

    def numbered(part: Part) -> dict[str, str]:
        """Номера для текста части: в вопросе — и варианты этого вопроса (parts_of)."""
        return numbers | {name: ids[key] for name, key in local.get(part.key, {}).items()}

    def renumber(part: Part, text: str) -> str:
        return renumbered(text, numbered(part), texts, words["quote"], terms, phrases)

    notes = [planned(numbered_part, ids,
                     migrated(olds.get(part.key), numbered_part.text, partial(renumber, part)),
                     alias.get(part.key), shelf, reuse)
             for part in parts
             for numbered_part in [replace(part, text=renumber(part, part.text))]]
    ours = {note.id for note in notes} | {note.id for note in before.values()}
    vanished = [VanishedNote(id=old.id, type=old.type, text=catalog.notes[old.id].body,
                             linked_from=sorted(note.id for note in catalog.notes.values()
                                                if old.id in note.links and note.id not in ours))
                for key, old in before.items()
                if key not in claimed and old.id in catalog.notes and old.id not in reserved]
    return notes, vanished, skipped, numbers


def migrated(old: ExportedNote | None, text: str,
             renumber: Callable[[str], str] | None) -> ExportedNote | None:
    """Прежняя запись — как её сделали бы сейчас, если совет написал бы то же (text): запись до
    номеров заметок (без note_numbers) хранит в текстах номера потока (Q1), и правку человека
    повторная выгрузка терять не должна. Номер потока в правке — тоже номером заметки
    (renumber), и тогда, когда в тексте совета его не было. В нынешней записи «Q1» в правке —
    слово человека."""
    if old is None or renumber is None:
        return old
    same = old.generated == text
    if (same and old.note_numbers) or (not same and renumber(old.generated) != text):
        return old
    return old.model_copy(update={"generated": text, "written": renumber(old.written)})


def planned(part: Part, ids: Mapping[str, str], old: ExportedNote | None, was: str | None,
            shelf: Shelf, reuse: bool) -> NotePlan:
    note_id = ids[part.key]
    links = [ids.get(link, link) for link in part.links]
    text = old.written if old and reuse and old.generated == part.text else part.text
    plan = NotePlan(key=part.key, id=note_id, type=part.type, text=text, generated=part.text,
                    links=links, action="create", was=was)
    return settled(plan, old, shelf)


def export_in(record: NotesExport | None, root: Path | None) -> NotesExport | None:
    """Выгрузка потока — если она в этот каталог. В другой (проект или его папку сменили) — её
    номера здесь ничего не значат: под ними тут чужие заметки. Файлы задач, что выгружали
    раньше вместе с потоком, ему больше не принадлежат: их выгружает этап «Задачи»."""
    if record is None or root is None or record.root != str(root):
        return None
    if any(note.type == "issue" for note in record.notes):
        return record.model_copy(update={
            "notes": [note for note in record.notes if note.type != "issue"]})
    return record


def previous_of(plan: NotePlan, before: Mapping[str, ExportedNote]) -> ExportedNote | None:
    """Прежняя выгрузка заметки, которую продолжает plan."""
    return before.get(plan.was) if plan.was else None


def settled(plan: NotePlan, old: ExportedNote | None, shelf: Shelf) -> NotePlan:
    """Что будет с заметкой (или файлом задачи) при записи — по тому, что лежит там сейчас."""
    held = shelf.held(plan.id, plan.type)
    if held is None:
        return plan.model_copy(update={"action": "create", "current": None})
    path = shelf.path(plan.id, plan.type)
    if old is not None and digest_of(path) != old.digest:
        return plan.model_copy(update={"action": "edited", "current": held.body})
    if held.body == plan.text.strip() and list(held.links) == plan.links:
        return plan.model_copy(update={"action": "same", "current": None})
    return plan.model_copy(update={"action": "update", "current": held.body})


def written(notes: Sequence[NotePlan], vanished: Sequence[VanishedNote],
            edits: Mapping[str, str], delete: Sequence[str], shelf: Shelf,
            previous: NotesExport | None,
            keep: Callable[[list[ExportedNote]], None] | None = None) -> list[ExportedNote]:
    """Записывает подтверждённое: заметки с правками человека (edits — по ключу), удаляет
    отмеченные исчезнувшие. Файлы, правленные руками, — не трогает. Вернёт, что выгружено, —
    и исчезнувшие, что человек оставил в каталоге: они всё ещё потока.

    Сначала номера в правках и пустой текст, потом временные файлы, подмена и удаление одним
    шагом с откатом (committed), потом keep — запись о выгрузке. Отказ на любом шаге, и в keep
    тоже, вернёт каталог (и папку задач) как был: файлы и запись о них не разойдутся. Заметка
    из каталога — там, где лежит."""
    where = shelf.path
    gone = deletable(vanished, delete)
    before = {note.key: note for note in previous.notes} if previous else {}
    # Какие номера — заметки: каталога и те, что ложатся сейчас.
    catalog = {note_key(note_id) for note_id in [*shelf.catalog.notes, *(p.id for p in notes)]}
    texts = {plan.key: edits.get(plan.key, plan.text).strip() for plan in notes
             if plan.action != "edited"}
    empty = [plan.id for plan in notes if texts.get(plan.key) == ""]
    if empty:
        raise NotesError(f"У заметки {empty[0]} пустой текст")
    numbered_edits(notes, edits, texts)
    changed = [plan for plan in notes if plan.action != "edited"
               and (plan.action != "same" or texts[plan.key] != plan.text.strip())]
    staged: list[tuple[Path, Path]] = []
    try:
        for plan in changed:
            path = where(plan.id, plan.type)
            note = Note(plan.id, plan.type, texts[plan.key], tuple(plan.links))
            staged.append((staged_file(path, file_text(note)), path))
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
            # Ссылка — номер, что сейчас в каталоге, или тот, что запомнила прошлая запись этой
            # заметки (заметку с тех пор могли удалить), — пока текст его называет.
            old = before.get(plan.was or plan.key)
            remembered = {note_key(found) for found in old.references} if old else set()
            references = sorted({found for found in numbers_in_prose(texts[plan.key])
                                 if note_key(found) in catalog | remembered})
            exported.append(ExportedNote(key=plan.key, id=plan.id, type=plan.type,
                                         generated=plan.generated, written=texts[plan.key],
                                         links=plan.links,
                                         digest=digest_of(where(plan.id, plan.type)),
                                         note_numbers=True, references=references))
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
        # Файл задачи — не заметка графа.
        if plan.action != "edited" and plan.type != "issue":
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


def portions(notes: Sequence[NotePlan]) -> list[dict[str, str]]:
    """Что переводить, по ходам судьи: заметки — одним, их связки и термины переводятся
    вместе, а файл задачи — каждый своим: задачи длинные, и все разом не влезли бы в один ответ
    модели."""
    sources = untranslated(notes)
    issues = {note.key for note in notes if note.type == "issue"}
    together = {key: text for key, text in sources.items() if key not in issues}
    apart = [{key: text} for key, text in sources.items() if key in issues]
    return [part for part in (together, *apart) if part]


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
        problem = numbering_problem(sources[key], text)
        if problem is not None:
            raise BadAnswer(f"в переводе {key} {problem}")
    return found


def numbered_edits(notes: Sequence[NotePlan], edits: Mapping[str, str],
                   texts: Mapping[str, str]) -> None:
    """Правка человека — с теми же номерами, что и перевод: номер задачи с экрана уже ушёл в
    коммиты, и без строки задачи в итоге у них не было бы следа."""
    for plan in notes:
        if plan.key in edits and plan.key in texts:
            problem = numbering_problem(plan.text, texts[plan.key])
            if problem is not None:
                raise NotesError(f"В правке заметки {plan.id} {problem}")


def numbering_problem(source: str, text: str) -> str | None:
    """Чем текст расходится с исходным в номерах: потерян или лишний номер заметки или задачи,
    не те строки задач итога. Номера держат граф и след в коде: ISS-… в итоге — задача, по нему
    считают след и раздают новые номера. Те же — None."""
    was, now = set(NUMBER.findall(source)), set(NUMBER.findall(text))
    if was - now:
        return f"потеряны номера {', '.join(sorted(was - now))}"
    if now - was:
        return f"лишние номера {', '.join(sorted(now - was))}"
    if declared_issues(source) != declared_issues(text):
        return "строки задач не те: каждая — «- ISS-…: название», как в исходном тексте"
    return None


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
