"""Проекты: рабочие копии и папка документации, которые совет берёт по проекту."""

import subprocess
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from spec_council.api.councils import council_lock
from spec_council.app import app
from spec_council.deps import council_notes, get_projects, get_repositories
from spec_council.models import ProjectDraft
from spec_council.projects import FileProjects, Projects
from spec_council.store import FileStore, InMemoryStore

client = TestClient(app)


def git_repo(folder):
    folder.mkdir(parents=True)
    subprocess.run(["git", "-C", str(folder), "init", "-q"], check=True, capture_output=True)
    return folder


@pytest.fixture(name="repos")
def repositories(tmp_path):
    """Каталог репозиториев с двумя рабочими копиями и папкой без git."""
    root = tmp_path / "repos"
    git_repo(root / "back")
    git_repo(root / "front")
    (root / "docs").mkdir()
    app.dependency_overrides[get_repositories] = lambda: root
    yield root
    app.dependency_overrides.pop(get_repositories)


@pytest.fixture(name="projects")
def fresh_projects():
    """Свои проекты у каждого теста: проект, выбранный у совета, не перейдёт к советам чужих
    тестов — новый совет берёт проект последнего, а его в настоящих проектах нет."""
    projects = Projects()
    app.dependency_overrides[get_projects] = lambda: projects
    yield projects
    app.dependency_overrides.pop(get_projects)


def creates(**draft):
    return client.post("/api/projects", json={"name": "Кромка", **draft})


def test_a_project_keeps_its_working_copies_and_notes_folder(repos, projects):
    res = creates(name="  Кромка ", repositories=["back", "front"], notes="back/docs/reasoning")
    assert res.status_code == 201
    project = res.json()
    assert (project["name"], project["repositories"]) == ("Кромка", ["back", "front"])
    # Папки ещё нет — её создаст первая выгрузка; путь — как его найдёт сервер.
    assert project["notes_root"] == str((repos / "back/docs/reasoning").resolve())
    assert project["problem"] is None
    assert client.get("/api/projects").json() == [project]
    assert client.get("/api/settings").json()["projects"] == [project]

    res = client.put(f"/api/projects/{project['id']}",
                     json={"name": "Кромка", "repositories": ["front"], "notes": "", "revision": 0})
    assert res.status_code == 200
    assert (res.json()["repositories"], res.json()["notes"], res.json()["notes_root"],
            res.json()["revision"]) == (["front"], "", None, 1)


def test_an_edit_of_an_older_version_is_refused(repos, projects):
    project = creates(repositories=["back"], notes="back/docs").json()
    # Одна вкладка сменила папку…
    assert client.put(f"/api/projects/{project['id']}", json={
        "name": "Кромка", "repositories": ["back"], "notes": "front/docs", "revision": 0,
    }).status_code == 200
    # …другая, открытая раньше, правит название — и вернула бы прежнюю папку.
    res = client.put(f"/api/projects/{project['id']}", json={
        "name": "Кромка 2", "repositories": ["back"], "notes": "back/docs", "revision": 0})
    assert res.status_code == 409 and "уже поправили" in res.json()["detail"]
    assert projects.get_project(project["id"]).notes == "front/docs"


def test_project_names_differ_in_more_than_case(repos, projects):
    first = creates(name="Кромка").json()
    res = creates(name=" КРОМКА ")
    assert res.status_code == 422 and "уже есть" in res.json()["detail"]
    other = creates(name="Совет").json()
    res = client.put(f"/api/projects/{other['id']}", json={"name": "кромка", "revision": 0})
    assert res.status_code == 422
    # Себя проект не задевает: то же название с другим регистром — можно.
    assert client.put(f"/api/projects/{first['id']}",
                      json={"name": "КРОМКА", "revision": 0}).status_code == 200


@pytest.mark.parametrize(("draft", "why"), [
    ({"name": "  "}, "Назовите проект"),
    ({"repositories": ["nope"]}, "Каталога нет"),
    ({"repositories": ["docs"]}, "docs: "),                   # не рабочая копия git
    ({"repositories": ["../back"]}, "вне каталога репозиториев"),
    ({"repositories": ["back", "back/."]}, "одна и та же рабочая копия"),
    ({"notes": "../notes"}, "вне каталога репозиториев"),
    ({"notes": "  "}, "Укажите папку документации"),
])
def test_a_project_with_wrong_paths_is_not_saved(repos, projects, draft, why):
    res = creates(**draft)
    assert res.status_code == 422 and why in res.json()["detail"]
    assert projects.list_projects() == []


@pytest.mark.parametrize("notes", ["docs/notes.md", "docs/notes.md/reasoning"])
def test_the_notes_folder_is_a_folder(repos, projects, notes):
    (repos / "docs" / "notes.md").write_text("", encoding="utf-8")
    res = creates(notes=notes)
    assert res.status_code == 422 and "Это не папка" in res.json()["detail"]


def test_without_a_repositories_folder_paths_are_absolute(tmp_path, projects):
    repo = git_repo(tmp_path / "repo")
    app.dependency_overrides[get_repositories] = lambda: None
    try:
        assert "Нужен абсолютный путь" in creates(repositories=["repo"]).json()["detail"]
        res = creates(repositories=[str(repo)], notes=str(tmp_path / "docs"))
        assert res.status_code == 201
        assert res.json()["notes_root"] == str((tmp_path / "docs").resolve())
        assert client.get("/api/repositories").json() == {"root": None, "paths": []}
    finally:
        app.dependency_overrides.pop(get_repositories)


def test_working_copies_are_offered_from_the_repositories_folder(repos):
    assert client.get("/api/repositories").json() == {"root": str(repos),
                                                      "paths": ["back", "front"]}
    subprocess.run(["git", "-C", str(repos), "init", "-q"], check=True, capture_output=True)
    assert client.get("/api/repositories").json()["paths"] == [".", "back", "front"]


def test_a_project_whose_folder_no_longer_fits_tells_why(repos, projects, tmp_path):
    app.dependency_overrides[get_repositories] = lambda: None
    project = creates(notes=str(tmp_path / "notes")).json()
    # Каталог репозиториев задали: прежняя папка — вне его.
    app.dependency_overrides[get_repositories] = lambda: repos
    shown = client.get("/api/projects").json()[0]
    assert shown["id"] == project["id"] and shown["notes_root"] is None
    assert "вне каталога репозиториев" in shown["problem"]


def test_a_new_council_takes_the_project_of_the_latest_one(repos, projects):
    project = creates(repositories=["back"]).json()
    first = client.post("/api/councils").json()["id"]
    assert client.get(f"/api/councils/{first}").json()["project"] == ""
    assert client.patch(f"/api/councils/{first}",
                        json={"project": project["id"]}).json()["project"] == project["id"]
    second = client.post("/api/councils").json()["id"]
    assert client.get(f"/api/councils/{second}").json()["project"] == project["id"]
    # Последний совет — без проекта: и новый без него.
    client.patch(f"/api/councils/{second}", json={"project": ""})
    third = client.post("/api/councils").json()["id"]
    assert client.get(f"/api/councils/{third}").json()["project"] == ""


def test_a_new_council_takes_its_project_under_the_councils_lock(repos, projects):
    created = []
    with council_lock:
        worker = threading.Thread(target=lambda: created.append(client.post("/api/councils")))
        worker.start()
        worker.join(0.3)
        assert worker.is_alive() and created == []     # ждёт замка: удаление проекта — под ним же
    worker.join(5)
    assert created[0].status_code == 201


def test_a_council_takes_only_an_existing_project(projects):
    council_id = client.post("/api/councils").json()["id"]
    res = client.patch(f"/api/councils/{council_id}", json={"project": "nope"})
    assert res.status_code == 422 and "Такого проекта нет" in res.json()["detail"]
    assert client.get(f"/api/councils/{council_id}").json()["project"] == ""


def test_a_project_chosen_by_a_council_is_not_deleted(repos, projects):
    project = creates().json()
    council_id = client.post("/api/councils").json()["id"]
    client.patch(f"/api/councils/{council_id}", json={"name": "Уведомления",
                                                      "project": project["id"]})
    res = client.delete(f"/api/projects/{project['id']}")
    assert res.status_code == 409 and "«Уведомления»" in res.json()["detail"]
    client.patch(f"/api/councils/{council_id}", json={"project": ""})
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get("/api/projects").json() == []
    assert client.delete(f"/api/projects/{project['id']}").status_code == 404
    assert client.put(f"/api/projects/{project['id']}",
                      json={"name": "Кромка", "revision": 0}).status_code == 404


def test_the_notes_folder_of_a_council_is_its_projects(tmp_path):
    store, projects = InMemoryStore(), Projects()
    project = projects.create_project(ProjectDraft(name="Кромка", notes="back/docs"))
    council = store.create_council(participants=["sol"], judge="sol", project=project.id)
    root = council_notes(council, projects, tmp_path)
    assert root == (tmp_path / "back" / "docs").resolve()
    alone = store.create_council(participants=["sol"], judge="sol")
    assert council_notes(alone, projects, tmp_path) is None
    # Папка проекта больше не годится — не молча без неё, а отказ с причиной.
    projects.update_project(project.id, ProjectDraft(name="Кромка", notes="../docs"))
    with pytest.raises(HTTPException) as refused:
        council_notes(council, projects, tmp_path)
    assert refused.value.status_code == 422 and "«Кромка»" in refused.value.detail


def test_projects_survive_a_restart_beside_the_councils(tmp_path):
    before = FileProjects(tmp_path / "projects")
    kept = before.create_project(ProjectDraft(name="Кромка", repositories=["back"], notes="docs"))
    gone = before.create_project(ProjectDraft(name="Старый"))
    before.update_project(kept.id, ProjectDraft(name="Кромка", repositories=["back", "front"]))
    before.delete_project(gone.id)
    (tmp_path / "projects" / "broken.json").write_text("{", encoding="utf-8")

    after = FileProjects(tmp_path / "projects")
    assert after.list_projects() == before.list_projects()
    assert after.get_project(kept.id).repositories == ["back", "front"]
    # Советы того же каталога проекты за советы не принимают.
    assert FileStore(tmp_path).list_councils() == []
