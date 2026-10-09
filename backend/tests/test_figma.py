"""Макет Figma: ссылки человека, снимок файла и отказы Figma словами."""

import io
import json
import urllib.error
from email.message import Message

import pytest

from spec_council import figma
from spec_council.figma import Figma, FigmaError, link_of, links_of, refused, snapshot
from spec_council.models import DesignNode
from tests.figma_fake import KEY, LINK, FakeFigma


@pytest.mark.parametrize(("url", "key", "node"), [
    (LINK, KEY, "2:1"),
    (f"https://www.figma.com/file/{KEY}/Billing?node-id=2%3A1", KEY, "2:1"),
    (f"https://figma.com/proto/{KEY}/Billing?node-id=1-0&t=x", KEY, "1:0"),
    (f"https://www.figma.com/design/{KEY}/branch/Br456/Billing?node-id=2-1", "Br456", "2:1"),
    (f"  https://www.figma.com/design/{KEY}/Billing  ", KEY, None),
])
def test_a_link_names_its_file_and_node(url, key, node):
    link = link_of(url)
    assert (link.file_key, link.node_id) == (key, node)


@pytest.mark.parametrize(("url", "problem"), [
    ("https://example.com/design/AbC123/x", "не ссылка на Figma"),
    ("не ссылка", "не ссылка на Figma"),
    ("https://www.figma.com/community/file/123", "нет файла"),
    (f"https://www.figma.com/design/{KEY}/x?node-id=main", "node-id"),
])
def test_a_link_that_is_not_to_a_figma_file_is_refused(url, problem):
    with pytest.raises(FigmaError, match=problem):
        link_of(url)


def test_links_are_to_one_file():
    """Находки ссылаются на узлы без файла, а номера узлов в разных файлах совпадают."""
    with pytest.raises(FigmaError, match="разных файлов"):
        links_of([LINK, "https://www.figma.com/design/Other9/x?node-id=2-1"])
    assert [link.node_id for link in links_of([LINK, f"{LINK.split('?')[0]}?node-id=1-0"])] == [
        "2:1", "1:0"]


def shot(tmp_path, links=(LINK,), fetch=None, name="snap"):
    into = tmp_path / name
    into.mkdir()
    fetch = fetch or FakeFigma()
    return snapshot([link_of(url) for url in links], fetch, into), fetch, into


def test_a_snapshot_holds_the_pages_of_the_links_from_one_version(tmp_path):
    """Страница из ссылки — целиком: структура для чтения, узлы как есть и картинки экранов.
    Все запросы после первого — к той же версии файла."""
    found, fetch, into = shot(tmp_path)
    assert [path for path, _ in fetch.calls if path != "content"] == [
        f"/files/{KEY}", f"/files/{KEY}/nodes", f"/images/{KEY}"]
    assert fetch.calls[0][1] == {"depth": "2"}
    assert all(params.get("version") == "v1" for path, params in fetch.calls[1:3])
    assert fetch.calls[2][1]["ids"] == "2:1,2:4"         # экран из ссылки и экран в секции
    assert sorted(p.relative_to(into).as_posix() for p in into.rglob("*") if p.is_file()) == [
        "file.json", "frames/2-1 Threads.png", "frames/2-4 Card.png",
        "pages/1-0 Screens/outline.txt", "pages/1-0 Screens/page.json"]
    assert found.source.requested == [DesignNode(page_id="1:0", node_id="2:1", name="Threads")]
    assert (found.source.version, found.source.pages, found.source.images) == ("v1", 1, 2)
    assert {"1:0", "2:1", "2:3", "2:5"} <= found.nodes
    assert "3:1" not in found.nodes                       # «Archive» в снимок не попал
    assert found.pages == {"1:0"}


def test_the_outline_tells_texts_components_and_prototype_jumps(tmp_path):
    _, _, into = shot(tmp_path)
    outline = (into / "pages/1-0 Screens/outline.txt").read_text(encoding="utf-8")
    assert "FRAME «Threads» [2:1] 1440×900" in outline
    assert 'TEXT «Title» [2:2] — "Треды\\nпоиск"' in outline        # одной строкой
    assert "INSTANCE «Search button» [2:3] — компонент «Button/State=Default» {State=Default}" \
        in outline
    assert "  → ON_CLICK: NAVIGATE 2:4 «Card»" in outline
    assert "TEXT «Body» [2:5] (скрыт)" in outline
    summary = json.loads((into / "file.json").read_text(encoding="utf-8"))
    assert [page["name"] for page in summary["pages"]] == ["Screens", "Archive / old"]
    assert summary["pages"][1]["in_snapshot"] is None
    assert summary["component_sets"]["5:0"]["description"] == "Основная кнопка"


def test_the_prompt_says_where_to_start_and_what_is_in_the_snapshot(tmp_path):
    found, _, _ = shot(tmp_path)
    assert "«Billing»" in found.prompt and "версия v1" in found.prompt
    assert "- 2:1 «Threads» на странице 1:0 «Screens»" in found.prompt
    assert "- frames/2-4 Card.png — 2:4 «Card»" in found.prompt
    assert "Страницы в снимке целиком: 1:0 «Screens»" in found.prompt


def test_a_node_deeper_than_a_frame_costs_one_more_request_to_find_its_page(tmp_path):
    found, fetch, _ = shot(tmp_path, links=[f"{LINK.split('?')[0]}?node-id=2-3"])
    assert fetch.calls[1] == (f"/files/{KEY}", {"ids": "2:3", "version": "v1"})
    assert found.source.requested[0].page_id == "1:0"


def test_a_node_the_file_does_not_have_is_refused(tmp_path):
    with pytest.raises(FigmaError, match="нет узлов 9:9"):
        shot(tmp_path, links=[f"{LINK.split('?')[0]}?node-id=9-9"])


def test_a_link_without_a_node_takes_every_page(tmp_path):
    found, fetch, _ = shot(tmp_path, links=[LINK.split("?")[0]])
    assert fetch.calls[1][1]["ids"] == "1:0,1:1"
    assert found.source.pages == 2 and "3:2" in found.nodes
    assert "весь файл" in found.prompt


def test_the_fingerprint_is_the_version_and_the_pages_not_the_image_bytes(tmp_path):
    """Ту же версию Figma может отрисовать другими байтами — ответ к ней всё равно годится."""
    first, _, _ = shot(tmp_path, name="a")
    again, _, into = shot(tmp_path, name="b",
                          fetch=FakeFigma(images={"2:1": "https://s3.example/other.png"}))
    assert first.fingerprint == again.fingerprint
    assert (into / "frames/2-1 Threads.png").read_bytes() != b""
    other, _, _ = shot(tmp_path, name="c", fetch=FakeFigma(version="v2"))
    assert other.fingerprint != first.fingerprint


def test_frames_that_did_not_render_are_told(tmp_path):
    found, _, _ = shot(tmp_path, fetch=FakeFigma(images={"2:1": "https://s3.example/2-1.png"}))
    assert found.source.images == 1
    assert "Не отрисовались (смотрите их структуру): 2:4" in found.prompt


def test_images_are_bounded_in_number_and_size(tmp_path, monkeypatch):
    monkeypatch.setattr(figma, "IMAGES_MAX", 1)
    found, fetch, _ = shot(tmp_path, name="few")
    assert fetch.calls[2][1]["ids"] == "2:1"
    assert "Картинок не больше 1" in found.prompt
    monkeypatch.setattr(figma, "IMAGES_MAX", 40)
    monkeypatch.setattr(figma, "IMAGES_SIZE_MAX", 10)
    found, _, _ = shot(tmp_path, name="small")
    assert found.source.images == 0


def test_a_render_error_fails_the_snapshot(tmp_path):
    class Broken(FakeFigma):
        def json(self, path, params):
            if path.startswith("/images/"):
                return {"err": "Render timeout", "images": {}}
            return super().json(path, params)

    with pytest.raises(FigmaError, match="Render timeout"):
        shot(tmp_path, fetch=Broken())


def http_error(code, headers=(), body=b""):
    message = Message()
    for key, value in headers:
        message[key] = value
    return urllib.error.HTTPError("https://api.figma.com/v1/x", code, "x", message,
                                  io.BytesIO(body))


@pytest.mark.parametrize(("error", "told"), [
    (http_error(429, [("Retry-After", "120")]), "повторите через 2 мин"),
    (http_error(403, body=b'{"status":403,"err":"Invalid token"}'),
     "Токен Figma не подходит: истёк, отозван или без права file_content:read — выпустите новый "
     "и впишите его в FIGMA_TOKEN: Invalid token"),
    (http_error(404), "Файла Figma нет или у владельца токена нет к нему доступа"),
    (http_error(500), "ошибка 500"),
])
def test_a_figma_refusal_is_told_in_words(error, told):
    assert told in str(refused(error))


class Opened(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_the_token_goes_to_the_api_and_not_to_the_images(monkeypatch):
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        return Opened(b'{"name": "x"}')

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert Figma("t0ken").json(f"/files/{KEY}", {"depth": "2"}) == {"name": "x"}
    Figma("t0ken").content("https://s3.example/2-1.png", 100)
    assert seen[0].full_url == f"https://api.figma.com/v1/files/{KEY}?depth=2"
    assert seen[0].get_header("X-figma-token") == "t0ken"
    assert seen[1].get_header("X-figma-token") is None


def test_an_answer_beyond_the_limit_is_not_read(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Opened(b"x" * 50))
    with pytest.raises(FigmaError, match="больше"):
        Figma("t").content("https://s3.example/big.png", 10)
