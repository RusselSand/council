"""Открытые вопросы к идее: разбор ответов моделей, проверка и сведение. Без ввода-вывода.

Вопрос — что неизвестно, ответов в нём нет. Предложения группы связаны с вопросом через
proposal_ids, и только фрагменты-предложения этой группы: чужой или не тот номер просто
отбрасывается, а inferred-вопрос, у которого не осталось ни одной связи, — уже discovered.
Вопросы пользователя — фрагменты типа question — сохраняются дословно: текст берётся из
фрагмента, а не у модели, и судья их не потеряет — пропущенные код вернёт сам.
"""

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


def candidate_of(item: object, fragments: Mapping[int, LabeledFragment], what: str) -> Candidate:
    if not isinstance(item, dict):
        raise BadAnswer(f"{what} — не объект")
    source = item.get("source")
    if source not in SOURCES:
        raise BadAnswer(f"{what}: source не из {', '.join(SOURCES)}: {source!r}")
    proposals = proposals_of(item.get("proposal_ids"), fragments)
    reason = reason_of(item.get("reason")) or None
    if source == "user":
        number = fragment_number(item.get("source_question_id"))
        fragment = fragments.get(number) if number is not None else None
        if fragment is None or fragment.label != "question":
            raise BadAnswer(f"{what}: source_question_id — не вопрос этой группы")
        # Текст — из фрагмента: вопрос пользователя дословен, что бы ни написала модель.
        return Candidate(fragment.text, "user", number, proposals, reason)
    text = question_text(item.get("text"), what)
    # Ссылки вторичны: все оказались чужими — вопрос остаётся, но восстановлен он уже не по
    # предложениям группы, а просто недостающий.
    if source == "inferred" and not proposals:
        source = "discovered"
    return Candidate(text, source, None, proposals, reason)


def question_list(data: dict, fragments: Mapping[int, LabeledFragment]) -> list[Candidate]:
    """Вопросы из ответа. Негодный отбрасывается, но если не годится ни один — ответ негодный.
    Пустой список — честное «решать нечего». Повтор одного вопроса — один вопрос."""
    raw = data.get("questions")
    if not isinstance(raw, list):
        raise BadAnswer("нет списка questions")
    valid, problems = [], []
    for n, item in enumerate(raw, 1):
        try:
            valid.append(candidate_of(item, fragments, f"вопрос {n}"))
        except BadAnswer as exc:
            problems.append(str(exc))
    if problems and not valid:
        raise BadAnswer(problems[0])
    return merged(valid)


def merged(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Одинаковые вопросы — один, со всеми предложениями; формулировка и пояснение первого."""
    found: dict[tuple, Candidate] = {}
    for candidate in candidates:
        known = found.get(candidate.key())
        if known is None:
            found[candidate.key()] = candidate
        else:
            found[candidate.key()] = Candidate(
                known.text, known.source, known.source_question_id,
                tuple(sorted({*known.proposal_ids, *candidate.proposal_ids})), known.reason)
    return list(found.values())


def same_lists(lists: list[list[Candidate]]) -> bool:
    """Участники сошлись: одни и те же вопросы с теми же предложениями."""
    def view(candidates: list[Candidate]) -> frozenset:
        return frozenset((c.key(), c.source, c.proposal_ids) for c in candidates)
    return len({view(candidates) for candidates in lists}) == 1


def with_user_questions(candidates: list[Candidate],
                        fragments: Mapping[int, LabeledFragment]) -> list[Candidate]:
    """Каждый вопрос из текста — в списке. Пропущенные возвращаются в конец, по порядку."""
    present = {c.source_question_id for c in candidates if c.source == "user"}
    missing = [Candidate(f.text, "user", f.id, (), None) for f in fragments.values()
               if f.label == "question" and f.id not in present]
    return [*candidates, *missing]


def numbered(candidates: list[Candidate]) -> list[OpenQuestion]:
    return [OpenQuestion(id=f"Q{n}", text=c.text, source=c.source,
                         source_question_id=c.source_question_id,
                         proposal_ids=list(c.proposal_ids), reason=c.reason)
            for n, c in enumerate(candidates, 1)]


def as_prompt(candidates: list[Candidate]) -> list[dict]:
    """Вопросы для судьи — в той же форме, в какой их просили у участников."""
    return [{"text": c.text, "source": c.source,
             "source_question_id": f"F{c.source_question_id}" if c.source_question_id else None,
             "proposal_ids": [f"F{i}" for i in c.proposal_ids], "reason": c.reason}
            for c in candidates]
