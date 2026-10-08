"""Репозиторий: inventory рабочей копии, путь к ней, разбор находок и вердикта судьи."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from spec_council.repository import (
    Context,
    RepositoryError,
    context_prompt,
    file_state,
    inventory,
    inventory_prompt,
    judged_map,
    located,
    map_of,
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


def test_the_fingerprint_follows_the_working_copy_state(repo, tmp_path):
    deps = repo / "api" / "deps.py"
    clean = inventory(repo).fingerprint
    assert inventory(repo).fingerprint == clean                       # то же состояние — тот же
    deps.write_text("def get_context(): return 1\n", encoding="utf-8")
    edited = inventory(repo).fingerprint
    assert edited != clean
    deps.write_text("def get_context(): return 2\n", encoding="utf-8")
    assert inventory(repo).fingerprint != edited                      # правка поверх правки
    (repo / "new.py").write_text("a\n", encoding="utf-8")
    with_new = inventory(repo).fingerprint
    (repo / "new.py").write_text("b\n", encoding="utf-8")
    assert inventory(repo).fingerprint != with_new                    # новый файл — по содержимому
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True)
    assert inventory(clone).commit_sha == inventory(repo).commit_sha
    deps.write_text("def get_context(): ...\n", encoding="utf-8")
    (repo / "new.py").unlink()
    assert inventory(repo).fingerprint == clean                       # вернули как было
    assert inventory(clone).fingerprint != clean                      # другой клон — другой ключ


def test_an_untracked_symlink_counts_as_a_link_not_as_what_it_points_to(repo, tmp_path):
    """Ссылку не разыменовываем: за ней может быть что угодно, вплоть до /dev/zero."""
    outside = tmp_path / "outside.txt"
    outside.write_text("раз", encoding="utf-8")
    try:
        (repo / "link").symlink_to(outside)
    except OSError:
        pytest.skip("символьные ссылки здесь создавать нельзя")
    linked = inventory(repo).fingerprint
    outside.write_text("два", encoding="utf-8")
    assert inventory(repo).fingerprint == linked


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


def test_an_edit_inside_a_submodule_changes_the_fingerprint(with_submodule):
    """Не только «подмодуль грязный», а какая именно правка: правка поверх правки — другой код."""
    lib = with_submodule / "vendor" / "lib" / "lib.py"
    lib.write_text("def api(): return 1\n", encoding="utf-8")
    first = inventory(with_submodule).fingerprint
    lib.write_text("def api(): return 2\n", encoding="utf-8")
    assert inventory(with_submodule).fingerprint != first


def test_a_link_is_hashed_by_where_it_points_and_never_read(tmp_path, monkeypatch):
    """Ссылка — это её цель словами, а не содержимое: оно может быть бесконечным (/dev/zero)."""
    link = tmp_path / "link"
    as_link = os.stat_result((stat.S_IFLNK | 0o777,) + (0,) * 9)
    monkeypatch.setattr(Path, "lstat", lambda self: as_link)
    monkeypatch.setattr(os, "readlink", lambda path: "/dev/zero")
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("ссылку читать нельзя"))
    assert file_state(link) == file_state(link)
    monkeypatch.setattr(os, "readlink", lambda path: "/etc/passwd")
    assert file_state(link) != b"link:/dev/zero"


def test_a_regular_file_is_hashed_by_its_content(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.write_bytes(b"x" * 3_000_000)
    two.write_bytes(b"x" * 3_000_000)
    assert file_state(one) == file_state(two)
    two.write_bytes(b"y")
    assert file_state(one) != file_state(two)
