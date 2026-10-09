"""Макет Figma для шага «Дизайн»: ссылки человека и снимок файла через REST API Figma.

Снимок делает совет сам, а не модели через MCP: все участники и все проходы читают одну и ту
же версию макета, ответы ключуются её содержимым, а в ходе модели нет ни сети, ни токена.
Токен — персональный (FIGMA_TOKEN) с правом file_content:read. Запросы к файлу и картинкам
Figma ограничивает по месту владельца токена: у Dev и Full — десятки в минуту, у View и
Collab — 20 в месяц. Поэтому снимок — 3–4 запроса:
1. файл до верхних фреймов страниц (depth=2): версия, страницы, что на них;
2. если ссылка ведёт глубже верхнего фрейма — где этот узел (ids=…);
3. страницы из ссылок целиком (files/:key/nodes) — с той же версии;
4. картинки фреймов (images/:key) — с той же версии; сами картинки лежат вне API, и токен
   туда не уходит.
"""

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlparse

from .models import DesignNode, FigmaSource

API = "https://api.figma.com/v1"
TIMEOUT = 60
# Ответ API больше этого не читаем: файл в сотни мегабайт — ссылки нужны на страницы.
RESPONSE_MAX = 64 * 2**20
# Картинки фреймов: сколько отрисовать и сколько они весят все вместе.
IMAGES_MAX = 40
IMAGES_SIZE_MAX = 256 * 2**20
# Что в снимке отрисовывается картинкой: экраны, а не группы и секции целиком.
SCREENS = ("FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE", "GROUP")
FILE_PATH = re.compile(r"/(?:design|file|proto|board)/([0-9A-Za-z]+)(?:/branch/([0-9A-Za-z]+))?")
# Узел Figma: «12:34», в ссылке — «12-34»; слой внутри экземпляра — «I12:34;56:78».
NODE_ID = re.compile(r"I?\d+:\d+(?:;\d+:\d+)*")
TEXT_SHOWN = 500
SOURCE_CHARS = 60_000


class FigmaError(ValueError):
    """Макет не прочитать: ссылка не на Figma, токена нет или он не подходит, файла нет,
    Figma ограничила запросы. Текст — для человека."""


@dataclass(frozen=True)
class Link:
    """Ссылка человека: файл и узел, с которого начинать; None — весь файл."""

    url: str
    file_key: str
    node_id: str | None


def node_id_of(text: str) -> str:
    """Узел, как его пишут в ссылке («12-34») или в API («12:34»), — как в API."""
    text = text.strip()
    if re.fullmatch(r"I?\d+-\d+(?:;\d+-\d+)*", text):
        text = text.replace("-", ":")
    return text


def link_of(text: str) -> Link:
    url = text.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (host == "figma.com"
                                                      or host.endswith(".figma.com")):
        raise FigmaError(f"Это не ссылка на Figma: {url or '(пусто)'}")
    match = FILE_PATH.match(parsed.path)
    if match is None:
        raise FigmaError(f"В ссылке нет файла Figma: {url}")
    nodes = parse_qs(parsed.query).get("node-id", [])
    node = node_id_of(nodes[0]) if nodes else None
    if node is not None and not NODE_ID.fullmatch(node):
        raise FigmaError(f"Непонятный node-id в ссылке: {url}")
    return Link(url, match.group(2) or match.group(1), node)


def links_of(texts: Sequence[str]) -> list[Link]:
    """Ссылки человека — на один файл Figma: находки ссылаются на узлы без файла, а номера
    узлов в разных файлах совпадают."""
    links = [link_of(text) for text in texts]
    keys = list(dict.fromkeys(link.file_key for link in links))
    if len(keys) > 1:
        raise FigmaError("Ссылки — из разных файлов Figma: один скан — один файл, его страницы "
                         "и фреймы")
    return links


class Fetcher(Protocol):
    """Как ходить в Figma: JSON из API и картинки по их ссылкам."""

    def json(self, path: str, params: Mapping[str, str]) -> dict: ...

    def content(self, url: str, limit: int) -> bytes: ...


@dataclass(frozen=True)
class Figma:
    """REST API Figma с персональным токеном."""

    token: str

    def json(self, path: str, params: Mapping[str, str]) -> dict:
        data = fetched(f"{API}{path}?{urlencode(params)}", {"X-Figma-Token": self.token},
                       RESPONSE_MAX)
        try:
            value = json.loads(data)
        except ValueError:
            raise FigmaError("Figma ответила не JSON — попробуйте позже") from None
        if not isinstance(value, dict):
            raise FigmaError("Figma ответила не так, как ждали, — попробуйте позже")
        return value

    def content(self, url: str, limit: int) -> bytes:
        return fetched(url, {}, limit)


def fetched(url: str, headers: Mapping[str, str], limit: int) -> bytes:
    request = urllib.request.Request(url, headers={**headers, "User-Agent": "spec-council"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise refused(exc) from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise FigmaError(f"Figma недоступна: {reason}") from None
    if len(data) > limit:
        raise FigmaError(f"Ответ Figma больше {limit // 2**20} МБ — дайте ссылки на страницы "
                         "или фреймы, а не на весь файл")
    return data


def refused(exc: urllib.error.HTTPError) -> FigmaError:
    """Отказ Figma — словами: что не так и что делать."""
    told = said(exc)
    if exc.code == 429:
        wait = exc.headers.get("Retry-After", "")
        when = f" через {max(1, round(int(wait) / 60))} мин" if wait.isdigit() else " позже"
        kind = exc.headers.get("X-Figma-Rate-Limit-Type", "")
        return FigmaError(f"Figma ограничила запросы владельца токена{f' ({kind})' if kind else ''}"
                          f" — повторите{when}. У места View или Collab это 20 запросов в месяц:"
                          " нужно место Dev или Full")
    if exc.code in (401, 403):
        return FigmaError("Токен Figma не подходит: истёк, отозван или без права file_content:read"
                          f" — выпустите новый и впишите его в FIGMA_TOKEN{told}")
    if exc.code == 404:
        return FigmaError(f"Файла Figma нет или у владельца токена нет к нему доступа{told}")
    if exc.code == 400:
        return FigmaError(f"Figma не приняла запрос{told}")
    return FigmaError(f"Figma не ответила: ошибка {exc.code}{told}")


def said(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read(4096) or b"{}")
    except (ValueError, OSError):
        return ""
    message = body.get("err") or body.get("message") if isinstance(body, dict) else None
    return f": {message}" if isinstance(message, str) and message else ""


# --- снимок


@dataclass(frozen=True)
class Snapshot:
    """Снимок макета: что легло в каталог, на какие узлы можно ссылаться, что сказать моделям
    ({{figma_source}}) и отпечаток — по версии файла и его страницам, без картинок: Figma может
    отрисовать ту же версию другими байтами, а ответ к ней годится."""

    source: FigmaSource
    nodes: frozenset[str]
    pages: frozenset[str]
    prompt: str
    fingerprint: str


def children(node: Mapping) -> list[dict]:
    items = node.get("children")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def walked(node: Mapping) -> Iterator[dict]:
    """Узел и все под ним, без рекурсии: дерево макета бывает глубоким."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(children(current)))


def text(value: object) -> str:
    """Имя или текст узла — одной строкой: перевод строки разбил бы строку структуры."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def snapshot(links: Sequence[Link], fetch: Fetcher, into: Path) -> Snapshot:
    """Снимок файла Figma в каталог into: страницы из ссылок целиком — их структура и узлы как
    есть, — картинки фреймов и сводка файла. Все запросы — к одной версии файла."""
    key = links[0].file_key
    meta = fetch.json(f"/files/{key}", {"depth": "2"})
    version = str(meta.get("version") or "")
    document = meta.get("document") if isinstance(meta.get("document"), dict) else {}
    outline = [page for page in children(document) if page.get("type") == "CANVAS"]
    if not outline:
        raise FigmaError("В файле Figma нет страниц")
    pinned = {"version": version} if version else {}
    requested = list(dict.fromkeys(link.node_id for link in links if link.node_id))
    whole = any(link.node_id is None for link in links)
    homes = home_pages(key, requested, outline, fetch, pinned)
    targets = [page["id"] for page in outline] if whole else list(dict.fromkeys(homes.values()))
    pages = full_pages(key, targets, outline, fetch, pinned)
    components = component_map(meta, "components")
    sets = component_map(meta, "componentSets")
    for entry in pages.values():
        components |= component_map(entry, "components")
        sets |= component_map(entry, "componentSets")
    names = {str(node.get("id")): text(node.get("name"))
             for entry in pages.values() for node in walked(entry["document"])}
    digest = hashlib.sha256(f"{key}\0{version}\0{','.join(sorted(requested))}\0{whole}".encode())
    for page_id in targets:
        raw = json.dumps(pages[page_id]["document"], ensure_ascii=False, sort_keys=True)
        digest.update(f"\0{page_id}\0".encode() + raw.encode())
        write_page(into, pages[page_id]["document"], raw, names, components, sets)
    frames = rendered(key, requested, [pages[page_id]["document"] for page_id in targets], names,
                      fetch, pinned, into)
    page_names = {page["id"]: text(page.get("name")) for page in outline}
    source = FigmaSource(
        file_key=key, name=text(meta.get("name")), version=version,
        last_modified=str(meta.get("lastModified") or ""),
        requested=[DesignNode(page_id=homes[node], node_id=node, name=names.get(node, ""))
                   for node in requested],
        pages=len(targets), images=sum(1 for _, path in frames if path))
    write_summary(into, source, outline, components, sets, frames)
    return Snapshot(source=source, nodes=frozenset(names), pages=frozenset(targets),
                    prompt=source_prompt(source, [link.url for link in links], whole, targets,
                                         page_names, frames, names),
                    fingerprint=digest.hexdigest())


def home_pages(key: str, requested: list[str], outline: list[dict], fetch: Fetcher,
               pinned: Mapping[str, str]) -> dict[str, str]:
    """На какой странице каждый узел из ссылок. Страница или её верхний фрейм видны в
    кратком файле; глубже — ещё запрос, с путём от корня до узла."""
    homes: dict[str, str] = {}
    for page in outline:
        for node in (page, *children(page)):
            if node.get("id") in requested:
                homes[node["id"]] = page["id"]
    deep = [node for node in requested if node not in homes]
    if deep:
        found = fetch.json(f"/files/{key}", {"ids": ",".join(deep), **pinned})
        document = found.get("document") if isinstance(found.get("document"), dict) else {}
        for page in children(document):
            for node in walked(page):
                if node.get("id") in deep:
                    homes[node["id"]] = str(page.get("id"))
    lost = [node for node in requested if node not in homes]
    if lost:
        raise FigmaError(f"В файле Figma нет узлов {', '.join(lost)} — проверьте ссылки")
    return homes


def full_pages(key: str, targets: list[str], outline: list[dict], fetch: Fetcher,
               pinned: Mapping[str, str]) -> dict[str, dict]:
    found = fetch.json(f"/files/{key}/nodes", {"ids": ",".join(targets), **pinned})
    nodes = found.get("nodes") if isinstance(found.get("nodes"), dict) else {}
    pages: dict[str, dict] = {}
    for page_id in targets:
        entry = nodes.get(page_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("document"), dict):
            name = next((text(page.get("name")) for page in outline if page["id"] == page_id), "")
            raise FigmaError(f"Страницу «{name or page_id}» Figma не отдала — попробуйте позже")
        pages[page_id] = entry
    return pages


def component_map(entry: Mapping, field: str) -> dict[str, dict]:
    items = entry.get(field)
    return {str(k): v for k, v in items.items() if isinstance(v, dict)} if isinstance(
        items, dict) else {}


def slug(value: str) -> str:
    """Имя для файла снимка: id и имя узла без знаков, которых не любят файловые системы."""
    cleaned = re.sub(r"[^\w .-]+", "_", value).strip(" .")
    return cleaned[:60].strip(" .") or "_"


def page_folder(page: Mapping) -> str:
    return f"pages/{slug(str(page.get('id')).replace(':', '-'))} {slug(text(page.get('name')))}"


def write_page(into: Path, page: dict, raw: str, names: Mapping[str, str],
               components: Mapping[str, dict], sets: Mapping[str, dict]) -> None:
    folder = into / page_folder(page)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.json").write_text(raw, encoding="utf-8")
    lines = [line for top in children(page) for line in outline_of(top, names, components, sets)]
    (folder / "outline.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def outline_of(top: dict, names: Mapping[str, str], components: Mapping[str, dict],
               sets: Mapping[str, dict]) -> Iterator[str]:
    """Структура узла строками с отступом: тип, имя, id, размер, текст, компонент и его
    варианты, прототипные переходы (→)."""
    stack: list[tuple[dict, int]] = [(top, 0)]
    while stack:
        node, depth = stack.pop()
        pad = "  " * depth
        yield pad + line_of(node, components, sets)
        for jump in jumps_of(node, names):
            yield f"{pad}  → {jump}"
        stack.extend((child, depth + 1) for child in reversed(children(node)))


def line_of(node: Mapping, components: Mapping[str, dict], sets: Mapping[str, dict]) -> str:
    line = f"{node.get('type')} «{text(node.get('name'))}» [{node.get('id')}]"
    box = node.get("absoluteBoundingBox")
    if isinstance(box, dict) and isinstance(box.get("width"), int | float):
        line += f" {round(box['width'])}×{round(box.get('height') or 0)}"
    if node.get("visible") is False:
        line += " (скрыт)"
    kind = node.get("type")
    if kind == "TEXT":
        written = json.dumps(str(node.get("characters") or ""), ensure_ascii=False)
        line += f" — {written[:TEXT_SHOWN]}"
    elif kind == "INSTANCE":
        line += instance_of(node, components, sets)
    elif kind in ("COMPONENT", "COMPONENT_SET"):
        described = (components if kind == "COMPONENT" else sets).get(str(node.get("id")), {})
        if text(described.get("description")):
            line += f" — описание: {text(described.get('description'))[:TEXT_SHOWN]}"
    return line


def instance_of(node: Mapping, components: Mapping[str, dict], sets: Mapping[str, dict]) -> str:
    component = components.get(str(node.get("componentId")), {})
    family = sets.get(str(component.get("componentSetId")), {})
    name = "/".join(n for n in (text(family.get("name")), text(component.get("name"))) if n)
    line = f" — компонент «{name}»" if name else ""
    props = node.get("componentProperties")
    if isinstance(props, dict) and props:
        shown = ", ".join(f"{text(k)}={text(str(v.get('value')))}" for k, v in props.items()
                          if isinstance(v, dict))
        line += f" {{{shown}}}"
    return line


def jumps_of(node: Mapping, names: Mapping[str, str]) -> list[str]:
    """Прототипные переходы узла: по какому событию куда. Новые interactions, старые
    reactions и совсем старый transitionNodeID."""
    found: list[str] = []
    for reaction in [*listed(node.get("interactions")), *listed(node.get("reactions"))]:
        trigger = reaction.get("trigger") if isinstance(reaction.get("trigger"), dict) else {}
        actions = listed(reaction.get("actions")) or listed([reaction.get("action")])
        for action in actions:
            found.append(f"{trigger.get('type') or '?'}: {action_of(action, names)}")
    if not found and node.get("transitionNodeID"):
        target = str(node["transitionNodeID"])
        found.append(f"NAVIGATE {target} «{names.get(target, '')}»")
    return list(dict.fromkeys(found))


def listed(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def action_of(action: Mapping, names: Mapping[str, str]) -> str:
    kind = action.get("type")
    if kind == "NODE":
        target = str(action.get("destinationId") or "")
        return f"{action.get('navigation') or 'NAVIGATE'} {target} «{names.get(target, '')}»"
    if kind == "URL":
        return f"URL {text(action.get('url'))}"
    return str(kind or "?")


def screens_of(page: dict) -> list[dict]:
    """Экраны страницы: верхние фреймы, а у секций — фреймы внутри них."""
    found: list[dict] = []
    stack = list(reversed(children(page)))
    while stack:
        node = stack.pop()
        if node.get("type") == "SECTION":
            stack.extend(reversed(children(node)))
        elif node.get("type") in SCREENS:
            found.append(node)
    return found


def rendered(key: str, requested: list[str], pages: list[dict], names: Mapping[str, str],
             fetch: Fetcher, pinned: Mapping[str, str], into: Path) -> list[tuple[str, str]]:
    """Картинки фреймов: сначала узлы из ссылок, потом экраны страниц — не больше IMAGES_MAX
    и IMAGES_SIZE_MAX вместе. Вернёт (узел, путь картинки в снимке или "" — не отрисовалась)."""
    wanted = [node for node in requested if node in names and node not in
              {str(page.get("id")) for page in pages}]
    wanted += [str(node.get("id")) for page in pages for node in screens_of(page)]
    wanted = list(dict.fromkeys(wanted))[:IMAGES_MAX]
    if not wanted:
        return []
    found = fetch.json(f"/images/{key}", {"ids": ",".join(wanted), "format": "png",
                                          "scale": "1", **pinned})
    if found.get("err"):
        raise FigmaError(f"Figma не отрисовала фреймы: {found['err']}")
    urls = found.get("images") if isinstance(found.get("images"), dict) else {}
    frames: list[tuple[str, str]] = []
    left = IMAGES_SIZE_MAX
    for node in wanted:
        url = urls.get(node)
        path = f"frames/{slug(node.replace(':', '-'))} {slug(names.get(node, ''))}.png"
        if not isinstance(url, str) or not url or left <= 0:
            frames.append((node, ""))
            continue
        try:
            data = fetch.content(url, left)
        except FigmaError:
            frames.append((node, ""))
            continue
        (into / "frames").mkdir(exist_ok=True)
        (into / path).write_bytes(data)
        left -= len(data)
        frames.append((node, path))
    return frames


def write_summary(into: Path, source: FigmaSource, outline: list[dict],
                  components: Mapping[str, dict], sets: Mapping[str, dict],
                  frames: list[tuple[str, str]]) -> None:
    summary = {
        "file": source.model_dump(mode="json"),
        "pages": [{"id": page.get("id"), "name": text(page.get("name")),
                   "in_snapshot": page_folder(page) if (into / page_folder(page)).exists()
                   else None,
                   "frames": [{"id": node.get("id"), "type": node.get("type"),
                               "name": text(node.get("name"))} for node in children(page)]}
                  for page in outline],
        "components": {k: {"name": text(v.get("name")), "description": text(v.get("description")),
                           "component_set_id": v.get("componentSetId")}
                       for k, v in components.items()},
        "component_sets": {k: {"name": text(v.get("name")),
                               "description": text(v.get("description"))}
                           for k, v in sets.items()},
        "images": [{"node_id": node, "path": path or None} for node, path in frames],
    }
    (into / "file.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                    encoding="utf-8")


def source_prompt(source: FigmaSource, urls: list[str], whole: bool, targets: list[str],
                  page_names: Mapping[str, str], frames: list[tuple[str, str]],
                  names: Mapping[str, str]) -> str:
    """{{figma_source}}: какой файл, с чего начинать и что лежит в снимке."""
    lines = [f"Файл Figma «{source.name}» (file key {source.file_key}), версия {source.version}"
             f", изменён {source.last_modified}.", "Ссылки человека:",
             *(f"- {url}" for url in urls)]
    if source.requested:
        lines.append("Начинать с узлов:")
        lines += [f"- {node.node_id} «{node.name}» на странице "
                  f"{node.page_id} «{page_names.get(node.page_id, '')}»"
                  for node in source.requested]
    if whole:
        lines.append("Одна из ссылок — на весь файл: в снимке все его страницы.")
    lines += [
        "", "Снимок макета — в текущем каталоге, только на чтение:",
        "- file.json — все страницы файла с их верхними фреймами, компоненты и наборы вариантов;",
        "- pages/<id> <страница>/outline.txt — структура страницы: узлы с id, типом, именем, "
        "размером, текстами, компонентами и вариантами, прототипными переходами (→);",
        "- pages/<id> <страница>/page.json — та же страница из Figma как есть, со всеми "
        "свойствами;",
        "- frames/<id> <имя>.png — картинки фреймов.",
        "Страницы в снимке целиком: " + ", ".join(
            f"{page} «{page_names.get(page, '')}»" for page in targets) + ". Остальных страниц "
        "в снимке нет — только их названия и верхние фреймы в file.json.",
    ]
    drawn = [(node, path) for node, path in frames if path]
    if drawn:
        lines.append("Картинки фреймов:")
        lines += [f"- {path} — {node} «{names.get(node, '')}»" for node, path in drawn]
    missing = [node for node, path in frames if not path]
    if missing:
        lines.append("Не отрисовались (смотрите их структуру): " + ", ".join(missing))
    if len(frames) == IMAGES_MAX:
        lines.append(f"Картинок не больше {IMAGES_MAX}: остальные экраны — только структурой.")
    return "\n".join(lines)[:SOURCE_CHARS]
