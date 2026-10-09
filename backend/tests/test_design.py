"""Шаг «Дизайн»: описание макета от участников и судьи держится на узлах снимка."""

import json

import pytest

from spec_council.design import Context, context_prompt, judged_design, map_of
from spec_council.models import DesignNode, FigmaSource
from spec_council.slicing import BadAnswer

CONTEXT = Context(nodes=frozenset({"1:0", "2:1", "2:3", "I2:3;5:2"}), pages=frozenset({"1:0"}))


def finding(id_="D1", status="verified", node="2:1", **extra):
    return {"id": id_, "statement": "Экран тредов с поиском", "status": status,
            "evidence": [{"page_id": "1:0", "node_id": node, "name": "Threads"}], **extra}


def test_a_finding_holds_on_a_node_of_the_snapshot():
    """Узел — как в ссылке («2-1») или в API («2:1»); узла нет в снимке — нет и подтверждения,
    и verified без подтверждения — только вывод."""
    result = map_of({"findings": [finding(node="2-1"), finding("D2", node="9:9"),
                                  finding("D3", node="I2:3;5:2")]}, CONTEXT)
    assert [(f.id, f.status, f.evidence) for f in result.findings] == [
        ("D1", "verified", [DesignNode(page_id="1:0", node_id="2:1", name="Threads")]),
        ("D2", "inferred", []),
        ("D3", "verified", [DesignNode(page_id="1:0", node_id="I2:3;5:2", name="Threads")])]


def test_a_page_not_in_the_snapshot_is_not_kept():
    result = map_of({"findings": [{**finding(), "evidence": [
        {"page_id": "7:0", "node_id": "2:1"}]}]}, CONTEXT)
    assert result.findings[0].evidence == [DesignNode(node_id="2:1")]


def test_screens_flows_and_unknowns_keep_only_known_nodes_and_findings():
    result = map_of({
        "findings": [finding(), finding("D1", node="2:3")],          # второй D1 — номер наш
        "screens": [{"name": "Threads", "node_id": "2:1", "purpose": "Найти тред",
                     "data": ["Заголовок", "Заголовок", 3],
                     "actions": [{"action": "Поиск", "result": "", "status": "maybe",
                                  "finding_ids": ["D1", "d2", "D7"]}, {"result": "без действия"}],
                     "states": [{"name": "Default", "node_id": "2:1"},
                                {"name": "Empty", "node_id": "8:8"}]},
                    {"name": "Чужой", "node_id": "8:8"}, {"purpose": "без имени"}],
        "flows": [{"name": "Найти тред", "status": "verified",
                   "steps": [{"description": "Ввести запрос", "finding_ids": ["D2"]}]}],
        "coverage": [{"area": "Поиск", "status": "everything"}],
        "unknowns": [{"question": "Что при пустом результате?",
                      "investigate": [{"page_id": "1:0", "node_id": "2-1"}, {"node_id": "8:8"}]}],
        "design_conflicts": ["Макет и текст расходятся", {"design": "поиск", "text": "бот"}]},
        CONTEXT)
    [screen, alien] = result.screens
    assert (screen.node_id, screen.data) == ("2:1", ["Заголовок"])
    assert [(a.action, a.result, a.status, a.finding_ids) for a in screen.actions] == [
        ("Поиск", None, "unknown", [])]   # D1 у двух находок, D2 — номер наш, D7 — нет такой
    assert [(s.name, s.node_id) for s in screen.states] == [("Default", "2:1"), ("Empty", "")]
    assert alien.node_id == ""                                # узла нет в снимке
    assert [(f.status, f.steps[0].finding_ids) for f in result.flows] == [("verified", [])]
    assert result.coverage[0].status == "not_investigated"
    assert result.unknowns[0].investigate == [DesignNode(page_id="1:0", node_id="2:1")]
    assert result.design_conflicts == ["Макет и текст расходятся", "поиск — бот"]


def test_no_findings_list_is_a_bad_answer_but_an_empty_one_is_honest():
    with pytest.raises(BadAnswer, match="findings"):
        map_of({"screens": []}, CONTEXT)
    assert map_of({"findings": []}, CONTEXT).findings == []


def test_the_judge_finishes_or_sends_concrete_follow_ups():
    told = judged_design({"status": "needs_investigation", "findings": [finding()],
                          "follow_up": [{"objective": "Проверить пустое состояние",
                                         "targets": [{"page_id": "1:0", "node_id": "2:3"}],
                                         "related_finding_ids": ["D1"]}, {"reason": "без цели"}]},
                         CONTEXT)
    assert not told.complete
    assert [(f.objective, f.targets, f.related_finding_ids) for f in told.follow_up] == [
        ("Проверить пустое состояние", [DesignNode(page_id="1:0", node_id="2:3")], ["D1"])]
    nothing = judged_design({"status": "needs_investigation", "findings": []}, CONTEXT)
    assert (nothing.complete, nothing.follow_up) == (True, ())
    with pytest.raises(BadAnswer, match="status"):
        judged_design({"status": "partial", "findings": []}, CONTEXT)


def test_the_next_steps_get_the_design_or_an_honest_no_design():
    assert "Макет не исследовался" in context_prompt(None)
    result = map_of({"findings": [finding()]}, CONTEXT)
    source = FigmaSource(file_key="AbC123", name="Billing", version="v1",
                         requested=[DesignNode(page_id="1:0", node_id="2:1", name="Threads")])
    told = json.loads(context_prompt(result, source, complete=False))
    assert (told["figma_file"], told["version"], told["complete"]) == ("Billing", "v1", False)
    assert told["requested"][0]["node_id"] == "2:1"
    assert told["design"]["findings"][0]["statement"] == "Экран тредов с поиском"
