"""Репозиторий: inventory рабочей копии, путь к ней, разбор находок и вердикта судьи."""

import subprocess

import pytest

from spec_council.repository import (
    Context,
    RepositoryError,
    context_prompt,
    inventory,
    inventory_prompt,
    judged_map,
    located,
    map_of,
)
from spec_council.slicing import BadAnswer


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "project"
    (root / "api").mkdir(parents=True)
    (root / "api" / "deps.py").write_text("def get_context(): ...\n", encoding="utf-8")
    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return root


def test_the_inventory_is_the_working_copy_files_and_its_commit(repo):
    (repo / "new.py").write_text("x = 1\n", encoding="utf-8")       # новый, не игнорируемый
    (repo / "debug.log").write_text("шум\n", encoding="utf-8")       # игнорируемый
    found = inventory(repo / "api")                                  # из подкаталога — корень
    assert found.root == repo.resolve()
    assert found.files == (".gitignore", "api/deps.py", "new.py")
    assert len(found.commit_sha) == 40 and found.dirty


def test_a_clean_working_copy_is_not_dirty_and_a_big_one_is_cut(repo, monkeypatch):
    assert not inventory(repo).dirty
    monkeypatch.setattr("spec_council.repository.INVENTORY_MAX", 1)
    assert inventory_prompt(inventory(repo)).endswith("и ещё 1 файлов: ищите по репозиторию сами")


def test_a_folder_that_is_not_a_repository_is_refused(tmp_path):
    with pytest.raises(RepositoryError):
        inventory(tmp_path)


def test_a_path_is_from_the_repositories_folder_and_stays_inside_it(repo, tmp_path):
    assert located("project", tmp_path) == repo.resolve()
    with pytest.raises(RepositoryError, match="вне каталога"):
        located("../..", repo)
    with pytest.raises(RepositoryError, match="абсолютный"):
        located("project", None)
    assert located(str(repo), None) == repo.resolve()
    with pytest.raises(RepositoryError, match="Каталога нет"):
        located("нет", tmp_path)
    with pytest.raises(RepositoryError, match="Укажите"):
        located("  ", tmp_path)


CONTEXT = Context(files=frozenset({"api/deps.py", "api/routes.py"}))


def finding(id_="R1", status="verified", path="api/deps.py", **extra):
    return {"id": id_, "statement": "API берёт контекст из зависимостей.", "status": status,
            "evidence": [{"path": path, "lines": "1-3", "symbol": "get_context"}],
            "relevance": "точка входа", **extra}


def test_findings_hold_on_files_that_exist():
    result = map_of({"findings": [
        finding(), finding("r2", path=".\\api\\routes.py"), finding("R3", path="нет.py"),
        finding("R4", status="maybe"), {"statement": " "}, "мусор"]}, CONTEXT)
    assert [(f.id, f.status, [e.path for e in f.evidence]) for f in result.findings] == [
        ("R1", "verified", ["api/deps.py"]), ("R2", "verified", ["api/routes.py"]),
        ("R3", "inferred", []),               # файла нет — подтверждения нет
        ("R4", "unknown", ["api/deps.py"])]


def test_links_go_only_to_known_findings():
    result = map_of({
        "findings": [finding()],
        "flows": [{"name": "Запрос", "entry_point": "api/routes.py",
                   "steps": [{"description": "маршрут", "finding_ids": ["R1", "R9"]},
                             {"description": " "}]}],
        "coverage": [{"area": "API", "status": "covered", "evidence_ids": ["r1", "R7"]},
                     {"area": "Auth", "status": "half"}],
        "unknowns": [{"question": "Есть ли прокси?", "investigate": ["Caddyfile", ""]}],
        "documentation_conflicts": [{"doc": "README", "code": "иначе"}, "строкой", 3]}, CONTEXT)
    assert result.flows[0].steps[0].finding_ids == ["R1"] and len(result.flows[0].steps) == 1
    assert [(c.area, c.status, c.evidence_ids) for c in result.coverage] == [
        ("API", "covered", ["R1"]), ("Auth", "not_investigated", [])]
    assert result.unknowns[0].investigate == ["Caddyfile"]
    assert result.documentation_conflicts == ["README — иначе", "строкой"]   # 3 — не текст


def test_no_findings_list_is_a_bad_answer_but_an_empty_one_is_honest():
    assert map_of({"findings": []}, CONTEXT).findings == []
    with pytest.raises(BadAnswer, match="findings"):
        map_of({"facts": []}, CONTEXT)


def test_the_judge_finishes_or_sends_concrete_follow_ups():
    follow = [{"objective": "Проверить прокси", "targets": ["Caddyfile"],
               "related_finding_ids": ["R1", "R5"]}, {"objective": ""}]
    more = judged_map({"status": "needs_investigation", "findings": [finding()],
                       "follow_up": follow}, CONTEXT)
    assert not more.complete
    assert [(f.objective, f.targets, f.related_finding_ids) for f in more.follow_up] == [
        ("Проверить прокси", ["Caddyfile"], ["R1"])]
    done = judged_map({"status": "complete", "findings": [], "follow_up": follow}, CONTEXT)
    assert done.complete and done.follow_up == ()
    # Доисследовать нечего — это тоже конец.
    assert judged_map({"status": "needs_investigation", "findings": []}, CONTEXT).complete
    with pytest.raises(BadAnswer, match="status"):
        judged_map({"status": "partial", "findings": []}, CONTEXT)


def test_the_next_steps_get_the_map_or_an_honest_no_scan():
    assert "не исследовался" in context_prompt(None)
    text = context_prompt(map_of({"findings": [finding()]}, CONTEXT), "abc")
    assert '"commit_sha": "abc"' in text and "get_context" in text
