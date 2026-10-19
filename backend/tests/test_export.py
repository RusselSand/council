"""Выгрузка потока в заметки: что ложится, под какими номерами и что при повторной выгрузке."""

from pathlib import Path

import pytest

from spec_council.export import WORDS as LANGUAGES
from spec_council.export import (
    Shelf,
    drafted,
    export_in,
    graph_problems,
    outcome_text,
    renumbered,
    stream_texts,
    translations,
    untranslated,
    words_for,
    written,
)
from spec_council.issue_files import loaded
from spec_council.issue_files import parsed as issue_parsed
from spec_council.issue_files import rendered as issue_rendered
from spec_council.models import (
    Choice,
    Decision,
    ExportedNote,
    LabeledFragment,
    NotesExport,
    OpenQuestion,
    Outcome,
    OutcomeDiscovery,
    ProjectDecision,
    Proposal,
    ProposalDiscovery,
    QuestionOptions,
    Stream,
    StreamIdea,
)
from spec_council.notes import Catalog, Note, NotesError, declared_issues, path_of, rendered
from spec_council.slicing import BadAnswer

WORDS = words_for("Russian")
FRAGMENTS = {
    3: LabeledFragment(id=3, text="Деплой запускает CI после merge.", label="proposal",
                       reason="", council_label="proposal"),
    5: LabeledFragment(id=5, text="Деплоить по merge или по тегу?", label="question",
                       reason="", council_label="question"),
}
SCOPE = [
    OpenQuestion(id="Q1", text=FRAGMENTS[5].text, source="user", source_question_id=5,
                 proposal_ids=[3], note="Что запускает деплой?"),
    OpenQuestion(id="Q2", text="Где хранить секреты деплоя?", source="discovered"),
    OpenQuestion(id="Q3", text="Оставлять ли ручной откат?", source="discovered",
                 revisits="ADR-0001"),
]
FOUND = ProposalDiscovery(state="done", run="p1", steps=[], options=[
    QuestionOptions(question_id="Q1", verdict="alternatives", proposals=[
        Proposal(id="P1", text="Деплой запускают по тегу релиза.", reason="")]),
    QuestionOptions(question_id="Q2", verdict="recommended", proposals=[
        Proposal(id="P2", text="Секреты лежат в хранилище CI.", reason="")]),
    QuestionOptions(question_id="Q3", verdict="recommended", proposals=[
        Proposal(id="P3", text="Ручной откат остаётся.", reason="")]),
])
DECIDED = [Decision(question_id="Q1", proposal="F3",
                    rationale="Рутинные шаги не должны требовать ручной координации.",
                    rationale_by="human"),
           Decision(question_id="Q2", proposal=None),
           Decision(question_id="Q3", proposal="P3", rationale="Откат нужен при сбое.",
                    rationale_by="human")]
OUTCOMES = OutcomeDiscovery(state="done", run="o1", steps=[], outcomes=[
    Outcome(id="O1", title="Деплой по merge", behavior="После merge CI сам выкладывает.",
            adr_ids=["ADR-1", "ADR-3"], acceptance_criteria=["Merge в main выкладывает сборку."]),
    Outcome(id="O2", title="Хранение секретов", behavior="Секреты где-то лежат.",
            blocked_by=["Q2"]),
])
STREAM = Stream(group="A", idea=StreamIdea(text="Деплой требует меньше ручной работы.",
                                           by="human"),
                scope=SCOPE, proposals=FOUND, decisions=DECIDED, outcomes=OUTCOMES)
# В каталоге уже есть прошлый совет: его решение пересматривает Q3, и задача ISS-0007.
PAST = [Note("IDEA-0001", "idea", "Откаты делаются быстро."),
        Note("OQ-0001", "open_question", "Как откатывать?", ("IDEA-0001",)),
        Note("PRO-0001", "proposal", "Откат руками.", ("OQ-0001",)),
        Note("ADR-0001", "adr", "Откат руками, потому что так проще.", ("PRO-0001",)),
        Note("OUT-0001", "outcome", "Откат\n\nЗадачи:\n- ISS-0007: Кнопка отката",
             ("ADR-0001",))]


@pytest.fixture
def root(tmp_path):
    for note in PAST:
        path = path_of(tmp_path, note)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered(note), encoding="utf-8")
    return tmp_path


def shelf(root):
    return Shelf(Catalog.load(root), root)


def draft(root, stream=STREAM, previous=None, language="Russian"):
    """Черновик без номеров по именам совета: их проверяет refs_of."""
    return drafted(stream, FRAGMENTS, shelf(root), previous, WORDS, language)[:3]


def refs_of(root, stream=STREAM, previous=None):
    return drafted(stream, FRAGMENTS, shelf(root), previous, WORDS, "Russian")[3]


def export(root, stream=STREAM, previous=None, edits=None, delete=()):
    notes, vanished, skipped = draft(root, stream, previous)
    graph_problems(Catalog.load(root), notes, vanished, edits or {}, delete)
    done = written(notes, vanished, edits or {}, delete, shelf(root), previous)
    return NotesExport(run="r", outcomes=stream.outcomes.run, language="Russian",
                       root=str(root), notes=done), notes, vanished, skipped


def by_id(notes):
    return {note.id: note for note in notes}


def test_a_stream_becomes_linked_notes_with_numbers_after_the_catalog(root):
    notes, vanished, skipped = draft(root)
    assert vanished == []
    assert [(n.id, n.type, n.action) for n in notes] == [
        ("IDEA-0002", "idea", "create"),
        ("OQ-0002", "open_question", "create"), ("OQ-0003", "open_question", "create"),
        ("OQ-0004", "open_question", "create"),
        ("PRO-0002", "proposal", "create"), ("PRO-0003", "proposal", "create"),
        ("PRO-0004", "proposal", "create"), ("PRO-0005", "proposal", "create"),
        ("ADR-0002", "adr", "create"), ("ADR-0003", "adr", "create"),
        ("OUT-0002", "outcome", "create")]
    note = by_id(notes)
    # Имена совета — номерами заметок: так план задач называет итоги и решения, а тексты задач —
    # и всё остальное.
    assert refs_of(root) == {
        "I1": "IDEA-0002", "Q1": "OQ-0002", "F5": "OQ-0002", "Q2": "OQ-0003", "Q3": "OQ-0004",
        "F3": "PRO-0002",
        "P1": "PRO-0003", "P2": "PRO-0004", "P3": "PRO-0005", "ADR-1": "ADR-0002",
        "ADR-3": "ADR-0003", "O1": "OUT-0002"}
    assert note["OQ-0002"].text == "Что запускает деплой?"            # формулировка заметки
    assert note["OQ-0002"].links == ["IDEA-0002"]
    assert note["OQ-0004"].links == ["ADR-0001"]                       # пересматривает прошлое
    assert note["PRO-0002"].links == ["OQ-0002"]
    assert note["ADR-0002"].text == ("Деплой запускает CI после merge, потому что рутинные "
                                     "шаги не должны требовать ручной координации.")
    assert note["ADR-0002"].links == ["PRO-0002"]
    # Решение по Q3 — в цепочке прошлой идеи: итог связан только с решениями своей.
    assert note["OUT-0002"].links == ["ADR-0002"]
    assert note["OUT-0002"].text == (
        "Деплой по merge\n\nПосле merge CI сам выкладывает.\n\nКритерии готовности:\n"
        "- Merge в main выкладывает сборку.")          # задач в итоге нет: их режут потом
    assert any("O2" in reason and "не выгружается" in reason for reason in skipped)
    assert any("O1" in reason and "пересматривают" in reason for reason in skipped)


def test_written_notes_make_a_valid_graph_with_the_past_one(root):
    record, _, _, _ = export(root)
    catalog = Catalog.load(root)
    assert catalog.problems() == []
    assert catalog.status("ADR-0001") == ("superseded", "ADR-0003")
    assert {note.id for note in record.notes} == {
        "IDEA-0002", "OQ-0002", "OQ-0003", "OQ-0004", "PRO-0002", "PRO-0003", "PRO-0004",
        "PRO-0005", "ADR-0002", "ADR-0003", "OUT-0002"}
    assert (root / "adrs" / "ADR-0002.md").read_text(encoding="utf-8").startswith(
        "---\nid: ADR-0002\ntype: adr\nlinks:\n- PRO-0002\n---\n")


def test_exporting_again_keeps_numbers_and_human_edits(root):
    first, _, _, _ = export(root, edits={"idea": "Деплой без ручной работы."})
    notes, _, _ = draft(root, previous=first)
    assert {note.action for note in notes} == {"same"}
    assert by_id(notes)["IDEA-0002"].text == "Деплой без ручной работы."   # правка осталась


def test_a_file_edited_by_hand_is_left_alone(root):
    first, _, _, _ = export(root)
    path = root / "ideas" / "IDEA-0002.md"
    path.write_text(path.read_text(encoding="utf-8") + "Дописали руками.\n", encoding="utf-8")
    notes, _, _ = draft(root, previous=first)
    edited = by_id(notes)["IDEA-0002"]
    assert edited.action == "edited" and "Дописали руками." in edited.current
    record, _, _, _ = export(root, previous=first)
    assert "Дописали руками." in path.read_text(encoding="utf-8")
    assert by_id(record.notes)["IDEA-0002"].digest == first.notes[0].digest


def test_another_choice_is_another_decision_and_the_old_one_is_kept_unless_deleted(root):
    first, _, _, _ = export(root)
    other = STREAM.model_copy(update={"decisions": [
        DECIDED[0].model_copy(update={"proposal": "P1"}), *DECIDED[1:]]})
    notes, vanished, _ = draft(root, other, previous=first)
    assert by_id(notes)["ADR-0004"].links == ["PRO-0003"]            # новый номер
    assert [(v.id, v.linked_from) for v in vanished] == [("ADR-0002", [])]
    record, _, _, _ = export(root, other, previous=first)
    assert (root / "adrs" / "ADR-0002.md").exists()                     # само не удаляется
    kept = [note for note in record.notes if note.kept]
    assert [(n.id, n.key) for n in kept] == [("ADR-0002", first.notes[8].key)]   # всё ещё наше
    _, vanished, _ = draft(root, other, previous=record)
    assert [v.id for v in vanished] == ["ADR-0002"]                       # и снова к удалению
    _, _, _, _ = export(root, other, previous=first, delete=["ADR-0002"])
    assert not (root / "adrs" / "ADR-0002.md").exists()


def test_an_own_option_is_exported_as_a_proposal_with_its_decision(root):
    own = "Секреты лежат в переменных окружения."
    stream = STREAM.model_copy(update={
        "choices": [Choice(question_id="Q1", proposal="F3"),
                    Choice(question_id="Q2", proposal="P4", text=own),
                    Choice(question_id="Q3", proposal="P3")],
        "decisions": [DECIDED[0], Decision(question_id="Q2", proposal="P4", rationale="Так проще.",
                                           rationale_by="human"), DECIDED[2]]})
    notes, _, _ = draft(root, stream)
    asked = next(n for n in notes if n.text == SCOPE[1].text)
    proposal = next(n for n in notes if n.type == "proposal" and n.text == own)
    assert proposal.links == [asked.id]
    adr = next(n for n in notes if n.type == "adr" and n.links == [proposal.id])
    assert adr.text == "Секреты лежат в переменных окружения, потому что так проще."


def proposals_of(notes, question):
    asked = next(n for n in notes if n.type == "open_question" and n.text == question)
    return [n.text for n in notes if n.type == "proposal" and n.links == [asked.id]]


def test_a_refinement_takes_the_place_of_the_option_it_refines(root):
    own = "Деплой запускают по тегу релиза, а hotfix — по merge."
    stream = STREAM.model_copy(update={
        "choices": [Choice(question_id="Q1", proposal="P4", text=own, based_on="P1"),
                    Choice(question_id="Q2", proposal=None),
                    Choice(question_id="Q3", proposal="P3")],
        "decisions": [Decision(question_id="Q1", proposal="P4", rationale="Так быстрее.",
                               rationale_by="human"), *DECIDED[1:]]})
    notes, _, _ = draft(root, stream)
    # P1 вышел неполным, его никто не отклонял: заметки «отклонённого» P1 нет.
    assert proposals_of(notes, "Что запускает деплой?") == [FRAGMENTS[3].text, own]

    # Решили всё же исходным — остаются оба: правку тогда и правда отклонили.
    kept = stream.model_copy(update={"decisions": [
        Decision(question_id="Q1", proposal="P1", rationale="Так проще.", rationale_by="human"),
        *DECIDED[1:]]})
    notes, _, _ = draft(root, kept)
    assert proposals_of(notes, "Что запускает деплой?") == [
        FRAGMENTS[3].text, FOUND.options[0].proposals[0].text, own]


def test_a_refinement_of_an_option_from_the_group_text_takes_its_place_too(root):
    own = "Деплой запускает CI после merge в main."
    stream = STREAM.model_copy(update={
        "choices": [Choice(question_id="Q1", proposal="P4", text=own, based_on="F3"),
                    Choice(question_id="Q2", proposal=None),
                    Choice(question_id="Q3", proposal="P3")],
        "decisions": None})
    notes, _, _ = draft(root, stream)
    assert proposals_of(notes, "Что запускает деплой?") == [
        own, FOUND.options[0].proposals[0].text]


LIMIT = LabeledFragment(id=4, text="Секреты не уходят в репозиторий.", label="constraint",
                        reason="", council_label="constraint")


def test_stream_numbers_in_texts_become_note_numbers_or_go(root):
    stream = STREAM.model_copy(update={
        "decisions": [
            DECIDED[0].model_copy(update={
                "rationale": "рутина не требует ручной работы (F4), а тег (P1) нужен лишь по Q2"}),
            DECIDED[1],
            DECIDED[2].model_copy(update={
                "rationale": "так велит F4, как и ADR-1 (Q2, F4), а P9 и ADR-0001 — чужие"})],
        "outcomes": OUTCOMES.model_copy(update={"outcomes": [
            OUTCOMES.outcomes[0].model_copy(update={
                "behavior": "CI выкладывает сам (I1), секреты — в O2 (R7)."}),
            *OUTCOMES.outcomes[1:]]})})
    notes = by_id(drafted(stream, FRAGMENTS | {4: LIMIT}, shelf(root), None, WORDS, "Russian")[0])
    # Номер с заметкой — её номером; ограничение без заметки в скобках выпадает: фраза его
    # пересказывает, — а посреди фразы встаёт его текст. Номера заметок и незнакомые — как есть.
    assert notes["ADR-0002"].text == (
        "Деплой запускает CI после merge, потому что рутина не требует ручной работы, а тег "
        "(PRO-0003) нужен лишь по OQ-0003")
    assert notes["ADR-0003"].text == (
        "Ручной откат остаётся, потому что так велит «Секреты не уходят в репозиторий», как и "
        "ADR-0002 (OQ-0003), а P9 и ADR-0001 — чужие")
    # Итог, который не выгружается, — своим названием; незнакомая находка R7 — как есть.
    assert notes["OUT-0002"].text.splitlines()[2] == (
        "CI выкладывает сам (IDEA-0002), секреты — в «Хранение секретов» (R7).")
    # Код в обратных кавычках — как есть: `Q1` там — не вопрос.
    assert renumbered("`Q1` и Q1 (`F4`)", {"Q1": "OQ-0002"}, {"F4": LIMIT.text}) == (
        "`Q1` и OQ-0002 (`F4`)")
    # И в блоке ```…```: там пример кода или настроек.
    fenced = "Пример:\n```yaml\nQ1: 1\nlimit: (F4)\n```\nпо Q1"
    assert renumbered(fenced, {"Q1": "OQ-0002"}, {"F4": LIMIT.text}) == (
        "Пример:\n```yaml\nQ1: 1\nlimit: (F4)\n```\nпо OQ-0002")
    assert renumbered("~~~\nQ1: 1\n~~~\nпо Q1", {"Q1": "OQ-0002"}, {}) == (
        "~~~\nQ1: 1\n~~~\nпо OQ-0002")
    # Разделители любой длины: ``Q1`` — код, а блок ```` не закрыть тремя кавычками внутри.
    assert renumbered("``Q1`` и Q1", {"Q1": "OQ-0002"}, {}) == "``Q1`` и OQ-0002"
    long = "````md\n```\nQ1\n```\n````\nпо Q1"
    assert renumbered(long, {"Q1": "OQ-0002"}, {}) == long.replace("по Q1", "по OQ-0002")
    # Блок с отступом в четыре пробела — код; продолжение пункта списка — нет.
    indented = "Пример:\n\n    Q1 = F4\n    F4 = Q1\n\n- по Q1\n    и Q1"
    assert renumbered(indented, {"Q1": "OQ-0002"}, {"F4": LIMIT.text}) == (
        "Пример:\n\n    Q1 = F4\n    F4 = Q1\n\n- по OQ-0002\n    и OQ-0002")
    # Пустая строка с пробелами перед блоком — тоже пустая; строка кода — и через перенос.
    assert renumbered("текст\n \n    Q1\n\nпо Q1", {"Q1": "OQ-0002"}, {}) == (
        "текст\n \n    Q1\n\nпо OQ-0002")
    assert renumbered("`first\nQ1` и Q1", {"Q1": "OQ-0002"}, {}) == "`first\nQ1` и OQ-0002"
    # Блоки кода и HTML на любой глубине: в цитате, в пункте списка.
    nested = "> ~~~yaml\n> Q1: 1\n> ~~~\n\n- пункт\n\n      Q1 = 2\n\n<pre>\nQ1\n</pre>\n\nпо Q1"
    assert renumbered(nested, {"Q1": "OQ-0002"}, {}) == nested.replace("по Q1", "по OQ-0002")
    # Тег HTML с атрибутами — не текст, а то, что между тегами, — текст.
    assert renumbered('<a href="/questions/Q1">Q1</a> <!-- Q1 --> и Q1', {"Q1": "OQ-0002"},
                      {}) == '<a href="/questions/Q1">OQ-0002</a> <!-- Q1 --> и OQ-0002'
    # Определение ссылки-сноски — по разбору Markdown — как есть целиком, а похожая строка
    # посреди абзаца — не определение: там Q1 — номер.
    assert renumbered("[вопрос Q1][q]\n\n[q]: /questions/Q1 \"Q1\"", {"Q1": "OQ-0002"}, {}) == (
        "[вопрос OQ-0002][q]\n\n[q]: /questions/Q1 \"Q1\"")
    assert renumbered("Абзац\n[Q1]: /questions/Q1\n\nсм. [Q1]", {"Q1": "OQ-0002"}, {}) == (
        "Абзац\n[OQ-0002]: /questions/OQ-0002\n\nсм. [OQ-0002]")
    # \[x](…) — текст, а не ссылка: «адрес» в нём — текст; голый адрес — со скобками любой
    # вложенности; повторное определение сноски — тоже определение.
    assert renumbered("\\[пример](/questions/Q1)", {"Q1": "OQ-0002"}, {}) == (
        "\\[пример](/questions/OQ-0002)")
    bare = "https://host/a((((((Q1))))))"
    assert renumbered(f"{bare} и Q1.", {"Q1": "OQ-0002"}, {}) == f"{bare} и OQ-0002."
    twice = "[Q1]: /a/Q1\n\n[q1]: /backup/Q1"
    assert renumbered(f"{twice}\n\nпо Q1", {"Q1": "OQ-0002"}, {}) == f"{twice}\n\nпо OQ-0002"
    # «\» перед пробелом — не экранирование: [x](foo\ Q1) — не ссылка; [Q1](не адрес) — не
    # встроенная ссылка, и [Q1] — сноска.
    assert renumbered("[x](foo\\ Q1)", {"Q1": "OQ-0002"}, {}) == "[x](foo\\ OQ-0002)"
    shortcut = "[Q1](не адрес)\n\n[Q1]: /q/1"
    assert renumbered(f"{shortcut}\n\nи Q1", {"Q1": "OQ-0002"}, {}) == f"{shortcut}\n\nи OQ-0002"
    # «[» в атрибуте тега — не начало ссылки.
    tagged = '<span title="[">x</span> ](/questions/Q1)'
    assert renumbered(tagged, {"Q1": "OQ-0002"}, {}) == tagged.replace("/Q1", "/OQ-0002")
    # «[» из прошлого абзаца — не начало ссылки, и пустая строка внутри «](…)» — тоже не ссылка.
    assert renumbered("[x\n\n](/questions/Q1)", {"Q1": "OQ-0002"}, {}) == (
        "[x\n\n](/questions/OQ-0002)")
    assert renumbered("[x](\n\n/questions/Q1)", {"Q1": "OQ-0002"}, {}) == (
        "[x](\n\n/questions/OQ-0002)")
    # «[» и «<code>» в строке кода — не начало ссылки и не элемент; незакрытый <code> — не
    # элемент.
    assert renumbered("`[x` ](/questions/Q1)", {"Q1": "OQ-0002"}, {}) == (
        "`[x` ](/questions/OQ-0002)")
    assert renumbered("Use `<code>` then Q1", {"Q1": "OQ-0002"}, {}) == (
        "Use `<code>` then OQ-0002")
    # Узел IPv6 в адресе — часть адреса; вложенные элементы кода — одно целое.
    ipv6 = "http://[::1]/Q1"
    assert renumbered(f"{ipv6} и Q1", {"Q1": "OQ-0002"}, {}) == f"{ipv6} и OQ-0002"
    nested_code = "<code>outer <code>Q1</code> Q1</code>"
    assert renumbered(f"{nested_code} и Q1", {"Q1": "OQ-0002"}, {}) == f"{nested_code} и OQ-0002"
    # Адрес в строке кода кончается с ней; «[» абзаца над заголовком — не начало ссылки в нём;
    # в <script> тег — текст до </script>.
    assert renumbered("`https://host`/Q1", {"Q1": "OQ-0002"}, {}) == "`https://host`/OQ-0002"
    assert renumbered("[x\n# ](/questions/Q1)", {"Q1": "OQ-0002"}, {}) == (
        "[x\n# ](/questions/OQ-0002)")
    script = '<script>const tag = "<script>"; Q1</script>'
    assert renumbered(f"До {script} и Q1", {"Q1": "OQ-0002"}, {}) == f"До {script} и OQ-0002"
    # [x\](…) — «]» экранирована, ссылки нет: Q1 — номер.
    assert renumbered("[x\\](/questions/Q1)", {"Q1": "OQ-0002"}, {}) == (
        "[x\\](/questions/OQ-0002)")
    # Скобки в адресе ссылки — любой вложенности.
    deep_link = "[x](https://host/a((((((Q1)))))))"
    assert renumbered(f"{deep_link} и Q1", {"Q1": "OQ-0002"}, {}) == f"{deep_link} и OQ-0002"
    # Вторая метка полной ссылки — сноска, хоть за ней и скобка.
    full = "[текст][Q1](пояснение)\n\n[Q1]: /questions/1"
    assert renumbered(full, {"Q1": "OQ-0002"}, {}) == full
    # \\[Q1] — экранирован сам «\», а [Q1] — снова ссылка на сноску; адрес в <…> — и с «\>».
    assert renumbered("см. \\\\[Q1] и Q1\n\n[Q1]: /q/1", {"Q1": "OQ-0002"}, {}) == (
        "см. \\\\[Q1] и OQ-0002\n\n[Q1]: /q/1")
    angled = "[x](</docs/a\\>/Q1>)"
    assert renumbered(f"{angled} и Q1", {"Q1": "OQ-0002"}, {}) == f"{angled} и OQ-0002"
    # Экранированная скобка в адресе — часть адреса; определение сноски — и в продолжении
    # вложенного пункта списка.
    escaped = "[x](https://host/a\\(/Q1)"
    assert renumbered(f"{escaped} и Q1", {"Q1": "OQ-0002"}, {}) == f"{escaped} и OQ-0002"
    listed = "- outer\n  - inner\n\n    [Q1]: /questions/Q1\n\n[t][Q1] и Q1"
    assert renumbered(listed, {"Q1": "OQ-0002"}, {}) == listed.replace("и Q1", "и OQ-0002")
    # Определение сноски — и в цитате, и в пункте списка.
    nested = "> [вопрос][Q1]\n>\n> [Q1]: /questions/Q1\n\n- [Q2]: /q/Q2\n\nпо Q1"
    assert renumbered(nested, {"Q1": "OQ-0002", "Q2": "OQ-0003"}, {}) == nested.replace(
        "по Q1", "по OQ-0002")
    # Адрес сноски — и на следующей строке; инструкция, CDATA и объявление HTML — не текст.
    wrapped = "[q]:\n  /questions/Q1\n\nтекст <?check Q1?> <![CDATA[Q1]]> <!DOCTYPE Q1>"
    assert renumbered(f"{wrapped} и Q1", {"Q1": "OQ-0002"}, {}) == f"{wrapped} и OQ-0002"
    # Метка сноски — как в CommonMark, без регистра и лишних пробелов; заголовок ссылки — и с
    # экранированной кавычкой.
    spaced = "[вопрос][Q1 ref] и [q1\nREF]\n\n[Q1  ref]: /questions/1"
    assert renumbered(f"{spaced}\n\nпо Q1", {"Q1": "OQ-0002"}, {}) == f"{spaced}\n\nпо OQ-0002"
    titled = '[x](/questions/Q1 "say \\"hi\\"")'
    assert renumbered(f"{titled} и Q1", {"Q1": "OQ-0002"}, {}) == f"{titled} и OQ-0002"
    # «R2-D2» — одно слово, а не две находки; \[Q1] — текст, а не ссылка на сноску; строка в
    # многострочном коде — не определение сноски.
    assert renumbered("Робот R2-D2 и R2", {}, {"R2": "Находка", "D2": "Экран"}) == (
        "Робот R2-D2 и «Находка»")
    assert renumbered("см. \\[Q1] и [Q1]\n\n[Q1]: /questions/1", {"Q1": "OQ-0002"}, {}) == (
        "см. \\[OQ-0002] и [Q1]\n\n[Q1]: /questions/1")
    assert renumbered("`пример\n[Q1]: /x` и см. [Q1]", {"Q1": "OQ-0002"}, {}) == (
        "`пример\n[Q1]: /x` и см. [OQ-0002]")
    # Метка со скобкой, экранированной «\»: и определение, и ссылка на него — как есть.
    escaped_label = "[текст][q1\\]]\n\n[Q1\\]]: /questions/1"
    assert renumbered(f"{escaped_label}\n\nпо Q1", {"Q1": "OQ-0002"}, {}) == (
        f"{escaped_label}\n\nпо OQ-0002")
    # [Q1](…) — встроенная ссылка, а не сноска Q1: её текст — номер заметки.
    inline = "[Q1](/docs) и [Q1]\n\n[Q1]: /questions/1"
    assert renumbered(inline, {"Q1": "OQ-0002"}, {}) == inline.replace("[Q1](", "[OQ-0002](")
    # Определение в блоке кода — пример, а не определение: [Q1] в тексте — номер.
    assert renumbered("```\n[Q1]: /x\n```\n\nсм. [Q1]", {"Q1": "OQ-0002"}, {}) == (
        "```\n[Q1]: /x\n```\n\nсм. [OQ-0002]")
    # Метка сноски — не текст ни в определении, ни там, где ссылкой пользуются.
    assert renumbered("[вопрос][Q1], [q1] и Q1\n\n[Q1]: /questions/1", {"Q1": "OQ-0002"},
                      {}) == "[вопрос][Q1], [q1] и OQ-0002\n\n[Q1]: /questions/1"
    # Заголовок ссылки — в любых кавычках CommonMark или в скобках; адрес — и в <…>.
    for link in ("[x](/questions/Q1 'Q1')", "[x](/questions/Q1 (Q1))", "[x](</questions/Q1>)",
                 '[x]( /questions/Q1 "Q1" )'):
        assert renumbered(f"{link} и Q1", {"Q1": "OQ-0002"}, {}) == f"{link} и OQ-0002"
    # Код в HTML — целиком, а обычный текст между тегами — текст.
    raw = "<code>Q1</code> <PRE class=\"x\">Q1\nF4</pre> <b>Q1</b>"
    assert renumbered(raw, {"Q1": "OQ-0002"}, {"F4": LIMIT.text}) == (
        "<code>Q1</code> <PRE class=\"x\">Q1\nF4</pre> <b>OQ-0002</b>")
    # Атрибут тега в кавычках — целиком, и с «>» внутри.
    tag = "<a title=\"x > Q1\" data-q='Q1' hidden>"
    assert renumbered(f"{tag}Q1</a>", {"Q1": "OQ-0002"}, {}) == f"{tag}OQ-0002</a>"
    # Скобки в адресе — и вложенные; почта — и в <…>, и сама по себе.
    deep = "[x](https://host/a_(b_(c))/Q1) <foo.Q1@example.com> foo.Q1@example.com"
    assert renumbered(f"{deep} и Q1", {"Q1": "OQ-0002"}, {}) == f"{deep} и OQ-0002"
    # Адрес — целиком, и со скобками внутри.
    assert renumbered("[x](https://host/a_(b)/Q1) https://host/a_(b)/Q1 Q1",
                      {"Q1": "OQ-0002"}, {}) == (
        "[x](https://host/a_(b)/Q1) https://host/a_(b)/Q1 OQ-0002")
    # Адрес ссылки — не текст: подпись получает номер заметки, адрес остаётся.
    assert renumbered("[вопрос Q1](https://tracker.local/Q1), см. https://x.local/Q1",
                      {"Q1": "OQ-0002"}, {}) == (
        "[вопрос OQ-0002](https://tracker.local/Q1), см. https://x.local/Q1")


def test_a_term_of_the_approved_idea_stays_in_its_note(root):
    # Идею написал человек раньше, чем у потока появились номера: «P1 incidents» в ней — слово.
    stream = STREAM.model_copy(update={"idea": StreamIdea(text="Разбирать P1 incidents быстрее.",
                                                         by="human")})
    assert by_id(draft(root, stream)[0])["IDEA-0002"].text == "Разбирать P1 incidents быстрее."


def test_an_adr_number_a_past_decision_shares_stays_as_it_is(root):
    # Решение проекта ADR-0001, отобранное для потока, каталог зовёт и «ADR-1»: «ADR-1» в тексте —
    # не обязательно первое решение потока, и номером его заметки оно не становится. И слова из
    # текста этого решения («P1 incidents») — термины, хоть в потоке и есть свой P1.
    stream = STREAM.model_copy(update={
        "project_decisions": [ProjectDecision(adr_id="ADR-0001",
                                              decision="P1 incidents разбирают первыми")],
        "decisions": [*DECIDED[:2], DECIDED[2].model_copy(update={
            "rationale": "так велит ADR-1: P1 incidents — первыми, а Q2 открыт"})]})
    notes = by_id(draft(root, stream)[0])
    assert notes["ADR-0003"].text == (
        "Ручной откат остаётся, потому что так велит ADR-1: P1 incidents — первыми, а OQ-0003 "
        "открыт")


def test_a_question_from_the_group_text_is_named_by_its_fragment_too_and_terms_stay(root):
    # «F1 score» — слово из текста группы: номером фрагмента F1 оно не становится.
    term = LabeledFragment(id=1, text="Деплой ускоряет F1 score команды.", label="idea",
                           reason="", council_label="idea")
    stream = STREAM.model_copy(update={"decisions": [
        DECIDED[0].model_copy(update={"rationale": "это ответ на F5 (F5), и F1 score растёт"}),
        *DECIDED[1:]]})
    notes = by_id(drafted(stream, FRAGMENTS | {1: term}, shelf(root), None, WORDS, "Russian")[0])
    assert notes["ADR-0002"].text == (
        "Деплой запускает CI после merge, потому что это ответ на OQ-0002 (OQ-0002), и F1 score "
        "растёт")


def test_a_source_phrase_stays_but_the_same_number_elsewhere_is_a_reference(root):
    # «P1 incidents» — слово текста группы, а «выбрать P1» в обосновании — вариант P1.
    term = LabeledFragment(id=1, text="Разбирать P1 incidents первыми.", label="idea",
                           reason="", council_label="idea")
    stream = STREAM.model_copy(update={"decisions": [
        DECIDED[0].model_copy(update={"rationale": "лучше выбрать P1 для Q2, а P1 incidents — "
                                                   "первыми"}),
        *DECIDED[1:]]})
    notes = by_id(drafted(stream, FRAGMENTS | {1: term}, shelf(root), None, WORDS, "Russian")[0])
    assert notes["ADR-0002"].text == (
        "Деплой запускает CI после merge, потому что лучше выбрать PRO-0003 для OQ-0003, а "
        "P1 incidents — первыми")


def test_a_refined_option_is_named_by_its_refinement(root):
    own = "Деплой запускают по тегу релиза, а hotfix — по merge."
    stream = STREAM.model_copy(update={
        "choices": [Choice(question_id="Q1", proposal="P4", text=own, based_on="P1"),
                    Choice(question_id="Q2", proposal=None),
                    Choice(question_id="Q3", proposal="P3")],
        "decisions": [Decision(question_id="Q1", proposal="P4", rationale="Так быстрее.",
                               rationale_by="human"), DECIDED[1],
                      DECIDED[2].model_copy(update={"rationale": "откат нужен и при P1"})]})
    notes, _, _ = draft(root, stream)
    refined = next(n for n in notes if n.type == "proposal" and n.text == own)
    adr = next(n for n in notes if n.type == "adr" and n.text.startswith("Ручной откат"))
    assert adr.text == f"Ручной откат остаётся, потому что откат нужен и при {refined.id}"
    # Заметки нет (удалили) — за номером исходного уже текст правки, а не прежний; за номером
    # вопроса и его фрагмента — его формулировка в заметке.
    texts = stream_texts(stream, FRAGMENTS)
    assert texts["P1"] == own
    assert texts["Q1"] == texts["F5"] == SCOPE[0].note


REFINED = "Ручной откат остаётся, но только по кнопке."


def test_a_refinement_marked_after_an_export_continues_the_note_of_its_option(root):
    first, _, _, _ = export(root)                                         # решили P3 как есть
    refined = STREAM.model_copy(update={
        "choices": [Choice(question_id="Q1", proposal="F3"),
                    Choice(question_id="Q2", proposal=None),
                    Choice(question_id="Q3", proposal="P4", text=REFINED, based_on="P3")],
        "decisions": [*DECIDED[:2], DECIDED[2].model_copy(update={"proposal": "P4"})]})
    notes, vanished, _ = draft(root, refined, previous=first)
    note = by_id(notes)
    # Тот же вариант, только дописанный, — та же заметка, и решение по нему — то же.
    assert (note["PRO-0005"].text, note["PRO-0005"].action) == (REFINED, "update")
    assert note["ADR-0003"].text.startswith(REFINED.rstrip("."))
    assert note["ADR-0003"].links == ["PRO-0005"]
    assert vanished == []


def refined_q3(text, based_on="P3"):
    """Поток, где по Q3 решили своим вариантом text — правкой based_on."""
    return STREAM.model_copy(update={
        "choices": [Choice(question_id="Q1", proposal="F3"),
                    Choice(question_id="Q2", proposal=None),
                    Choice(question_id="Q3", proposal="P4", text=text, based_on=based_on)],
        "decisions": [*DECIDED[:2], DECIDED[2].model_copy(update={"proposal": "P4"})]})


def test_a_refinement_exported_as_its_own_option_before_the_mark_joins_its_option(root):
    first, notes, _, _ = export(root, refined_q3(REFINED, based_on=None))
    own = next(n for n in notes if n.type == "proposal" and n.text == REFINED)
    base = next(n for n in notes if n.text == FOUND.options[2].proposals[0].text)
    adr = next(n for n in notes if n.type == "adr" and n.links == [own.id])
    notes, vanished, _ = draft(root, refined_q3(REFINED), previous=first)
    # Отметили, что это правка P3: заметка P3 — уже с правкой, решение — то же, но о ней, а
    # заметка, где правка лежала своим вариантом, уходит.
    assert [(n.id, n.action) for n in notes if n.text == REFINED] == [(base.id, "update")]
    assert by_id(notes)[adr.id].links == [base.id]
    assert [v.id for v in vanished] == [own.id]


def test_a_refinement_edited_again_stays_the_same_note(root):
    first, notes, _, _ = export(root, refined_q3(REFINED))
    before = {n.type: n.id for n in notes if n.text.startswith(REFINED.rstrip("."))}
    again = "Ручной откат остаётся, но только по кнопке и с подтверждением."
    notes, vanished, _ = draft(root, refined_q3(again), previous=first)
    after = {n.type: n.id for n in notes if n.text.startswith(again.rstrip("."))}
    assert after == before and set(after) == {"proposal", "adr"}
    assert vanished == []


def test_a_vanished_note_linked_from_outside_is_not_deleted(root):
    first, _, _, _ = export(root)
    outside = Note("OQ-0009", "open_question", "Пересмотреть?", ("ADR-0002",))
    (root / "open_questions" / "OQ-0009.md").write_text(rendered(outside), encoding="utf-8")
    other = STREAM.model_copy(update={"decisions": [
        DECIDED[0].model_copy(update={"proposal": "P1"}), *DECIDED[1:]]})
    _, vanished, _ = draft(root, other, previous=first)
    assert [(v.id, v.linked_from) for v in vanished] == [("ADR-0002", ["OQ-0009"])]
    with pytest.raises(NotesError, match="ссылаются OQ-0009"):
        export(root, other, previous=first, delete=["ADR-0002"])


def test_a_vanished_parent_is_not_deleted_while_a_vanished_child_links_to_it(root):
    first, _, _, _ = export(root)
    # Выбрали другой вариант, а итог переназвали: прежние ADR и итог исчезли из потока оба.
    retitled = OUTCOMES.model_copy(update={"outcomes": [
        OUTCOMES.outcomes[0].model_copy(update={"title": "Деплой по тегу"}),
        *OUTCOMES.outcomes[1:]]})
    other = STREAM.model_copy(update={"outcomes": retitled, "decisions": [
        DECIDED[0].model_copy(update={"proposal": "P1"}), *DECIDED[1:]]})
    _, vanished, _ = draft(root, other, previous=first)
    assert [(v.id, v.linked_from) for v in vanished] == [("ADR-0002", []), ("OUT-0002", [])]
    with pytest.raises(NotesError, match="OUT-0002: ссылка на несуществующую заметку ADR-0002"):
        export(root, other, previous=first, delete=["ADR-0002"])
    assert (root / "adrs" / "ADR-0002.md").exists()                     # файлы не тронуты
    export(root, other, previous=first, delete=["ADR-0002", "OUT-0002"])
    assert Catalog.load(root).problems() == []


def twins(order=(0, 1)):
    twin = OUTCOMES.outcomes[0].model_copy(update={"id": "O3", "behavior": "И откат по merge."})
    outcomes = [OUTCOMES.outcomes[0], twin]
    return STREAM.model_copy(update={
        "outcomes": OUTCOMES.model_copy(update={"outcomes": [
            *(outcomes[i] for i in order), OUTCOMES.outcomes[1]]})})


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
            for path in root.rglob("*") if path.is_file()}


def refusing(monkeypatch, name):
    """Файл name не сдвинуть с места: нет прав или его заняли."""
    replace = Path.replace

    def refused(path, target):
        if path.name == name:
            raise PermissionError(13, "Permission denied")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", refused)


def chose_p1():
    return STREAM.model_copy(update={"decisions": [
        DECIDED[0].model_copy(update={"proposal": "P1"}), *DECIDED[1:]]})


def test_a_note_that_cannot_be_deleted_leaves_the_catalog_as_it_was(root, monkeypatch):
    first, _, _, _ = export(root)
    before = snapshot(root)
    refusing(monkeypatch, "ADR-0002.md")
    with pytest.raises(NotesError, match="ADR-0002.md не удалить"):
        export(root, chose_p1(), previous=first, delete=["ADR-0002"])
    assert snapshot(root) == before                     # ни новых, ни временных файлов


def test_a_note_that_cannot_be_replaced_rolls_the_whole_export_back(root, monkeypatch):
    first, _, _, _ = export(root)
    before = snapshot(root)
    refusing(monkeypatch, "OUT-0002.md.part")          # новый ADR уже встал, итог — нет
    with pytest.raises(NotesError, match="OUT-0002.md не записать"):
        export(root, chose_p1(), previous=first, delete=["ADR-0002"])
    assert snapshot(root) == before                     # и удалённое вернулось


def test_outcomes_with_the_same_title_stay_separate(root):
    first, notes, _, _ = export(root, twins())
    assert len({note.key for note in notes}) == len(notes)
    assert [n.id for n in notes if n.type == "outcome"] == ["OUT-0002", "OUT-0003"]
    assert "И откат по merge." in (root / "outcomes" / "OUT-0003.md").read_text(encoding="utf-8")
    again, _, _ = draft(root, twins(), previous=first)
    assert {note.action for note in again} == {"same"}
    # Модель отдала их в другом порядке — номера держатся за суть, а не за место в списке.
    swapped, _, _ = draft(root, twins((1, 0)), previous=first)
    assert {n.id: n.text.split("\n")[2] for n in swapped if n.type == "outcome"} == {
        "OUT-0002": "После merge CI сам выкладывает.", "OUT-0003": "И откат по merge."}


def test_a_second_outcome_with_the_same_title_keeps_the_first_ones_numbers(root):
    first, _, _, _ = export(root)                       # итог «Деплой по merge» один
    notes, vanished, _ = draft(root, twins(), previous=first)
    assert vanished == []
    assert {n.text.split("\n")[2]: n.id for n in notes if n.type == "outcome"} == {
        "После merge CI сам выкладывает.": "OUT-0002", "И откат по merge.": "OUT-0003"}
    second, _, _, _ = export(root, twins(), previous=first)
    notes, vanished, _ = draft(root, previous=second)   # двойник ушёл
    assert [n.id for n in notes if n.type == "outcome"] == ["OUT-0002"]
    assert [v.id for v in vanished] == ["OUT-0003"]


def test_an_outcome_reworded_under_the_same_title_keeps_its_number(root):
    first, _, _, _ = export(root)
    reworded = OUTCOMES.model_copy(update={"outcomes": [OUTCOMES.outcomes[0].model_copy(
        update={"behavior": "CI выкладывает сборку после merge."}), *OUTCOMES.outcomes[1:]]})
    notes, vanished, _ = draft(root, STREAM.model_copy(update={"outcomes": reworded}),
                                  previous=first)
    assert vanished == []
    assert by_id(notes)["OUT-0002"].action == "update"


def test_another_notes_language_translates_the_notes_again(root):
    first, _, _, _ = export(root, edits={"idea": "Деплой без ручной работы."})
    notes, _, _ = draft(root, previous=first, language="English")
    idea = by_id(notes)["IDEA-0002"]
    assert idea.text == idea.generated                  # прежний текст — на прежнем языке
    assert "idea" in untranslated(notes)


def test_a_renamed_note_file_is_deleted_where_it_lies(root):
    first, _, _, _ = export(root)
    renamed = root / "adrs" / "old-decision.md"
    (root / "adrs" / "ADR-0002.md").rename(renamed)
    export(root, chose_p1(), previous=first, delete=["ADR-0002"])
    assert not renamed.exists()
    assert "ADR-0002" not in Catalog.load(root).notes


def test_a_file_edited_by_hand_keeps_the_text_it_was_exported_from(root):
    first, _, _, _ = export(root)
    path = root / "ideas" / "IDEA-0002.md"
    original = path.read_bytes()
    path.write_bytes(original + "Дописали руками.\n".encode())
    other = STREAM.model_copy(update={"idea": StreamIdea(text="Деплой идёт сам.", by="human")})
    second, _, _, _ = export(root, other, previous=first)          # файл правили — не трогаем
    path.write_bytes(original)                                       # правку откатили
    notes, _, _ = draft(root, other, previous=second)
    idea = by_id(notes)["IDEA-0002"]
    assert (idea.action, idea.text) == ("update", "Деплой идёт сам.")    # новое — предложено


def test_an_empty_text_is_not_written(root):
    with pytest.raises(NotesError, match="пустой текст"):
        export(root, edits={"idea": "   "})


def test_an_old_number_whose_file_holds_another_note_is_not_reused(root):
    first, _, _, _ = export(root)
    old = next(note for note in first.notes if note.type == "idea")
    path = root / "ideas" / f"{old.id}.md"
    path.unlink()                                          # нашу идею удалили руками,
    foreign = Note("IDEA-0099", "idea", "Чужая идея.")
    path.write_text(rendered(foreign), encoding="utf-8")   # а в её файл переименовали чужую
    notes, _, _ = draft(root, previous=first)
    idea = next(note for note in notes if note.type == "idea")
    assert (idea.id, idea.action) == ("IDEA-0100", "create")
    export(root, previous=first)
    assert path.read_text(encoding="utf-8") == rendered(foreign)          # не затёрта


def test_an_edit_must_keep_the_numbers(root):
    notes, _, _ = draft(root)
    idea = notes[0]
    with pytest.raises(NotesError, match=f"В правке заметки {idea.id} лишние номера ADR-0042"):
        written(notes, [], {idea.key: idea.text + " Как в ADR-0042."}, [], shelf(root), None)
    assert sorted(Catalog.load(root).notes) == sorted(note.id for note in PAST)   # не тронут


def test_an_empty_text_anywhere_leaves_the_catalog_as_it_was(root):
    notes, _, _ = draft(root)
    last = notes[-1]
    with pytest.raises(NotesError, match=f"У заметки {last.id} пустой текст"):
        written(notes, [], {last.key: " "}, [], shelf(root), None)
    assert sorted(note.id for note in Catalog.load(root).notes.values()) == sorted(
        note.id for note in PAST)                                      # ничего не записано


def test_a_revisited_decision_gone_from_the_catalog_stops_the_draft(root):
    (root / "adrs" / "ADR-0001.md").unlink()
    (root / "outcomes" / "OUT-0001.md").unlink()
    with pytest.raises(NotesError, match="Q3 пересматривает ADR-0001"):
        draft(root)


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_criteria_with_issue_numbers_are_not_the_issue_list(language):
    words = LANGUAGES[language]
    text = outcome_text("Поиск", "Ищется.", ["ISS-0042: регресс не вернулся"], words)
    assert declared_issues(text) == []
    # И на языке, подписи которого совет не знает: критерий — не строка задачи.
    foreign = text.replace(f"{words['criteria']}:", "Criterios de aceptación:")
    assert declared_issues(foreign) == [] and "- ISS-0042 — регресс не вернулся" in foreign


def test_a_translation_does_not_turn_a_criterion_into_an_issue_line():
    source = outcome_text("Поиск", "Ищется.", ["ISS-0042: регресс не вернулся"],
                          LANGUAGES["russian"])
    turned = {"notes": [{"key": "o", "text": "Búsqueda\n\nSe busca.\n\nCriterios de aceptación:\n"
                                             "- ISS-0042: la regresión no vuelve"}]}
    with pytest.raises(BadAnswer, match="строки задач"):
        translations(turned, {"o": source})


def test_a_translation_keeps_exactly_the_numbers_of_the_source():
    sources = {"o": "Итог\n\nЗадачи:\n- ISS-0001: Кнопка", "a": "Откат, потому что ADR-0001."}
    good = {"notes": [{"key": "o", "text": "Outcome\n\nIssues:\n- ISS-0001: Button"},
                      {"key": "a", "text": "Rollback, because of ADR-0001."}]}
    assert translations(good, sources)["o"].endswith("ISS-0001: Button")
    lost = {"notes": [good["notes"][0], {"key": "a", "text": "Rollback."}]}
    with pytest.raises(BadAnswer, match="потеряны номера ADR-0001"):
        translations(lost, sources)
    added = {"notes": [{"key": "o", "text": "Outcome\n\nIssues:\n- ISS-0001: Button\n"
                                            "- ISS-9999: Extra"}, good["notes"][1]]}
    with pytest.raises(BadAnswer, match="лишние номера ISS-9999"):
        translations(added, sources)
    # Номер на месте, но строка задачи — уже не строка задачи: итог её бы потерял.
    reworded = {"notes": [{"key": "o", "text": "Outcome\n\nIssues: ISS-0001 (Button)"},
                          good["notes"][1]]}
    with pytest.raises(BadAnswer, match="строки задач"):
        translations(reworded, sources)


# --- файлы задач: поток их больше не выгружает, их выгружает этап «Задачи»


def test_issue_files_of_an_old_export_are_no_longer_the_streams(root):
    first, _, _, _ = export(root)
    old = first.model_copy(update={"notes": [*first.notes, ExportedNote(
        key="i:запуск", id="ISS-0008", type="issue", generated="…", written="…",
        digest="")]})
    assert export_in(old, root) == first
    notes, vanished, _ = draft(root, previous=export_in(old, root))
    assert not any(note.type == "issue" for note in notes) and vanished == []


@pytest.fixture
def issues(tmp_path):
    return tmp_path / "issues"


def test_two_files_of_one_issue_stop_the_reading(issues):
    issues.mkdir()
    for name in ("ISS-0008.md", "copy.md"):
        (issues / name).write_text("---\nid: ISS-8\n---\n\nЗадача\n", encoding="utf-8")
    with pytest.raises(NotesError, match="Два файла задачи ISS-0008"):
        loaded(issues)


def test_an_issue_file_reads_back_as_written():
    note = Note("ISS-0012", "issue", "# Поиск\n\nИщется.", ("OUT-0003", "ADR-0007", "ISS-0011"))
    back = issue_parsed(issue_rendered(note))
    assert (back.id, back.type, back.body, back.links) == (
        "ISS-0012", "issue", "# Поиск\n\nИщется.", ("OUT-0003", "ADR-0007", "ISS-0011"))
