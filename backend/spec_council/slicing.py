"""Нарезка и разметка: разбор ответов моделей, их проверка и сведение. Без ввода-вывода.

Нарезку сравниваем не по строкам фрагментов, а по границам: позиция, с которой в
исходном тексте начинается очередной фрагмент. Пробел или запятая, отнесённые моделью
к другому фрагменту, нарезку не меняют, а итоговые фрагменты режутся из исходного текста
по границам, поэтому всегда дословны и ничего не теряют.
"""

import json
import re
from dataclasses import dataclass
from itertools import pairwise

LABELS = ("idea", "question", "proposal", "constraint", "risk")

WORD = re.compile(r"\w")
# Открывающие знаки при разрезе уходят к следующему фрагменту: «Главное…», а не «…базы. «».
OPENERS = "«„“\"'([{—–-"


class BadAnswer(ValueError):
    """Ответ модели не годится: не JSON, не та форма, не тот текст."""


class JudgeRejected(ValueError):
    """Судья нарезки по протоколу не принял ни один вариант. Ответ честный — негодны
    кандидаты, и повтор должен спросить участников заново."""


Bounds = tuple[int, ...]


@dataclass(frozen=True)
class SliceOption:
    bounds: Bounds
    reason: str | None


@dataclass(frozen=True)
class LabelOption:
    label: str
    reason: str


@dataclass(frozen=True)
class BoundaryNote:
    """Решение судьи нарезки о спорной границе: «<слева> | <справа>» и почему."""

    left: str
    right: str
    reason: str


def short(text: str, width: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def parse_json(reply: str) -> dict:
    """JSON-объект из ответа. Модели иногда оборачивают его в ```json или пишут текст вокруг."""
    text = reply.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise BadAnswer("в ответе нет JSON") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise BadAnswer(f"JSON не разбирается: {exc}") from None
    if not isinstance(data, dict):
        raise BadAnswer("ответ — не JSON-объект")
    return data


def bounds_of(text: str, fragments: object) -> Bounds:
    """Границы нарезки или BadAnswer, если фрагменты не дословны, не по порядку,
    перекрываются или между ними потерян содержательный текст."""
    if not isinstance(fragments, list) or not fragments:
        raise BadAnswer("нет списка фрагментов")
    position = 0
    starts = []
    for fragment in fragments:
        if not isinstance(fragment, str) or not WORD.search(fragment):
            raise BadAnswer(f"фрагмент без текста: {fragment!r}")
        found = text.find(fragment, position)
        if found < 0:
            raise BadAnswer(
                f"фрагмента нет в тексте дословно или он не по порядку: «{short(fragment)}»"
            )
        if WORD.search(text, position, found):
            raise BadAnswer(f"потерян текст перед «{short(fragment)}»")
        starts.append(WORD.search(text, found).start())
        position = found + len(fragment)
    if WORD.search(text, position):
        raise BadAnswer(f"потерян текст в конце: «{short(text[position:])}»")
    return tuple(starts[1:])


def cut(text: str, bounds: Bounds) -> list[str]:
    """Фрагменты из исходного текста по границам.

    Граница стоит на первой букве следующего фрагмента, а резать надо в промежутке между
    фрагментами. Режем по первому пробельному символу промежутка: закрывающее мысль
    (запятая, точка, скобка) остаётся с предыдущим фрагментом, а маркер списка, кавычка
    или тире после пробела уходят к следующему: «- Первое» / «- Второе». Промежуток без
    пробела отдаёт следующему фрагменту только открывающие знаки.
    """
    edges = [0]
    for bound in bounds:
        gap = bound
        while gap > edges[-1] and not WORD.match(text, gap - 1):
            gap -= 1
        space = next((i for i, char in enumerate(text[gap:bound]) if char.isspace()), None)
        if space is not None:
            edge = gap + space
        else:
            edge = bound
            while edge > gap and text[edge - 1] in OPENERS:
                edge -= 1
        edges.append(edge)
    edges.append(len(text))
    return [text[start:end].strip() for start, end in pairwise(edges)]


def slice_options(text: str, data: dict) -> list[SliceOption]:
    """Варианты нарезки из ответа модели. Негодный вариант отбрасывается, но если
    не годится ни один, ответ считается негодным."""
    options = data.get("options")
    if not isinstance(options, list) or not options:
        raise BadAnswer("нет списка options")
    valid, problems = [], []
    for option in options:
        try:
            if not isinstance(option, dict):
                raise BadAnswer("вариант — не объект")
            reason = option.get("reason")
            valid.append(SliceOption(bounds_of(text, option.get("fragments")),
                                     reason if isinstance(reason, str) and reason else None))
        except BadAnswer as exc:
            problems.append(str(exc))
    if not valid:
        raise BadAnswer(problems[0])
    return valid


def judged_bounds(text: str, data: dict, candidates: list[SliceOption]) -> Bounds:
    """Итог судьи нарезки. Граница, которой нет ни у одного кандидата, — ошибка судьи."""
    status = data.get("status")
    if status == "no_valid_option":
        problem = data.get("problem")
        raise JudgeRejected(f"не принял ни один вариант: {problem or 'без объяснения'}; "
                            "повтор спросит участников заново")
    if status != "ok":
        raise BadAnswer(f"неизвестный status: {status!r}")
    bounds = bounds_of(text, data.get("fragments"))
    known = {bound for option in candidates for bound in option.bounds}
    invented = [bound for bound in bounds if bound not in known]
    if invented:
        raise BadAnswer(f"судья провёл границу, которой не было ни в одном варианте: "
                        f"перед «{short(text[invented[0]:])}»")
    return bounds


def boundary_notes(data: dict) -> list[BoundaryNote]:
    """Пояснения судьи нарезки. Не обязательны: кривая запись пропускается, а не роняет итог,
    и decisions не списком — тоже просто нет пояснений."""
    decisions = data.get("decisions")
    notes = []
    for item in decisions if isinstance(decisions, list) else []:
        if not isinstance(item, dict):
            continue
        boundary, reason = item.get("boundary"), item.get("reason")
        if isinstance(boundary, str) and "|" in boundary and isinstance(reason, str) and reason:
            left, _, right = boundary.partition("|")
            notes.append(BoundaryNote(left.strip(), right.strip(), reason.strip()))
    return notes


# Края цитат судьи сравниваем без пробелов и знаков: «без базы» и «без базы.» — одно.
EDGES = " \t\r\n.,;:!?…—–-«»„“\"'()[]"


def note_places(fragments: list[str], notes: list[BoundaryNote]) -> dict[int, str]:
    """К какому фрагменту (индекс) отнести пояснение. Ищем по паре цитат, а не по одной:
    одна и та же фраза может встретиться в тексте дважды. Не нашлось — пропускается."""
    placed: dict[int, list[str]] = {}
    for note in notes:
        index = boundary_index(fragments, note)
        if index is not None:
            placed.setdefault(index, []).append(note.reason)
    return {index: " ".join(reasons) for index, reasons in placed.items()}


def boundary_index(fragments: list[str], note: BoundaryNote) -> int | None:
    left, right = note.left.strip(EDGES), note.right.strip(EDGES)
    if not left or not right:
        return None
    # Проведённая граница: левая цитата кончает фрагмент, правая начинает следующий.
    for i in range(1, len(fragments)):
        before, after = fragments[i - 1].strip(EDGES), fragments[i].strip(EDGES)
        if before.endswith(left) and after.startswith(right):
            return i
    # Непроведённая: обе цитаты по порядку внутри одного фрагмента.
    for i, fragment in enumerate(fragments):
        at = fragment.find(left)
        if at >= 0 and fragment.find(right, at + len(left)) >= 0:
            return i
    return None


def label_options(data: dict, ids: list[int]) -> dict[int, list[LabelOption]]:
    """Разметка участника: для каждого ID хотя бы один вариант из пяти типов."""
    items = data.get("labels")
    if not isinstance(items, list):
        raise BadAnswer("нет списка labels")
    found: dict[int, list[LabelOption]] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("id") not in ids:
            raise BadAnswer(f"разметка для неизвестного фрагмента: {item!r}"[:200])
        if item["id"] in found:
            raise BadAnswer(f"фрагмент {item['id']} размечен дважды")
        options = item.get("options")
        if not isinstance(options, list) or not options:
            raise BadAnswer(f"у фрагмента {item['id']} нет вариантов")
        found[item["id"]] = [label_of(option, item["id"]) for option in options]
    missing = [i for i in ids if i not in found]
    if missing:
        raise BadAnswer(f"не размечены фрагменты {', '.join(map(str, missing))}")
    return found


def judged_labels(data: dict, ids: list[int]) -> dict[int, LabelOption]:
    """Итог судьи разметки: ровно один тип на каждый спорный ID."""
    items = data.get("labels")
    if not isinstance(items, list):
        raise BadAnswer("нет списка labels")
    found: dict[int, LabelOption] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("id") not in ids:
            raise BadAnswer(f"решение по фрагменту, который судье не давали: {item!r}"[:200])
        if item["id"] in found:
            raise BadAnswer(f"по фрагменту {item['id']} два решения")
        found[item["id"]] = label_of(item, item["id"])
    missing = [i for i in ids if i not in found]
    if missing:
        raise BadAnswer(f"нет решения по фрагментам {', '.join(map(str, missing))}")
    return found


def label_of(item: object, fragment_id: int) -> LabelOption:
    if not isinstance(item, dict) or item.get("label") not in LABELS:
        label = item.get("label") if isinstance(item, dict) else item
        raise BadAnswer(f"у фрагмента {fragment_id} тип не из {', '.join(LABELS)}: {label!r}")
    reason = item.get("reason")
    return LabelOption(item["label"], reason if isinstance(reason, str) else "")


def agreed_label(answers: list[list[LabelOption]]) -> LabelOption | None:
    """Общий тип, если каждый участник видит ровно один вариант и все одинаковые."""
    if all(len(options) == 1 for options in answers) and len({o[0].label for o in answers}) == 1:
        return answers[0][0]
    return None
