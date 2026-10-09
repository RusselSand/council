"""Открытые вопросы к идее: разбор ответов моделей, проверка и сведение. Без ввода-вывода.

Вопрос — что неизвестно, ответов в нём нет. Предложения группы связаны с вопросом через
proposal_ids, и только фрагменты-предложения этой группы: чужой или не тот номер просто
отбрасывается, а inferred-вопрос, у которого не осталось ни одной связи, — уже discovered.
Вопросы пользователя — фрагменты типа question — сохраняются дословно: текст берётся из
фрагмента, а не у модели, и судья их не потеряет — пропущенные код вернёт сам. Для заметки у
такого вопроса есть ещё note — та же неопределённость атомарно, одним предложением, без
вариантов внутри: её пишет модель. Вопрос, который пересматривает принятое решение проекта,
называет его в revisits — только из решений, которые человек отобрал для потока.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .ideas import fragment_number, reason_of
from .models import LabeledFragment, OpenQuestion
from .slicing import BadAnswer

QUESTION_MAX = 500
SOURCES = ("user", "inferred", "discovered")


def same_question(text: str) -> str:
    """Что сравнивать: вопросы, разные только пробелами, регистром или знаком в конце, —
    один и тот же вопрос. lower, не casefold: экран сравнивает через toLowerCase — то же
    стандартное приведение, — и отбор после сервера совпадает с тем, что человек видел."""
    return " ".join(text.split()).rstrip(".?!").lower()


@dataclass(frozen=True)
class Candidate:
    text: str
    source: str
    source_question_id: int | None
    proposal_ids: tuple[int, ...]
    reason: str | None
    # Формулировка для заметки — у вопроса из текста; и какое принятое решение он пересматривает.
    note: str | None = None
    revisits: str | None = None

    def key(self) -> tuple:
        """Один и тот же вопрос: вопрос из текста — по фрагменту, остальные — по формулировке."""
        if self.source == "user":
            return ("user", self.source_question_id)
        return ("asked", same_question(self.text))


def question_text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadAnswer(f"{what}: нет текста вопроса")
    text = " ".join(value.split())
    if len(text) > QUESTION_MAX:
        raise BadAnswer(f"{what}: вопрос длиннее {QUESTION_MAX} знаков")
    return text


def proposals_of(value: object, fragments: Mapping[int, LabeledFragment]) -> tuple[int, ...]:
    """Предложения группы, на которые ссылается вопрос. Не номер, не из группы или не
    предложение — отбрасывается: связь вторична, сам вопрос от неё не портится."""
    numbers = (fragment_number(item) for item in value) if isinstance(value, list) else ()
    return tuple(sorted({number for number in numbers if number is not None
                         and number in fragments and fragments[number].label == "proposal"}))


def note_of(value: object) -> str | None:
    """Формулировка заметки — вторична: негодная или пустая — её просто нет, вопрос остаётся."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(value.split())
    return text if len(text) <= QUESTION_MAX else None


def revisited(value: object, decisions: frozenset[str]) -> str | None:
    """Принятое решение, которое вопрос пересматривает, — из отобранных для потока. Номер
    без нулей («ADR-7») — то же решение, что «ADR-0007»."""
    if not isinstance(value, str):
        return None
    found = re.fullmatch(r"\s*([A-Za-z]+)-0*(\d+)\s*", value)
    if found is None:
        return None
    wanted = (found.group(1).upper(), int(found.group(2)))
    for decision in decisions:
        known = re.fullmatch(r"([A-Za-z]+)-0*(\d+)", decision)
        if known and (known.group(1).upper(), int(known.group(2))) == wanted:
            return decision
    return None


def candidate_of(item: object, fragments: Mapping[int, LabeledFragment], what: str,
                 decisions: frozenset[str] = frozenset()) -> Candidate:
    if not isinstance(item, dict):
        raise BadAnswer(f"{what} — не объект")
    source = item.get("source")
    if source not in SOURCES:
        raise BadAnswer(f"{what}: source не из {', '.join(SOURCES)}: {source!r}")
    proposals = proposals_of(item.get("proposal_ids"), fragments)
    reason = reason_of(item.get("reason")) or None
    revisits = revisited(item.get("revisits"), decisions)
    if source == "user":
        number = fragment_number(item.get("source_question_id"))
        fragment = fragments.get(number) if number is not None else None
        if fragment is None or fragment.label != "question":
            raise BadAnswer(f"{what}: source_question_id — не вопрос этой группы")
        # Текст — из фрагмента: вопрос пользователя дословен, что бы ни написала модель.
        return Candidate(fragment.text, "user", number, proposals, reason,
                         note_of(item.get("note")), revisits)
    text = question_text(item.get("text"), what)
    # Ссылки вторичны: все оказались чужими — вопрос остаётся, но восстановлен он уже не по
    # предложениям группы, а просто недостающий.
    if source == "inferred" and not proposals:
        source = "discovered"
    return Candidate(text, source, None, proposals, reason, None, revisits)


def question_list(data: dict, fragments: Mapping[int, LabeledFragment],
                  decisions: frozenset[str] = frozenset()) -> list[Candidate]:
    """Вопросы из ответа. Негодный отбрасывается, но если не годится ни один — ответ негодный.
    Пустой список — честное «решать нечего». Повтор одного вопроса — один вопрос. decisions —
    номера принятых решений проекта, отобранных для потока: revisits — только из них."""
    raw = data.get("questions")
    if not isinstance(raw, list):
        raise BadAnswer("нет списка questions")
    valid, problems = [], []
    for n, item in enumerate(raw, 1):
        try:
            valid.append(candidate_of(item, fragments, f"вопрос {n}", decisions))
        except BadAnswer as exc:
            problems.append(str(exc))
    if problems and not valid:
        raise BadAnswer(problems[0])
    return merged(valid)


def merged(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Одинаковые вопросы — один, со всеми предложениями; формулировка первого. Если одна
    модель сочла вопрос недостающим, а другая — восстановленным по предложениям, он inferred,
    с её пояснением: на него уже отвечают предложения группы. От порядка это не зависит."""
    found: dict[tuple, Candidate] = {}
    for candidate in candidates:
        known = found.get(candidate.key())
        if known is None:
            found[candidate.key()] = candidate
            continue
        wins = candidate if candidate.source == "inferred" and known.source != "inferred" else known
        found[candidate.key()] = Candidate(
            known.text, wins.source, known.source_question_id,
            tuple(sorted({*known.proposal_ids, *candidate.proposal_ids})), wins.reason,
            known.note or candidate.note, known.revisits or candidate.revisits)
    return list(found.values())


def same_lists(lists: list[list[Candidate]]) -> bool:
    """Участники сошлись: одни и те же вопросы с теми же предложениями и пересмотрами.
    Формулировка заметки — не повод звать судью: она только формулировка."""
    def view(candidates: list[Candidate]) -> frozenset:
        return frozenset((c.key(), c.source, c.proposal_ids, c.revisits) for c in candidates)
    return len({view(candidates) for candidates in lists}) == 1


def with_user_questions(candidates: list[Candidate],
                        fragments: Mapping[int, LabeledFragment]) -> list[Candidate]:
    """Каждый вопрос из текста — в списке, и один раз. Сгенерированный вопрос с тем же текстом
    и есть он: на его месте — вопрос из текста, со связями обоих. Пропущенные возвращаются в
    конец, по порядку."""
    asked = [f for f in fragments.values() if f.label == "question"]
    by_text = {same_question(f.text): f for f in asked}
    result: list[Candidate] = []
    placed: dict[int, int] = {}  # вопрос из текста → его место в result
    for candidate in candidates:
        fragment = (fragments.get(candidate.source_question_id) if candidate.source == "user"
                    else by_text.get(same_question(candidate.text)))
        if fragment is None:
            result.append(candidate)
        elif fragment.id in placed:
            known = result[placed[fragment.id]]
            result[placed[fragment.id]] = Candidate(
                known.text, "user", fragment.id,
                tuple(sorted({*known.proposal_ids, *candidate.proposal_ids})), known.reason,
                known.note or candidate.note, known.revisits or candidate.revisits)
        else:
            placed[fragment.id] = len(result)
            result.append(Candidate(fragment.text, "user", fragment.id, candidate.proposal_ids,
                                    candidate.reason, candidate.note, candidate.revisits))
    return [*result, *(Candidate(f.text, "user", f.id, (), None)
                       for f in asked if f.id not in placed)]


def numbered(candidates: list[Candidate]) -> list[OpenQuestion]:
    return [OpenQuestion(id=f"Q{n}", text=c.text, source=c.source,
                         source_question_id=c.source_question_id,
                         proposal_ids=list(c.proposal_ids), reason=c.reason, note=c.note,
                         revisits=c.revisits)
            for n, c in enumerate(candidates, 1)]


def as_prompt(candidates: list[Candidate]) -> list[dict]:
    """Вопросы для судьи — в той же форме, в какой их просили у участников."""
    return [{"text": c.text, "source": c.source,
             "source_question_id": f"F{c.source_question_id}" if c.source_question_id else None,
             "proposal_ids": [f"F{i}" for i in c.proposal_ids], "reason": c.reason,
             **({"note": c.note} if c.source == "user" else {}), "revisits": c.revisits}
            for c in candidates]
