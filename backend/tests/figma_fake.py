"""Figma без сети — для тестов скана макета: файл из двух страниц. На «Screens» — экран тредов
с заголовком и кнопкой поиска, которая ведёт на карточку; карточка — в секции. «Archive» в
ссылки не попадает."""

import copy

from spec_council.figma import FigmaError

KEY = "AbC123"
LINK = f"https://www.figma.com/design/{KEY}/Billing?node-id=2-1"
BOX = {"x": 0, "y": 0, "width": 1440, "height": 900}
TITLE = {"id": "2:2", "type": "TEXT", "name": "Title", "characters": "Треды\nпоиск"}
BUTTON = {"id": "2:3", "type": "INSTANCE", "name": "Search button", "componentId": "5:1",
          "componentProperties": {"State": {"type": "VARIANT", "value": "Default"}},
          "interactions": [{"trigger": {"type": "ON_CLICK"},
                            "actions": [{"type": "NODE", "destinationId": "2:4",
                                         "navigation": "NAVIGATE"}]}]}
THREADS = {"id": "2:1", "type": "FRAME", "name": "Threads", "absoluteBoundingBox": BOX,
           "children": [TITLE, BUTTON]}
CARD = {"id": "2:4", "type": "FRAME", "name": "Card",
        "children": [{"id": "2:5", "type": "TEXT", "name": "Body", "characters": "Текст",
                      "visible": False}]}
SCREENS = {"id": "1:0", "type": "CANVAS", "name": "Screens",
           "children": [THREADS, {"id": "2:6", "type": "SECTION", "name": "Flows",
                                  "children": [CARD]}]}
ARCHIVE = {"id": "1:1", "type": "CANVAS", "name": "Archive / old",
           "children": [{"id": "3:1", "type": "FRAME", "name": "Old",
                         "children": [{"id": "3:2", "type": "TEXT", "name": "x",
                                       "characters": "старое"}]}]}
PAGES = {"1:0": SCREENS, "1:1": ARCHIVE}
COMPONENTS = {"5:1": {"name": "State=Default", "componentSetId": "5:0", "description": ""}}
SETS = {"5:0": {"name": "Button", "description": "Основная кнопка"}}


def shallow(node, depth):
    """Узел до глубины depth — как файл с depth=…"""
    node = dict(node)
    if depth <= 0:
        node.pop("children", None)
    elif "children" in node:
        node["children"] = [shallow(child, depth - 1) for child in node["children"]]
    return node


class FakeFigma:
    """Отвечает, как REST API Figma, и помнит запросы. fail — чем отказать на любой запрос;
    images — ссылки на картинки по узлам (None — Figma не отрисовала)."""

    def __init__(self, version="v1", fail=None, images=None):
        self.version = version
        self.fail = fail
        self.calls = []
        self.images = images if images is not None else {
            node: f"https://s3.example/{node}.png" for node in ("2:1", "2:4", "3:1")}

    def json(self, path, params):
        self.calls.append((path, dict(params)))
        if self.fail is not None:
            raise self.fail
        document = {"id": "0:0", "type": "DOCUMENT",
                    "children": [copy.deepcopy(page) for page in PAGES.values()]}
        if path == f"/files/{KEY}":
            depth = int(params.get("depth", 99))
            return {"name": "Billing", "version": self.version,
                    "lastModified": "2026-10-01T10:00:00Z",
                    "document": shallow(document, depth), "components": COMPONENTS,
                    "componentSets": SETS}
        if path == f"/files/{KEY}/nodes":
            return {"nodes": {node: {"document": copy.deepcopy(PAGES[node]),
                                     "components": COMPONENTS, "componentSets": SETS}
                              if node in PAGES else None
                              for node in params["ids"].split(",")}}
        if path == f"/images/{KEY}":
            return {"err": None, "images": {node: self.images.get(node)
                                            for node in params["ids"].split(",")}}
        raise FigmaError(f"нет такого: {path}")

    def content(self, url, limit):
        self.calls.append(("content", url))
        data = f"PNG {url} {self.version}".encode()
        if len(data) > limit:
            raise FigmaError("слишком большая картинка")
        return data
