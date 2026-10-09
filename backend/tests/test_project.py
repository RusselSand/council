"""Решения проекта для потока: каталог прошлых ADR, их след в коде и отбор в начале «Вопросов»."""

import subprocess

import pytest

from spec_council.app import app
from spec_council.deps import get_agents, get_launcher, get_notes_root, get_repositories
from spec_council.models import (
    Evidence,
    ProjectDecision,
    RepositoryFinding,
    RepositoryMap,
    RepositoryScan,
    ScannedRepository,
)
from spec_council.notes import Catalog, Note, path_of, rendered
from spec_council.project import (
    evidence_files,
    issue_outcomes,
    records,
    same_selection,
    selected,
    trails_of,
)
from spec_council.slicing import BadAnswer
from tests.test_streams import (
    IDEA_C,
    Agents,
    approve,
    client,
    confirm,
    grouped,
    passes,
    scans,
    section,
    seen_idea,
    skip,
    streams_of,
    takes,
)

PAST = [Note("IDEA-0001", "idea", "Ответы находятся без помощи людей."),
        Note("OQ-0001", "open_question", "Где искать ответы?", ("IDEA-0001",)),
        Note("PRO-0001", "proposal", "Ищем в базе знаний.", ("OQ-0001",)),
        Note("ADR-0001", "adr", "Ищем в базе знаний, потому что там проверенные ответы.",
             ("PRO-0001",)),
        Note("OUT-0001", "outcome", "Поиск\n\nЗадачи:\n- ISS-0003: Поиск по базе",
             ("ADR-0001",)),
        Note("OQ-0002", "open_question", "Нужен ли поиск по чату?", ("ADR-0001",)),
        Note("IDEA-0002", "idea", "Счета приходят вовремя."),
        Note("OQ-0003", "open_question", "Кто шлёт счета?", ("IDEA-0002",)),
        Note("PRO-0002", "proposal", "Счета шлёт бот.", ("OQ-0003",)),
        Note("ADR-0002", "adr", "Счета шлёт бот.", ("PRO-0002",))]


def put(root, notes=PAST):
    for note in notes:
        path = path_of(root, note)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered(note), encoding="utf-8")
    return root


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def test_the_catalog_tells_each_decision_with_its_idea_question_and_status(tmp_path):
    catalog = Catalog.load(put(tmp_path))
    found = records(catalog, {}, excluded=["ADR-0002"])
    assert [(r.adr_id, r.idea, r.question, r.status) for r in found] == [
        ("ADR-0001", "Ответы находятся без помощи людей.", "Где искать ответы?",
         "under_review")]
    assert issue_outcomes(catalog) == {"ISS-0003": [("OUT-0001", ("ADR-0001",))]}


def scan_of(*repos, paths=("app.py",)):
    findings = [RepositoryFinding(id=f"R{n}", statement="…", status="verified",
                                  evidence=[Evidence(path=path)])
                for n, path in enumerate(paths, 1)]
    return RepositoryScan(state="done", run="s1", steps=[], result=RepositoryMap(
        findings=findings), repositories=[ScannedRepository(name=name, path=name, root=str(root))
                                          for name, root in repos])


def project_with(tmp_path, *message):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "app.py").write_text("def find(): ...\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", *(part for line in message for part in ("-m", line)))
    return repo


def test_the_trail_follows_commits_with_issue_numbers_to_the_decisions(tmp_path):
    repo = project_with(tmp_path, "Поиск по базе", "Closes ISS-0003")
    (repo / "app.py").write_text("def find(): return []\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "Мелочь без номера и ISS-0999 чужая")
    catalog = Catalog.load(put(tmp_path / "notes"))
    files = evidence_files(scan_of(("", repo)))
    assert files == [(repo, "app.py", "app.py")]
    trails = trails_of(files, issue_outcomes(catalog))
    [trail] = trails["ADR-0001"]
    assert (trail.issue, trail.outcome, trail.file) == ("ISS-0003", "OUT-0001", "app.py")
    assert records(catalog, trails)[0].found_in_code == [trail]
    assert trails_of([(tmp_path / "нет", "app.py", "app.py")], issue_outcomes(catalog)) == {}


def test_an_issue_of_several_outcomes_leaves_its_trail_on_the_decisions_of_each(tmp_path):
    notes = [*PAST[:5],
             Note("OQ-0004", "open_question", "Как ранжировать ответы?", ("IDEA-0001",)),
             Note("PRO-0004", "proposal", "Ранжируем по свежести.", ("OQ-0004",)),
             Note("ADR-0004", "adr", "Ранжируем по свежести.", ("PRO-0004",)),
             Note("OUT-0002", "outcome", "Ранжирование\n\nЗадачи:\n- ISS-0003: Поиск по базе",
                  ("ADR-0004",))]
    catalog = Catalog.load(put(tmp_path / "notes", notes))
    assert issue_outcomes(catalog) == {"ISS-0003": [("OUT-0001", ("ADR-0001",)),
                                                    ("OUT-0002", ("ADR-0004",))]}
    repo = project_with(tmp_path, "Поиск с ранжированием", "ISS-0003")
    trails = trails_of(evidence_files(scan_of(("", repo))), issue_outcomes(catalog))
    assert {adr: [(t.issue, t.outcome) for t in found] for adr, found in trails.items()} == {
        "ADR-0001": [("ISS-0003", "OUT-0001")], "ADR-0004": [("ISS-0003", "OUT-0002")]}


def test_several_repositories_split_the_map_paths_by_folder(tmp_path):
    files = evidence_files(scan_of(("back", tmp_path / "b"), ("front", tmp_path / "f"),
                                   paths=("back/api.py", "front/src/App.tsx", "other/x.py")))
    assert files == [(tmp_path / "b", "api.py", "back/api.py"),
                     (tmp_path / "f", "src/App.tsx", "front/src/App.tsx")]


CATALOG = [ProjectDecision(adr_id="ADR-0007", decision="Платежи через Stripe."),
           ProjectDecision(adr_id="ADR-0012", decision="Чеки в S3.")]


def test_the_selection_keeps_catalog_decisions_with_a_known_relevance():
    found = selected({"decisions": [
        {"adr_id": "ADR-7", "relevance": "applicable", "reason": "  платежи  "},
        {"adr_id": "ADR-0012", "relevance": "maybe", "reason": "не та категория"},
        {"adr_id": "ADR-0099", "relevance": "uncertain", "reason": "нет в каталоге"},
        {"adr_id": "ADR-0007", "relevance": "uncertain", "reason": "повтор"}]}, CATALOG)
    assert [(d.adr_id, d.relevance, d.reason) for d in found] == [
        ("ADR-0007", "applicable", "платежи")]
    judged = selected({"decisions": [{"adr_id": "ADR-0012", "relevance": "uncertain"}]},
                      CATALOG, allowed={"ADR-0007"})
    assert judged == []                                  # судья — только из предложенного
    with pytest.raises(BadAnswer, match="decisions"):
        selected({}, CATALOG)
    assert same_selection([found, list(found)])
    assert not same_selection([found, []])


# --- в потоке


@pytest.fixture
def agents(tmp_path):
    fake = Agents()
    app.dependency_overrides[get_agents] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    app.dependency_overrides[get_notes_root] = lambda: put(tmp_path / "notes")
    yield fake
    for dependency in (get_agents, get_launcher, get_notes_root):
        app.dependency_overrides.pop(dependency)


def picks(council_id, keep, group="C", search_run=None):
    run = search_run or (streams_of(council_id)[group].decisions_search.run if keep else None)
    return client.post(f"/api/councils/{council_id}/streams/{group}/project-decisions",
                       json={"run": "g1", "revision": 0, "search_run": run, "keep": list(keep),
                             "idea": seen_idea(council_id, group)})


def at_questions():
    council_id = grouped()
    confirm(council_id)
    approve(council_id, "C", IDEA_C)
    skip(council_id, "C")
    passes(council_id, "C")
    return council_id


def test_past_decisions_are_selected_before_the_questions(agents):
    council_id = at_questions()
    stream = streams_of(council_id)["C"]
    assert stream.questions is None                     # сначала — решения проекта
    search = stream.decisions_search
    assert (search.state, search.catalog, search.traced) == ("done", 2, 0)
    assert [(d.adr_id, d.relevance) for d in search.decisions] == [("ADR-0001", "applicable")]
    catalog = section(agents.prompts["project_decisions_discovery"], "PROJECT ADR CATALOG")
    assert '"status": "under_review"' in catalog and "Счета шлёт бот." in catalog
    assert {s.name.value: s.state for s in search.steps}["project_decisions_judge"] == "skipped"
    assert client.post(f"/api/councils/{council_id}/streams/C/questions/discovery"
                       ).status_code == 409

    assert picks(council_id, ["ADR-0001"]).status_code == 200
    stream = streams_of(council_id)["C"]
    assert [d.adr_id for d in stream.project_decisions] == ["ADR-0001"]
    assert stream.questions.decisions == ["ADR-0001"]
    accepted = section(agents.prompts["question_discovery"], "ACCEPTED PROJECT DECISIONS")
    assert '"adr_id": "ADR-0001"' in accepted and "та же область" in accepted
    first = stream.questions.run
    assert picks(council_id, ["ADR-0001"]).status_code == 200      # тот же отбор — повтор
    assert streams_of(council_id)["C"].questions.run == first
    assert picks(council_id, []).status_code == 200                # без решений — заново
    stream = streams_of(council_id)["C"]
    assert (stream.project_decisions, stream.questions.decisions) == ([], [])
    assert stream.questions.run != first


def test_a_decision_not_from_the_selection_is_refused(agents):
    council_id = at_questions()
    res = picks(council_id, ["ADR-0002"])
    assert res.status_code == 422 and "ADR-0002" in res.json()["detail"]
    assert picks(council_id, ["ADR-0001"], search_run="прежний").status_code == 409


def test_without_models_the_selection_fails_and_the_questions_go_without_it(agents):
    agents.online = set()
    council_id = at_questions()
    search = streams_of(council_id)["C"].decisions_search
    assert search.state == "failed" and search.error.startswith("Нет подключения")
    agents.online = {"sol", "fable"}
    assert client.post(f"/api/councils/{council_id}/streams/C/project-decisions/search"
                       ).status_code == 202
    assert streams_of(council_id)["C"].decisions_search.state == "done"


def test_the_trail_comes_from_the_approved_repository_map(agents, tmp_path):
    repos = tmp_path / "repos"
    repo = repos / "project"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "app.py").write_text("def main(): ...\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Поиск ISS-0003")
    app.dependency_overrides[get_repositories] = lambda: repos
    try:
        council_id = grouped()
        confirm(council_id)
        approve(council_id, "C", IDEA_C)
        scans(council_id, "C")
        takes(council_id, "C")
        passes(council_id, "C")
    finally:
        app.dependency_overrides.pop(get_repositories)
    search = streams_of(council_id)["C"].decisions_search
    assert search.traced == 1
    catalog = section(agents.prompts["project_decisions_discovery"], "PROJECT ADR CATALOG")
    assert '"issue": "ISS-0003"' in catalog and '"file": "app.py"' in catalog
