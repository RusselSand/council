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
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from itertools import groupby
from pathlib import Path

from markdown_it import MarkdownIt

from . import issue_files
from .models import (
    Choice,
    Decision,
    ExportedNote,
    LabeledFragment,
    NotePlan,
    NotesExport,
    OpenQuestion,
    Proposal,
    Stream,
    VanishedNote,
)
from .notes import Catalog, Note, NotesError, declared_issues, path_of, rendered
from .proposals import found_by_question
from .questions import same_question
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
# списка): их ищет разбор Markdown. Номера в них — не ссылки.
MARKDOWN = MarkdownIt("commonmark")
BLOCKS = ("fence", "code_block", "html_block")


def balanced(plain: str, depth: int = 5) -> str:
    """Знак адреса или (…) с парными скобками внутри — до depth уровней."""
    inner = plain
    for _ in range(depth):
        inner = rf"(?:{plain}|\({inner}*\))"
    return inner


# Атрибуты тега HTML по CommonMark: значение в "…", '…' или без кавычек — «>» в кавычках тег не
# обрывает. И элементы, чьё содержимое — код или сырой текст.
ATTRIBUTES = (r"""(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*"""
              r"""(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*""")
RAW = "code|pre|kbd|samp|tt|var|script|style|textarea"
# Что не трогают в строке текста — номера в нём не ссылки, а текст вокруг остаётся текстом.
UNTOUCHED = re.compile("|".join((
    # строка кода — `…`, ``…`` — до того же числа обратных кавычек, и через перенос, но не пустую
    r"(?<!`)(?P<tick>`+)(?!`)(?:[^\n]|\n(?![ \t]*(?:\n|\Z)))+?(?<!`)(?P=tick)(?!`)",
    # адрес ссылки и картинки [..](адрес "заголовок") — и в <…>, и со скобками внутри, и с
    # экранированными «\(» и «\>»
    rf"\]\(\s*(?:<(?:\\.|[^<>\\\n])*>|{balanced(r'(?:\\.|[^()\s\\])')}*)"
    r"""(?:\s+(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^()\\])*\)))?\s*\)""",
    # <адрес> и <почта>, почта сама по себе
    r"<[A-Za-z][A-Za-z0-9+.-]*:[^>\s]*>",
    r"<?[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*>?",
    # комментарий, инструкция <?…?>, CDATA, объявление <!…> и тег HTML с его атрибутами
    r"<!--[\s\S]*?-->",
    r"<\?[\s\S]*?\?>",
    r"<!\[CDATA\[[\s\S]*?\]\]>",
    r"<![A-Za-z][^>]*>",
    rf"(?i:<(?P<raw>{RAW})\b{ATTRIBUTES}\s*>[\s\S]*?</(?P=raw)\s*>)",
    rf"<[A-Za-z][A-Za-z0-9-]*{ATTRIBUTES}\s*/?>",
    r"</[A-Za-z][A-Za-z0-9-]*\s*>",
    # адрес сам по себе — и со скобками внутри
    rf"\b[A-Za-z][A-Za-z0-9+.-]*://{balanced(r'(?:\\.|[^\s<>()\]\\])')}+",
)), re.MULTILINE)
# Скобки, где одни номера — потока или заметок: «(F3)», «(Q1, F3)», «(R8 и R12)».
CITED_NUMBER = r"(?:(?:IDEA|OQ|PRO|ADR|OUT|ISS)-\d+|[IQPFORD][1-9]\d*)(?![\w-])"
CITED = re.compile(rf"\(\s*{CITED_NUMBER}(?:(?:\s*[,;/]|\s+(?:and|и))\s*{CITED_NUMBER})*\s*\)")
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
             words: Mapping[str, str]) -> tuple[list[Part], list[str], dict[str, str]]:
    """Части потока в порядке заметок: идея, вопросы, варианты, решения, итоги. И что не
    выгружается — с причиной, и какой частью ложится всё, что тексты потока называют его
    номерами: идея (I1), вопрос, вариант (Pn и Fn), решение (ADR-n), итог (O1). По ним план
    задач называет итоги и решения номерами заметок, а тексты заметок и задач — всё остальное."""
    found = found_by_question(stream.proposals, stream.choices)
    choices = {choice.question_id: choice for choice in stream.choices or []}
    decisions = {decision.question_id: decision for decision in stream.decisions or []}
    questions: list[Part] = []
    proposals: list[Part] = []
    adrs: list[Part] = []
    adr_of: dict[str, str] = {}          # ADR-n потока → ключ части
    named: dict[str, str] = {"I1": "idea"}
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
        for option, part in zip(options, offered, strict=True):
            named.setdefault(option["id"], part.key)
        if choice is not None and choice.based_on is not None and choice.proposal in named:
            # Правка встала на место исходного: текст, что называет исходный, — о ней.
            named.setdefault(choice.based_on, named[choice.proposal])
        if adr is not None:
            adrs.append(adr)
            adr_of[f"ADR-{n}"] = adr.key
            if asked.links != ("idea",):
                external.add(adr.key)
    outcomes, skipped, outcome_of = outcome_parts(stream, adr_of, external, words, taken)
    return ([Part("idea", "idea", stream.idea.text, ()), *questions, *proposals, *adrs,
             *outcomes], skipped, named | adr_of | outcome_of)


def stream_texts(stream: Stream, fragments: Mapping[int, LabeledFragment]) -> dict[str, str]:
    """Что значит номер потока, если заметки у него нет: фрагмент текста группы, находка скана
    репозитория или макета, вопрос, вариант, итог."""
    texts = {f"F{i}": fragment.text for i, fragment in fragments.items()}
    for scan in (stream.scan, stream.design_scan):
        if scan is not None and scan.result is not None:
            texts |= {finding.id: finding.statement for finding in scan.result.findings}
    questions = [*(stream.questions.questions if stream.questions else []), *(stream.scope or [])]
    texts |= {question.id: question.text for question in questions}
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


def terms_of(stream: Stream) -> frozenset[str]:
    """Номера, которых не трогают нигде: решение проекта, отобранное для потока, без нулей в
    номере (ADR-0001 — «ADR-1»). Каталог зовёт его и так, и «ADR-1» в тексте — не обязательно
    первое решение потока."""
    return frozenset(f"ADR-{int(found.group(1))}" for decision in stream.project_decisions or []
                     if (found := PAST_ADR.fullmatch(decision.adr_id)) is not None)


def prose_of(text: str) -> str:
    """Только проза текста — без кода, адресов и меток ссылок (in_prose): сочетание исходного
    текста — его слово, только если оно в прозе; `Q1` в коде — не его слово."""
    parts: list[str] = []

    def keep(part: str) -> str:
        parts.append(part)
        return part

    in_prose(text, keep)
    return "\n".join(parts)


def sources_of(stream: Stream, fragments: Mapping[int, LabeledFragment],
               more: Iterable[str] = ()) -> list[str]:
    """Исходные тексты потока: текст группы, его утверждённая идея, тексты отобранных решений
    проекта, находки скана репозитория и макета — и more."""
    sources = [fragment.text for fragment in fragments.values()]
    if stream.idea is not None:
        sources.append(stream.idea.text)
    sources += [text for decision in stream.project_decisions or []
                for text in (decision.idea, decision.question, decision.decision)]
    for scan in (stream.scan, stream.design_scan):
        if scan is not None and scan.result is not None:
            sources += [finding.statement for finding in scan.result.findings]
    return [*sources, *more]


def phrases_of(stream: Stream, fragments: Mapping[int, LabeledFragment],
               more: Iterable[str] = ()) -> frozenset[str]:
    """Где в прозе исходных текстов — текста группы, идеи, отобранных решений проекта,
    находок скана (и more) — слово, похожее на номер («F1 score», «Cloudflare R2», «I1 cache»,
    «ADR-9999 fixture»): оно с соседним словом. Номера потока, заметок и задач появились позже
    этих текстов, и в таком сочетании слово — их слово, а не ссылка; то же слово в другом месте
    текста совета — ссылка."""
    found: set[str] = set()
    for text in map(prose_of, sources_of(stream, fragments, more)):
        for match in WORDLIKE.finditer(text):
            if (after := re.match(r"[ \t]+\w+", text[match.end():])) is not None:
                found.add(text[match.start():match.end() + after.end()])
            if (before := re.search(r"\w+[ \t]+$", text[:match.start()])) is not None:
                found.add(text[before.start():match.end()])
    return frozenset(found)


def in_prose(text: str, change: Callable[[str], str], keep: Collection[str] = ()) -> str:
    """Текст, где change — только в прозе: блоки кода и HTML на любой глубине и определения
    ссылок-сносок (их строки — по разбору Markdown), строки кода, адреса ссылок, теги
    (UNTOUCHED), метки сносок там, где ими пользуются, и сочетания keep («F1 score») — как
    есть."""
    env: dict = {}
    tokens = MARKDOWN.parse(text, env)
    references = env.get("references", {})
    code = {n for token in tokens if token.type in BLOCKS and token.map
            for n in range(*token.map)}
    code |= {n for found in references.values() if found.get("map")
             for n in range(*found["map"])}
    lines = [f"{row}\n" for row in text.split("\n")]
    lines[-1] = lines[-1][:-1]
    # Метка сноски там, где ею пользуются: [..][Q1], [Q1][], [Q1]. Метки сравнивают, как
    # CommonMark: без регистра и с любыми пробелами между словами. [Q1](…) и [Q1][метка] — не
    # сноска Q1: там [Q1] — текст ссылки; \[Q1] — просто текст, а \\[Q1] — снова сноска.
    spelled = {r"\s+".join(map(re.escape, label.split())) for label in references
               if label.split()}
    extra = [re.escape(phrase) for phrase in sorted(keep, key=len, reverse=True)]
    if spelled:
        labels = "|".join(sorted(spelled))
        # Вторая метка полной ссылки [текст][Q1] — сноска, что бы ни шло за ней.
        extra.append(r"(?i:(?<=\])\[\s*(?:" + labels + r")\s*\])")
        extra.append(r"(?i:(?<!\\)(?:\\\\)*\[\s*(?:" + labels + r")\s*\](?!\(|\[(?!\])))")
    untouched = UNTOUCHED
    if extra:
        untouched = re.compile("|".join([UNTOUCHED.pattern, *extra]), UNTOUCHED.flags)

    def inline(part: str) -> str:
        out: list[str] = []
        last = 0
        for kept in untouched.finditer(part):
            out += [change(part[last:kept.start()]), kept.group(0)]
            last = kept.end()
        out.append(change(part[last:]))
        return "".join(out)

    return "".join(
        "".join(row for _, row in rows) if inside else inline("".join(row for _, row in rows))
        for inside, rows in groupby(enumerate(lines), key=lambda item: item[0] in code))


def renumbered(text: str, numbers: Mapping[str, str], texts: Mapping[str, str],
               quote: str = "«{}»", terms: Collection[str] = (),
               phrases: Collection[str] = ()) -> str:
    """Номера потока в тексте — номерами заметок: в документации Q1, P11 и F3 ничего не
    значат. У чего заметки нет (ограничение из текста группы, находка скана), номер в скобках
    выпадает — фраза его и так пересказывает, — а посреди фразы встаёт сам текст в кавычках
    (quote). Номера заметок и незнакомые — как есть; код, адреса и метки ссылок (in_prose),
    сочетания исходных текстов (phrases_of) и двусмысленные номера (terms_of) — тоже."""
    numbers = {name: number for name, number in numbers.items() if name not in terms}
    texts = {name: value for name, value in texts.items() if name not in terms}

    def number(match: re.Match[str]) -> str:
        return numbers.get(match.group(0), match.group(0))

    def quoted(match: re.Match[str]) -> str:
        name = match.group(0)
        if name in numbers or name not in texts:
            return numbers.get(name, name)
        return quote.format(" ".join(texts[name].split()).rstrip(".!"))

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
    parts, skipped, named = parts_of(stream, fragments, catalog, words)
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
    terms, phrases = terms_of(stream), phrases_of(stream, fragments)
    notes = [planned(replace(part, text=renumbered(part.text, numbers, texts, words["quote"],
                                                   terms, phrases)),
                     ids, olds.get(part.key), alias.get(part.key), shelf, reuse)
             for part in parts]
    ours = {note.id for note in notes} | {note.id for note in before.values()}
    vanished = [VanishedNote(id=old.id, type=old.type, text=catalog.notes[old.id].body,
                             linked_from=sorted(note.id for note in catalog.notes.values()
                                                if old.id in note.links and note.id not in ours))
                for key, old in before.items()
                if key not in claimed and old.id in catalog.notes and old.id not in reserved]
    return notes, vanished, skipped, numbers


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
