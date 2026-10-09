"""Шаг «Дизайн»: разбор описаний макета от участников и судьи и что о макете знают следующие
шаги. Находка держится на узле, который лёг в снимок: ссылка на узел, которого там нет, —
не подтверждение, и verified без подтверждения становится inferred."""

import itertools
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .figma import node_id_of
from .models import (
    DesignAction,
    DesignCoverage,
    DesignFinding,
    DesignFlow,
    DesignFollowUp,
    DesignMap,
    DesignNode,
    DesignScreen,
    DesignState,
    DesignUnknown,
    FigmaSource,
    FlowStep,
)
from .repository import conflicts_of, strings, text_of
from .slicing import BadAnswer

FINDING_ID = re.compile(r"D?(\d+)", re.IGNORECASE)
STATUSES = ("verified", "inferred", "unknown")
COVERAGE = ("covered", "partial", "not_investigated", "not_applicable")


@dataclass(frozen=True)
class Context:
    """На что могут ссылаться находки: узлы и страницы, что легли в снимок."""

    nodes: frozenset[str]
    pages: frozenset[str]

    def node_of(self, value: object) -> str:
        return node_id_of(value) if isinstance(value, str) else ""


def node_ref(value: object, context: Context) -> DesignNode | None:
    """Ссылка на узел макета из ответа. Узла нет в снимке — ссылки нет; страница — только
    та, что в снимке."""
    if not isinstance(value, dict):
        return None
    node, page = context.node_of(value.get("node_id")), context.node_of(value.get("page_id"))
    page = page if page in context.pages else ""
    name = text_of(value.get("name"))
    if node in context.nodes:
        return DesignNode(page_id=page, node_id=node, name=name)
    if not node and page:
        return DesignNode(page_id=page, name=name)
    return None


def node_refs(value: object, context: Context) -> list[DesignNode]:
    items = value if isinstance(value, list) else []
    found = (node_ref(item, context) for item in items)
    return list({(ref.page_id, ref.node_id): ref for ref in found if ref is not None}.values())


def finding_id(value: object) -> str | None:
    found = FINDING_ID.fullmatch(value.strip()) if isinstance(value, str) else None
    return f"D{int(found.group(1))}" if found else None


def given_findings(value: object) -> list[dict]:
    items = value if isinstance(value, list) else []
    return [item for item in items if isinstance(item, dict) and text_of(item.get("statement"))]


def findings_of(value: object, context: Context) -> list[DesignFinding]:
    """Находки со своими номерами. Без номера или с повтором — номер наш и не занятый ни одной
    находкой ответа: иначе ссылки на ту находку достались бы этой."""
    items = given_findings(value)
    taken = {finding_id(item.get("id")) for item in items}
    free = (f"D{n}" for n in itertools.count(1) if f"D{n}" not in taken)
    found: dict[str, DesignFinding] = {}
    for item in items:
        name = finding_id(item.get("id"))
        if name is None or name in found:
            name = next(free)
        status = item.get("status") if item.get("status") in STATUSES else "unknown"
        evidence = [ref for ref in node_refs(item.get("evidence"), context) if ref.node_id]
        if status == "verified" and not evidence:
            status = "inferred"   # verified без узла в снимке — только вывод
        found[name] = DesignFinding(id=name, statement=text_of(item.get("statement")),
                                    status=status, evidence=evidence,
                                    relevance=text_of(item.get("relevance")))
    return list(found.values())


def linkable(findings: list[DesignFinding], value: object) -> set[str]:
    """На какие находки ссылки берём: на те, чей номер дал сам ответ, и одной находке."""
    named = Counter(finding_id(item.get("id")) for item in given_findings(value))
    return {finding.id for finding in findings if named[finding.id] == 1}


def ids_in(value: object, known: set[str]) -> list[str]:
    items = value if isinstance(value, list) else []
    return list(dict.fromkeys(name for name in map(finding_id, items) if name in known))


def status_of(value: object) -> str:
    return value if value in STATUSES else "unknown"


def screens_of(value: object, known: set[str], context: Context) -> list[DesignScreen]:
    items = value if isinstance(value, list) else []
    return [DesignScreen(
        name=text_of(item.get("name")), node_id=known_node(item.get("node_id"), context),
        purpose=text_of(item.get("purpose")), data=strings(item.get("data")),
        actions=[DesignAction(action=text_of(action.get("action")),
                              result=text_of(action.get("result")) or None,
                              status=status_of(action.get("status")),
                              finding_ids=ids_in(action.get("finding_ids"), known))
                 for action in listed(item.get("actions")) if text_of(action.get("action"))],
        states=[DesignState(name=text_of(state.get("name")),
                            node_id=known_node(state.get("node_id"), context))
                for state in listed(item.get("states")) if text_of(state.get("name"))])
        for item in items if isinstance(item, dict) and text_of(item.get("name"))]


def listed(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def known_node(value: object, context: Context) -> str:
    """Узел экрана или состояния — только из снимка: иначе следующие шаги поверили бы
    несуществующему фрейму."""
    node = context.node_of(value)
    return node if node in context.nodes else ""


def flows_of(value: object, known: set[str]) -> list[DesignFlow]:
    return [DesignFlow(
        name=text_of(item.get("name")), status=status_of(item.get("status")),
        steps=[FlowStep(description=text_of(step.get("description")),
                        finding_ids=ids_in(step.get("finding_ids"), known))
               for step in listed(item.get("steps")) if text_of(step.get("description"))])
        for item in listed(value) if text_of(item.get("name"))]


def coverage_of(value: object) -> list[DesignCoverage]:
    return [DesignCoverage(
        area=text_of(item.get("area")),
        status=item.get("status") if item.get("status") in COVERAGE else "not_investigated",
        reason=text_of(item.get("reason")))
        for item in listed(value) if text_of(item.get("area"))]


def unknowns_of(value: object, context: Context) -> list[DesignUnknown]:
    return [DesignUnknown(question=text_of(item.get("question")),
                          reason=text_of(item.get("reason")),
                          investigate=node_refs(item.get("investigate"), context))
            for item in listed(value) if text_of(item.get("question"))]


def map_of(data: dict, context: Context) -> DesignMap:
    """Описание макета из ответа участника или судьи. Без списка findings ответ негодный;
    пустой список — честное «ничего относящегося к идее в макете не нашлось»."""
    if not isinstance(data.get("findings"), list):
        raise BadAnswer("нет списка findings")
    findings = findings_of(data.get("findings"), context)
    known = linkable(findings, data.get("findings"))
    return DesignMap(findings=findings, screens=screens_of(data.get("screens"), known, context),
                     flows=flows_of(data.get("flows"), known),
                     coverage=coverage_of(data.get("coverage")),
                     unknowns=unknowns_of(data.get("unknowns"), context),
                     design_conflicts=conflicts_of(data.get("design_conflicts")))


@dataclass(frozen=True)
class Judged:
    complete: bool
    result: DesignMap
    follow_up: tuple[DesignFollowUp, ...]


def judged_design(data: dict, context: Context) -> Judged:
    """Итог судьи: проверенное описание и, если исследование недостаточно, задания follow_up.
    needs_investigation без заданий — доисследовать нечего, и это тоже конец."""
    status = data.get("status")
    if status not in ("complete", "needs_investigation"):
        raise BadAnswer(f"неизвестный status: {status!r}")
    result = map_of(data, context)
    known = linkable(result.findings, data.get("findings"))
    follow_up = tuple(DesignFollowUp(objective=text_of(item.get("objective")),
                                     reason=text_of(item.get("reason")),
                                     targets=node_refs(item.get("targets"), context),
                                     related_finding_ids=ids_in(
                                         item.get("related_finding_ids"), known))
                      for item in listed(data.get("follow_up"))
                      if text_of(item.get("objective")))
    if status == "complete" or not follow_up:
        return Judged(True, result, ())
    return Judged(False, result, follow_up)


def as_prompt(result: DesignMap) -> dict:
    """Описание — в той форме, в какой его просили у моделей."""
    return result.model_dump(mode="json")


def context_prompt(result: DesignMap | None, source: FigmaSource | None = None, *,
                   complete: bool = True, follow_up: Sequence[DesignFollowUp] = ()) -> str:
    """Что о макете знают следующие шаги: проверенное описание или честное «не смотрели».
    Какой файл и версия; complete — судья счёл исследование достаточным, а
    remaining_follow_up — что доисследовать не успели: недоисследованное — не установленное."""
    if result is None:
        return "Макет не исследовался: шаг «Дизайн» пропущен."
    source = source or FigmaSource()
    return json.dumps({"figma_file": source.name, "file_key": source.file_key,
                       "version": source.version,
                       "requested": [node.model_dump() for node in source.requested],
                       "complete": complete,
                       "remaining_follow_up": [item.model_dump(mode="json")
                                               for item in follow_up],
                       "design": as_prompt(result)}, ensure_ascii=False, indent=2)
