"""Анализ решения по одному вопросу: разбор ответов участников и судьи. Без ввода-вывода.

Где человек выбрал вариант, его проверяют: совместим ли с идеей, соблюдает ли ограничения,
от каких вопросов зависит, какие риски с ним связаны. Где вопрос unresolved, сравнивают его
варианты и, если один обоснованно лучше, рекомендуют его. Новых вариантов здесь нет:
рекомендовать можно только из тех, что у вопроса есть. Выбор человека не меняется: проверка не
того варианта или рекомендация вместо проверки — негодный ответ. Ссылки вторичны: чужой номер
просто отбрасывается.
"""

from dataclasses import dataclass

from .ideas import reason_of
from .proposals import fragments_in, questions_in
from .slicing import BadAnswer

RATIONALE_MAX = 2000

# Ответы участника и судьи — в своих словах (decision_analysis.md, decision_judge.md).
JUDGED = {"validated": "validated", "conflict": "conflict", "recommended": "recommended",
          "no_recommendation": "none"}


@dataclass(frozen=True)
class Context:
    """Вопрос, как его видят модели: на что можно сослаться и что выбрал человек."""

    constraints: frozenset[int]
    risks: frozenset[int]
    # Другие вопросы потока.
    questions: frozenset[str]
    # Варианты вопроса: Fn — из текста группы, Pn — найденные советом.
    proposals: frozenset[str]
    # Выбор человека; None — вопрос unresolved.
    selected: str | None


@dataclass(frozen=True)
class Analysis:
    """Анализ участника или итог судьи. kind — validated или conflict про выбор человека,
    recommended или none про unresolved; proposal — проверенный или рекомендованный вариант."""

    kind: str
    proposal: str | None
    conflicts: tuple[int, ...] = ()
    risks: tuple[int, ...] = ()
    depends_on: tuple[str, ...] = ()
    reason: str = ""
    rationale: str | None = None


def proposal_id(value: object) -> str | None:
    return value.strip().upper() if isinstance(value, str) and value.strip() else None


def rationale_of(value: object) -> str | None:
    """Обоснование: строкой или {"text": …} — как у участника и у судьи. Нет — None."""
    text = reason_of(value.get("text") if isinstance(value, dict) else value)
    if len(text) > RATIONALE_MAX:
        raise BadAnswer(f"обоснование длиннее {RATIONALE_MAX} знаков")
    return text or None


def checked(data: dict, context: Context, field: str) -> Analysis:
    """Проверка выбора человека: про тот вариант, что он выбрал, и со ссылками только на своё."""
    if context.selected is None:
        raise BadAnswer("проверка выбора, а вопрос unresolved")
    named = proposal_id(data.get(field))
    if named is not None and named != context.selected:
        raise BadAnswer(f"проверен {named}, а выбран {context.selected}")
    validation = data.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    conflicts = fragments_in(validation.get("constraint_conflicts"), context.constraints)
    return Analysis(
        "conflict" if conflicts or validation.get("valid") is False else "validated",
        context.selected, conflicts, fragments_in(validation.get("risk_ids"), context.risks),
        questions_in(validation.get("depends_on_question_ids"), context.questions))


def recommended(value: object, context: Context) -> str:
    """Рекомендация — только из вариантов вопроса: новых на этом шаге нет."""
    if context.selected is not None:
        raise BadAnswer(f"рекомендация вместо проверки выбранного {context.selected}")
    named = proposal_id(value)
    if named not in context.proposals:
        raise BadAnswer(f"у вопроса нет варианта {value!r}")
    return named


def analysis_of(data: dict, context: Context) -> Analysis:
    """Анализ участника: проверка выбора (user_selected) или сравнение вариантов (unresolved)."""
    status = data.get("status")
    if status == "user_selected":
        found = checked(data, context, "selected_proposal_id")
        draft = data.get("adr_draft")
        return Analysis(found.kind, found.proposal, found.conflicts, found.risks,
                        found.depends_on, reason_of(data.get("summary")),
                        rationale_of(draft.get("rationale")) if isinstance(draft, dict) else None)
    if status == "unresolved":
        if context.selected is not None:
            raise BadAnswer(f"вопрос unresolved, а выбран {context.selected}")
        pick = data.get("recommendation")
        if not isinstance(pick, dict):
            return Analysis("none", None, reason=reason_of(data.get("reason")))
        return Analysis("recommended", recommended(pick.get("proposal_id"), context),
                        reason=reason_of(pick.get("reason")))
    raise BadAnswer(f"неизвестный status: {status!r}")


def judged_analysis(data: dict, context: Context) -> Analysis:
    """Итог судьи по вопросу."""
    status = data.get("status")
    kind = JUDGED.get(status) if isinstance(status, str) else None
    if kind is None:
        raise BadAnswer(f"неизвестный status: {status!r}")
    reason, rationale = reason_of(data.get("reason")), rationale_of(data.get("rationale"))
    if kind in ("validated", "conflict"):
        found = checked(data, context, "proposal_id")
        # Судья назвал проблему — это конфликт, даже если status «validated».
        kind = "conflict" if found.conflicts or kind == "conflict" else "validated"
        return Analysis(kind, found.proposal, found.conflicts, found.risks, found.depends_on,
                        reason, rationale)
    if kind == "recommended":
        return Analysis(kind, recommended(data.get("proposal_id"), context), reason=reason,
                        rationale=rationale)
    if context.selected is not None:
        raise BadAnswer(f"no_recommendation вместо проверки выбранного {context.selected}")
    return Analysis("none", None, reason=reason)


def as_prompt(analysis: Analysis) -> dict:
    """Анализ участника для судьи — в той же форме, в какой его просили у участников."""
    if analysis.kind in ("validated", "conflict"):
        return {"status": "user_selected", "selected_proposal_id": analysis.proposal,
                "validation": {"valid": analysis.kind == "validated",
                               "constraint_conflicts": [f"F{i}" for i in analysis.conflicts],
                               "risk_ids": [f"F{i}" for i in analysis.risks],
                               "depends_on_question_ids": list(analysis.depends_on)},
                "summary": analysis.reason,
                "adr_draft": {"rationale": analysis.rationale,
                              "rationale_source": "ai_suggested" if analysis.rationale else None}}
    if analysis.kind == "recommended":
        return {"status": "unresolved",
                "recommendation": {"proposal_id": analysis.proposal, "reason": analysis.reason}}
    return {"status": "unresolved", "recommendation": None, "reason": analysis.reason}
