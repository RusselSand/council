"""Репозиторий: inventory рабочей копии, путь к ней, разбор находок и вердикта судьи."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from spec_council import repository
from spec_council.repository import (
    Context,
    Inventory,
    RepositoryError,
    context_prompt,
    inventory,
    inventory_prompt,
    judged_map,
    located,
    map_of,
    sha_prompt,
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


def test_the_inventory_prompt_is_cut_by_its_length_too(repo, monkeypatch):
    """5000 путей по 4 КБ — 20 МБ в каждом промпте: модели такого не примут."""
    monkeypatch.setattr(repository, "INVENTORY_CHARS", len(".gitignore") + 1)
    text = inventory_prompt(inventory(repo))
    assert text.startswith(".gitignore\n")
    assert text.endswith("и ещё 1 файлов: ищите по репозиторию сами")


def test_a_name_that_is_not_utf8_is_shown_as_its_bytes_and_found_back():
    """Имя с байтом не из UTF-8 (так его отдаёт POSIX): в промпте — его байты как \\xNN, модель
    называет его так же — это тот же файл, и карта с ним сохраняется."""
    name = "bad-\udcff.py"
    context = Context(files=frozenset({name}))
    shown = inventory_prompt(Inventory(Path("."), "", False, (name,)))
    shown.encode("utf-8")                                    # промпт уходит в UTF-8
    result = map_of({"findings": [finding(path=shown)], "flows": [
        {"name": "Поток", "entry_point": f"{shown}:main", "steps": []}]}, context)
    assert result.findings[0].status == "verified"
    assert [e.path for e in result.findings[0].evidence] == [shown]
    assert result.flows[0].entry_point == f"{shown}:main"
    result.model_dump_json()


def test_names_shown_alike_before_are_never_taken_for_each_other():
    """Байт не из UTF-8 и те же буквы «\\xNN» в имени другого файла показаны по-разному: ссылка
    на один — не на другой."""
    raw = "bad-\udcff.py"
    literal = os.fsencode(raw).decode("utf-8", "backslashreplace")    # буквами — как виден raw
    context = Context(files=frozenset({raw, literal}))
    shown_raw = inventory_prompt(Inventory(Path("."), "", False, (raw,)))
    shown_literal = inventory_prompt(Inventory(Path("."), "", False, (literal,)))
    assert shown_raw != shown_literal
    assert context.path_of(shown_raw) == raw
    assert context.path_of(shown_literal) == literal


def test_a_newline_in_a_name_is_shown_escaped_and_found_back():
    """Имя с переводом строки показанным как есть — два «файла» списка, и оба настоящие."""
    name = "src/a\nb.py"
    context = Context(files=frozenset({name, "src/a", "b.py"}))
    line = inventory_prompt(Inventory(Path("."), "", False, (name,)))
    assert "\n" not in line
    assert context.path_of(line) == name


def test_a_long_or_spaced_path_is_looked_up_as_it_is():
    """Путь бывает длиннее 2000 символов и с двумя пробелами подряд: ссылку модели не режем и
    не схлопываем, иначе подтверждение отброшено."""
    long_name = "deep/" + "d" * 2500 + ".py"
    spaced = "docs/two  spaces.md"
    context = Context(files=frozenset({long_name, spaced}))
    result = map_of({"findings": [finding(path=long_name), finding("R2", path=spaced)], "flows": [
        {"name": "Поток", "entry_point": f"{long_name}:main", "steps": []}]}, context)
    assert [f.status for f in result.findings] == ["verified", "verified"]
    assert result.flows[0].entry_point == f"{long_name}:main"


def test_a_repository_inside_that_is_not_a_submodule_is_not_the_root_commit(repo):
    """Кода вложенной копии, не подмодуля, в коммите корня нет: карта — не этого коммита, даже
    когда обе копии чисты."""
    nested = repo / "tools"
    nested.mkdir()
    (nested / "README.md").write_text("внешний\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\ntools/*\n!tools/README.md\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "tools")
    (nested / "gen.py").write_text("x = 1\n", encoding="utf-8")
    git(nested, "init", "-q")
    git(nested, "add", ".")
    git(nested, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "gen")
    found = inventory(repo)
    assert "tools/gen.py" in found.files
    assert found.dirty


def test_a_folder_without_its_own_repository_is_refused_before_the_outer_one_is_read(
        tmp_path, monkeypatch):
    """Каталог репозиториев сам лежит в рабочей копии git: папку без своего репозитория git
    отнёс бы к внешней — её не обходим даже ради отказа."""
    outer = tmp_path / "outer"
    base = outer / "repos"
    (base / "plain").mkdir(parents=True)
    git(outer, "init", "-q")
    monkeypatch.setattr(repository, "copies_of", lambda root: pytest.fail("внешнюю копию читали"))
    with pytest.raises(RepositoryError, match="вне каталога репозиториев"):
        working_copy("plain", base)


def test_the_file_cap_holds_across_nested_copies_while_walking_them(with_submodule, monkeypatch):
    """Подмодулей может быть много, у каждого — меньше предела, а вместе — миллионы путей:
    считаем, пока обходим, а не после."""
    monkeypatch.setattr(repository, "FILES_MAX", 4)
    with pytest.raises(RepositoryError, match="много файлов"):
        repository.copies_of(with_submodule)


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


def test_a_duplicate_finding_id_takes_no_other_finding_s_id_and_links_to_it_are_dropped():
    """Номер R1 у двух находок: вторая не должна забрать номер R2 у третьей, а ссылка на R1 —
    на неизвестно какую из двух, её не берём."""
    result = map_of({"findings": [
        finding("R1", statement="первая"), finding("R1", statement="вторая"),
        finding("R2", statement="третья")], "flows": [
        {"name": "Поток", "entry_point": "api/deps.py",
         "steps": [{"description": "шаг", "finding_ids": ["R1", "R2"]}]}]}, CONTEXT)
    assert [(f.id, f.statement) for f in result.findings] == [
        ("R1", "первая"), ("R3", "вторая"), ("R2", "третья")]
    assert result.flows[0].steps[0].finding_ids == ["R2"]


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
    _, edited, _ = copy(inventory(repo), tmp_path, "three")
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


def link_folder(link, target):
    """Каталог-ссылка: на Windows — junction (его можно и без прав администратора)."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_a_file_reached_through_a_linked_folder_is_neither_listed_nor_copied(repo, tmp_path):
    """Каталог в пути подменили ссылкой наружу: файл за ней — чужой, в снимок он не попадёт."""
    (repo / "conf").mkdir()
    (repo / "conf" / "app.ini").write_text("x=1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "conf")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.ini").write_text("TOKEN=секрет\n", encoding="utf-8")
    shutil.rmtree(repo / "conf")
    link_folder(repo / "conf", outside)
    found = inventory(repo)
    assert "conf/app.ini" not in found.files
    forged = Inventory(found.root, found.commit_sha, found.dirty, (*found.files, "conf/app.ini"),
                       found.state)
    with pytest.raises(RepositoryError, match="conf/app.ini"):
        snapshot(forged, tmp_path / "snap")
    assert not (tmp_path / "snap" / "conf" / "app.ini").exists()


def test_a_folder_swapped_for_a_link_to_an_ignored_folder_inside_is_not_copied(repo, tmp_path):
    """Ссылка ведёт внутрь рабочей копии, но в игнорируемое: за ней может быть и .env."""
    (repo / "conf").mkdir()
    (repo / "conf" / "app.ini").write_text("x=1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\nsecret/\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "conf")
    (repo / "secret").mkdir()
    (repo / "secret" / "app.ini").write_text("TOKEN=секрет\n", encoding="utf-8")
    shutil.rmtree(repo / "conf")
    link_folder(repo / "conf", repo / "secret")
    found = inventory(repo)
    assert "conf/app.ini" not in found.files
    forged = Inventory(found.root, found.commit_sha, found.dirty, (*found.files, "conf/app.ini"),
                       found.state)
    with pytest.raises(RepositoryError, match="conf/app.ini"):
        snapshot(forged, tmp_path / "snap")
    assert not (tmp_path / "snap" / "conf" / "app.ini").exists()


def test_a_working_copy_with_too_many_files_is_refused(repo, tmp_path, monkeypatch):
    """Крошечных файлов может быть миллион: байтов мало, а память и inode кончатся."""
    monkeypatch.setattr(repository, "FILES_MAX", 1)
    with pytest.raises(RepositoryError, match="много файлов"):
        working_copy(str(repo), None)


def test_git_output_beyond_the_limit_is_not_read_into_memory(repo, monkeypatch):
    monkeypatch.setattr(repository, "OUTPUT_MAX", 5)
    with pytest.raises(RepositoryError, match="слишком"):
        repository.git_bytes(repo, "ls-files", "-z")


def test_a_working_copy_edited_while_the_snapshot_is_made_is_refused(repo, tmp_path, monkeypatch):
    """Файл поправили, когда он уже скопирован: снимок — смесь старого и нового, не годится."""
    found = inventory(repo)
    copy_one = repository.copied_file

    def edit_after_copy(root, name, target, **options):
        copied = copy_one(root, name, target, **options)
        if name == "api/deps.py":
            (root / name).write_text("def get_context(): return 'новое и длиннее'\n",
                                     encoding="utf-8")
        return copied

    monkeypatch.setattr(repository, "copied_file", edit_after_copy)
    with pytest.raises(RepositoryError, match="менялась"):
        copy(found, tmp_path)


def test_a_working_copy_changed_since_the_inventory_is_refused(repo, tmp_path):
    found = inventory(repo)
    (repo / "added.py").write_text("x = 1\n", encoding="utf-8")       # новый — после inventory
    with pytest.raises(RepositoryError, match="менялась"):
        copy(found, tmp_path)


def test_a_repository_without_commits_can_be_scanned(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "main.py").write_text("x = 1\n", encoding="utf-8")
    git(root, "init", "-q")
    found = inventory(root)
    assert found.commit_sha == ""
    assert found.files == ("main.py",)
    assert "нет коммитов" in sha_prompt(found)


def test_an_entry_point_may_have_spaces_in_its_path():
    context = Context(files=frozenset({"services/payment worker/main.py"}))
    result = map_of({"findings": [], "flows": [
        {"name": "Платёж", "entry_point": "services/payment worker/main.py:run", "steps": []},
        {"name": "Целиком", "entry_point": "services/payment worker/main.py", "steps": []}]},
        context)
    assert [f.entry_point for f in result.flows] == [
        "services/payment worker/main.py:run", "services/payment worker/main.py"]


@pytest.mark.skipif(os.name == "nt", reason="бита исполняемости на Windows нет")
def test_the_executable_bit_is_copied_and_counts_in_the_fingerprint(repo, tmp_path):
    tool = repo / "tool"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    _, plain, _ = copy(inventory(repo), tmp_path, "one")
    tool.chmod(0o755)
    into, executable, _ = copy(inventory(repo), tmp_path, "two")
    assert os.access(into / "tool", os.X_OK)
    assert executable != plain


def test_with_file_mode_off_the_executable_bit_comes_from_the_index(repo, tmp_path):
    """core.fileMode=false: бит на диске git не сверяет — снимок берёт его из индекса, как взял
    бы коммит. Иначе модели видели бы не тот коммит, что показан, а копия — «без правок»."""
    git(repo, "config", "core.fileMode", "false")
    _, plain, _ = copy(inventory(repo), tmp_path, "one")
    git(repo, "update-index", "--chmod=+x", "api/deps.py")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "исполняемый")
    found = inventory(repo)
    assert not found.dirty
    _, executable, _ = copy(found, tmp_path, "two")
    assert executable != plain


@pytest.mark.skipif(os.name == "nt", reason="бита исполняемости на Windows нет")
def test_with_file_mode_off_a_bit_set_only_on_disk_is_not_in_the_snapshot(repo, tmp_path):
    git(repo, "config", "core.fileMode", "false")
    (repo / "api" / "deps.py").chmod(0o755)
    found = inventory(repo)
    assert not found.dirty
    into, _, _ = copy(found, tmp_path)
    assert not os.access(into / "api" / "deps.py", os.X_OK)


def test_a_working_copy_too_big_for_a_snapshot_is_refused_before_copying(repo, tmp_path,
                                                                        monkeypatch):
    """Снимок ложится на диск сервера: без предела большой репозиторий его бы заполнил."""
    monkeypatch.setattr(repository, "SNAPSHOT_MAX", 10)
    with pytest.raises(RepositoryError, match="слишком"):
        working_copy(str(repo), None)
    found = inventory(repo)
    with pytest.raises(RepositoryError, match="слишком"):
        copy(found, tmp_path)
    assert not any((tmp_path / "snap").iterdir())


def test_a_file_that_grows_past_the_limit_while_copying_stops_the_snapshot(repo, tmp_path,
                                                                           monkeypatch):
    found = inventory(repo)
    monkeypatch.setattr(repository, "SNAPSHOT_MAX", 40)
    (repo / "api" / "deps.py").write_bytes(b"x" * 1000)           # вырос после inventory
    with pytest.raises(RepositoryError, match="слишком"):
        copy(found, tmp_path)
    copied = tmp_path / "snap" / "api" / "deps.py"
    assert not copied.exists() or copied.stat().st_size <= 40


def test_the_next_steps_know_the_map_is_of_a_working_copy_with_uncommitted_changes():
    """Коммит — не вся правда о грязной копии: следующие шаги не должны приписать ему её правки."""
    result = map_of({"findings": [finding()]}, CONTEXT)
    dirty = json.loads(context_prompt(result, "abc", dirty=True))
    assert (dirty["commit_sha"], dirty["uncommitted_changes"]) == ("abc", True)
    assert json.loads(context_prompt(result, "abc"))["uncommitted_changes"] is False


def test_a_new_file_swapped_inside_a_submodule_while_copying_is_caught(with_submodule, tmp_path,
                                                                      monkeypatch):
    """Подмодуль и так грязный — его общая пометка не меняется; сверять надо и его содержимое."""
    sub = with_submodule / "vendor" / "lib"
    (sub / "a.txt").write_text("a\n", encoding="utf-8")
    found = inventory(with_submodule)
    copy_one = repository.copied_file

    def swap(root, name, target, **options):
        copied = copy_one(root, name, target, **options)
        if name == ".gitignore":                       # копируется первым — дальше подмена
            (sub / "a.txt").unlink()
            (sub / "b.txt").write_text("b\n", encoding="utf-8")
        return copied

    monkeypatch.setattr(repository, "copied_file", swap)
    with pytest.raises(RepositoryError, match="менялась"):
        copy(found, tmp_path)


def test_a_submodule_replaced_by_a_link_to_its_parent_is_not_walked_in_circles(with_submodule):
    """Подмодуль подменили ссылкой на сам репозиторий: обход не должен ходить по кругу."""
    shutil.rmtree(with_submodule / "vendor" / "lib")
    link_folder(with_submodule / "vendor" / "lib", with_submodule)
    found = inventory(with_submodule)
    assert not any(name.startswith("vendor/lib/") for name in found.files)


def test_a_submodule_checked_out_at_another_commit_marks_the_copy_dirty(with_submodule):
    """В самом подмодуле правок нет, но он не на том коммите, что записан в родителе: снимок —
    уже не показанный коммит."""
    sub = with_submodule / "vendor" / "lib"
    (sub / "lib.py").write_text("def api(): return 2\n", encoding="utf-8")
    git(sub, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-a", "-m", "ещё")
    assert inventory(with_submodule).dirty
    git(with_submodule, "add", "vendor/lib")                    # и записан, но не закоммичен
    assert inventory(with_submodule).dirty


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_an_edit_hidden_by_an_index_flag_still_marks_the_copy_dirty(repo, flag):
    """С этим флагом git status правку не покажет, а модели прочтут уже не коммит."""
    git(repo, "update-index", flag, "api/deps.py")
    assert not inventory(repo).dirty                         # сам флаг — ещё не правка
    (repo / "api" / "deps.py").write_text("def get_context(): return 2\n", encoding="utf-8")
    assert inventory(repo).dirty


def test_a_deleted_file_marked_assume_unchanged_still_marks_the_copy_dirty(repo):
    """Файла коммита нет на диске, а git status молчит: снимок — уже не показанный коммит."""
    git(repo, "update-index", "--assume-unchanged", "api/deps.py")
    (repo / "api" / "deps.py").unlink()
    assert inventory(repo).dirty


def test_a_skip_worktree_file_absent_from_disk_is_a_sparse_checkout_not_an_edit(repo):
    git(repo, "update-index", "--skip-worktree", "api/deps.py")
    (repo / "api" / "deps.py").unlink()
    assert not inventory(repo).dirty


def test_a_submodule_not_checked_out_is_told_not_hidden(with_submodule):
    """Подмодуль не скачан: git status молчит, а кода его нет ни на диске, ни в снимке."""
    git(with_submodule, "submodule", "deinit", "-q", "-f", "vendor/lib")
    found = inventory(with_submodule)
    assert found.absent == ("vendor/lib",)
    assert "подмодули не скачаны: vendor/lib" in inventory_prompt(found)
    result = map_of({"findings": []}, CONTEXT)
    told = json.loads(context_prompt(result, "abc", absent=("vendor/lib",)))
    assert told["submodules_not_checked_out"] == ["vendor/lib"]
    assert told["submodules_not_checked_out_count"] == 1


def test_many_submodules_not_checked_out_are_told_within_a_budget():
    """Нескачанных подмодулей бывают тысячи: карта идёт в каждый промпт ниже — список в ней
    ограничен, а сколько всего — сказано."""
    absent = tuple(f"vendor/lib{n}" for n in range(1000))
    found = Inventory(Path("."), "", False, (), absent=absent)
    assert "и ещё 980" in inventory_prompt(found)
    told = json.loads(context_prompt(map_of({"findings": []}, CONTEXT), "abc", absent=absent))
    assert len(told["submodules_not_checked_out"]) == 20
    assert told["submodules_not_checked_out_count"] == 1000


@pytest.mark.skipif(os.name == "nt", reason="бита исполняемости на Windows нет")
def test_a_flagged_file_made_executable_marks_the_copy_dirty(repo):
    """С флагом git status и смену бита не покажет, а снимок его сохранит."""
    git(repo, "update-index", "--assume-unchanged", "api/deps.py")
    (repo / "api" / "deps.py").chmod(0o755)
    assert inventory(repo).dirty


def test_a_repository_path_keeps_the_spaces_at_its_ends(tmp_path):
    """Каталог « repo» — не «repo»: путь человека не обрезаем, пустой — только из пробелов."""
    (tmp_path / " repo").mkdir()
    (tmp_path / "repo").mkdir()
    assert located(" repo", tmp_path) == (tmp_path / " repo").resolve()
    with pytest.raises(RepositoryError, match="Укажите"):
        located("   ", tmp_path)


def test_an_entry_point_named_with_spaces_at_its_ends_is_that_file():
    """Имя файла бывает и с пробелом в начале или в конце: точную ссылку не обрезаем, обрезанная
    — лишь запасной ход."""
    context = Context(files=frozenset({" api/main.py", "api/main.py", "notes.py "}))
    result = map_of({"findings": [], "flows": [
        {"name": "Один", "entry_point": " api/main.py:run", "steps": []},
        {"name": "Два", "entry_point": "notes.py ", "steps": []},
        {"name": "Три", "entry_point": "  api/main.py  ", "steps": []}]}, context)
    assert [flow.entry_point for flow in result.flows] == [
        " api/main.py:run", "notes.py ", "api/main.py"]


def test_files_left_out_by_a_sparse_checkout_are_told_not_hidden(repo):
    """Файлов коммита вне sparse checkout нет ни на диске, ни в снимке: модели и следующие шаги
    должны знать, что видели не весь коммит."""
    git(repo, "update-index", "--skip-worktree", "api/deps.py")
    (repo / "api" / "deps.py").unlink()
    found = inventory(repo)
    assert found.outside == 1
    assert "вне sparse checkout: 1" in inventory_prompt(found)
    result = map_of({"findings": []}, CONTEXT)
    assert json.loads(context_prompt(result, "abc", outside=1))["files_outside_checkout"] == 1
    assert json.loads(context_prompt(result, "abc"))["files_outside_checkout"] == 0


def test_an_untracked_working_copy_inside_is_scanned_too(repo, tmp_path):
    """Вложенная рабочая копия, не подмодуль: git показывает только её каталог, а код в ней
    модели должны видеть — без её .git и игнорируемого."""
    nested = repo / "tools" / "gen"
    nested.mkdir(parents=True)
    (nested / "gen.py").write_text("x = 1\n", encoding="utf-8")
    (nested / ".gitignore").write_text("*.key\n", encoding="utf-8")
    (nested / "secret.key").write_text("ключ\n", encoding="utf-8")
    git(nested, "init", "-q")
    git(nested, "add", ".")
    git(nested, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "gen")
    (nested / "fresh.py").write_text("y = 2\n", encoding="utf-8")
    found = inventory(repo)
    assert {"tools/gen/.gitignore", "tools/gen/gen.py", "tools/gen/fresh.py"} <= set(found.files)
    assert "tools/gen/secret.key" not in found.files
    assert not any("/.git/" in name for name in found.files)
    into, _, _ = copy(found, tmp_path)
    assert (into / "tools" / "gen" / "fresh.py").is_file()


def test_a_working_copy_inside_a_tracked_folder_keeps_its_own_excludes(repo):
    """В каталоге вложенной копии есть и файлы внешней: --others внешней перечисляет её файлы
    поштучно и её собственных исключений (.git/info/exclude) не знает."""
    nested = repo / "tools"
    nested.mkdir()
    (nested / "README.md").write_text("внешний\n", encoding="utf-8")
    git(repo, "add", "tools/README.md")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "tools")
    git(nested, "init", "-q")
    (nested / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (nested / ".git" / "info" / "exclude").write_text("secret.key\n", encoding="utf-8")
    (nested / "gen.py").write_text("x = 1\n", encoding="utf-8")
    (nested / "secret.key").write_text("ключ\n", encoding="utf-8")
    files = set(inventory(repo).files)
    assert {"tools/README.md", "tools/gen.py"} <= files
    assert "tools/secret.key" not in files


def test_a_flagged_file_edited_after_the_inventory_is_caught_by_the_snapshot(repo, tmp_path):
    git(repo, "update-index", "--assume-unchanged", "api/deps.py")
    found = inventory(repo)
    (repo / "api" / "deps.py").write_text("def get_context(): return 2\n", encoding="utf-8")
    with pytest.raises(RepositoryError, match="менялась"):
        copy(found, tmp_path)


def test_a_file_that_cannot_be_read_fails_the_snapshot_instead_of_vanishing(repo, tmp_path,
                                                                            monkeypatch):
    """Inventory и промпт файл называют: без него карта вышла бы «полной», а его никто не читал."""
    open_one = repository.open_inside

    def locked(root, name):
        if name == "api/deps.py":
            raise PermissionError(13, "Permission denied")
        return open_one(root, name)

    monkeypatch.setattr(repository, "open_inside", locked)
    found = inventory(repo)
    with pytest.raises(RepositoryError, match="api/deps.py"):
        copy(found, tmp_path)


def test_a_backslash_in_a_posix_file_name_is_a_letter_of_the_name():
    """В POSIX «\\» — буква имени: точная ссылка модели — на этот файл, а не на соседний."""
    both = Context(files=frozenset({"api\\deps.py", "api/deps.py"}))
    assert both.path_of("api\\deps.py") == "api\\deps.py"
    assert Context(files=frozenset({"api\\deps.py"})).path_of("api\\deps.py") == "api\\deps.py"


def test_a_windows_style_citation_still_finds_the_file():
    assert Context(files=frozenset({"api/deps.py"})).path_of("api\\deps.py") == "api/deps.py"


@pytest.mark.skipif(os.name == "nt", reason="на Windows имена файлов всегда Unicode")
def test_a_file_name_that_is_not_utf8_is_scanned_as_it_is(repo, tmp_path):
    raw = os.fsencode(repo) + b"/bad-\xff.py"
    with open(raw, "wb") as file:
        file.write(b"x = 1\n")
    name = os.fsdecode(b"bad-\xff.py")
    found = inventory(repo)
    assert name in found.files
    into, _, copied = copy(found, tmp_path)
    assert name in copied
    assert os.path.exists(os.fsencode(into) + b"/bad-\xff.py")
