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
    snapshot,
    working_copy,
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
    assert len(found.commit_sha) == 40
    assert found.dirty


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
    assert [step.finding_ids for step in result.flows[0].steps] == [["R1"]]   # пустой шаг выпал
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
    assert done.complete
    assert done.follow_up == ()
    # Доисследовать нечего — это тоже конец.
    assert judged_map({"status": "needs_investigation", "findings": []}, CONTEXT).complete
    with pytest.raises(BadAnswer, match="status"):
        judged_map({"status": "partial", "findings": []}, CONTEXT)


def test_the_next_steps_get_the_map_or_an_honest_no_scan():
    assert "не исследовался" in context_prompt(None)
    text = context_prompt(map_of({"findings": [finding()]}, CONTEXT), "abc")
    assert '"commit_sha": "abc"' in text
    assert "get_context" in text


def test_a_working_copy_whose_root_is_outside_the_repositories_folder_is_refused(repo):
    """Каталог репозиториев внутри большего репозитория: корень git — выше него, и модели
    увидели бы то, что каталог отрезает."""
    with pytest.raises(RepositoryError, match="вне каталога"):
        working_copy(".", repo / "api")
    assert working_copy("project", repo.parent).root == repo.resolve()


def test_file_names_come_as_they_are_and_deleted_ones_are_not_files(repo):
    (repo / "файл.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ещё")
    (repo / "api" / "deps.py").unlink()                               # удалён, но отслеживается
    assert inventory(repo).files == (".gitignore", "файл.py")


def copy(found, tmp_path, name="snap"):
    """Снимок рабочей копии в свой каталог: (каталог, отпечаток, что в нём есть)."""
    into = tmp_path / name
    into.mkdir()
    print_, copied = snapshot(found, into)
    return into, print_, copied


def test_a_snapshot_holds_only_the_inventory_files(repo, tmp_path):
    """Игнорируемое (там бывают .env и ключи) и .git модели не видят: их нет в снимке."""
    (repo / "secret.log").write_text("token=123\n", encoding="utf-8")   # игнорируется
    (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
    found = inventory(repo)
    into, _, copied = copy(found, tmp_path)
    present = sorted(p.relative_to(into).as_posix() for p in into.rglob("*") if p.is_file())
    assert present == [".gitignore", "api/deps.py", "new.py"]
    assert copied == frozenset(present)
    assert not (into / ".git").exists()
    assert (into / "api" / "deps.py").read_text(encoding="utf-8") == "def get_context(): ...\n"


def test_the_snapshot_fingerprint_is_its_content(repo, tmp_path):
    """Один и тот же код — один отпечаток, в какой бы копии он ни лежал; другой код — другой."""
    found = inventory(repo)
    _, first, _ = copy(found, tmp_path, "one")
    _, again, _ = copy(found, tmp_path, "two")
    assert first == again
    (repo / "api" / "deps.py").write_text("def get_context(): return 1\n", encoding="utf-8")
    _, edited, _ = copy(found, tmp_path, "three")
    assert edited != first
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True)
    (repo / "api" / "deps.py").write_text("def get_context(): ...\n", encoding="utf-8")
    _, cloned, _ = copy(inventory(clone), tmp_path, "four")
    assert cloned == first                                            # тот же код — тот же ключ


def test_the_snapshot_does_not_change_when_the_working_copy_does(repo, tmp_path):
    """Правку во время скана модели не увидят: они читают снимок, а он неподвижен."""
    into, _, _ = copy(inventory(repo), tmp_path)
    (repo / "api" / "deps.py").write_text("def get_context(): return 2\n", encoding="utf-8")
    assert (into / "api" / "deps.py").read_text(encoding="utf-8") == "def get_context(): ...\n"


def test_a_link_is_not_a_file_of_the_inventory(repo, tmp_path):
    """Ссылку не разыменовываем: за ней может быть что угодно, вплоть до /dev/zero или ключей."""
    outside = tmp_path / "outside.txt"
    outside.write_text("секрет", encoding="utf-8")
    try:
        (repo / "link").symlink_to(outside)
    except OSError:
        pytest.skip("символьные ссылки здесь создавать нельзя")
    assert "link" not in inventory(repo).files


@pytest.fixture
def with_submodule(repo, tmp_path):
    """В project — подмодуль vendor/lib с lib.py."""
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "lib.py").write_text("def api(): ...\n", encoding="utf-8")
    git(lib, "init", "-q")
    git(lib, "add", ".")
    git(lib, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "lib")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "vendor/lib")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "подмодуль")
    return repo


def test_files_of_a_checked_out_submodule_are_in_the_inventory(with_submodule):
    files = inventory(with_submodule).files
    assert "vendor/lib/lib.py" in files
    assert "vendor/lib" not in files                                  # не сам gitlink


def test_a_new_file_inside_a_submodule_is_in_the_inventory_and_the_snapshot(with_submodule,
                                                                             tmp_path):
    """--others в подмодули не заходит: их новые файлы модели читают, значит, и мы их видим."""
    (with_submodule / "vendor" / "lib" / "fresh.py").write_text("a = 1\n", encoding="utf-8")
    found = inventory(with_submodule)
    assert "vendor/lib/fresh.py" in found.files
    into, _, _ = copy(found, tmp_path)
    assert (into / "vendor" / "lib" / "fresh.py").is_file()


def test_evidence_may_name_a_file_by_its_path_in_the_snapshot(tmp_path):
    """Модель может назвать файл и полным путём в снимке — это тот же файл."""
    context = Context(files=frozenset({"api/deps.py"}), roots=(tmp_path,))
    full = f"{tmp_path.as_posix()}/api/deps.py"
    result = map_of({"findings": [finding(path=full)]}, context)
    assert [e.path for e in result.findings[0].evidence] == ["api/deps.py"]


def test_a_flow_entry_point_must_be_a_file_of_the_repository():
    """Точка входа, которой в репозитории нет, — не точка входа: следующие шаги ей бы поверили."""
    result = map_of({"findings": [finding()], "flows": [
        {"name": "Запрос", "entry_point": "api/deps.py:get_context", "steps": []},
        {"name": "Выдуманный", "entry_point": "api/nowhere.py", "steps": []}]}, CONTEXT)
    assert [(f.name, f.entry_point) for f in result.flows] == [
        ("Запрос", "api/deps.py:get_context"), ("Выдуманный", "")]
