"""Выгрузка потока в заметки: что ложится, под какими номерами и что при повторной выгрузке."""

from pathlib import Path

import pytest

from spec_council.export import WORDS as LANGUAGES
from spec_council.export import (
    drafted,
    graph_problems,
    numbered_issues,
    outcome_text,
    translations,
    untranslated,
    words_for,
    written,
)
from spec_council.models import (
    Decision,
    Issue,
    IssueDiscovery,
    LabeledFragment,
    NotesExport,
    OpenQuestion,
    Outcome,
    OutcomeDiscovery,
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
ISSUES = IssueDiscovery(state="done", run="i1", outcomes="o1", steps=[], issues=[
    Issue(id="I1", title="Запуск деплоя по merge", user_story="As a dev…",
          outcome_ids=["O1"])])
STREAM = Stream(group="A", idea=StreamIdea(text="Деплой требует меньше ручной работы.",
                                           by="human"),
                scope=SCOPE, proposals=FOUND, decisions=DECIDED, outcomes=OUTCOMES,
                issues=ISSUES)
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


def draft(root, stream=STREAM, previous=None, language="Russian"):
    return drafted(stream, FRAGMENTS, Catalog.load(root), root, previous, WORDS, language)


def export(root, stream=STREAM, previous=None, edits=None, delete=()):
    notes, vanished, numbers, skipped = draft(root, stream, previous)
    catalog = Catalog.load(root)
    graph_problems(catalog, notes, vanished, edits or {}, delete)
    done = written(notes, vanished, edits or {}, delete, root, previous, catalog)
    return NotesExport(run="r", issues=stream.issues.run, language="Russian", notes=done,
                       numbers=numbers), notes, vanished, skipped


def by_id(notes):
    return {note.id: note for note in notes}


def test_a_stream_becomes_linked_notes_with_numbers_after_the_catalog(root):
    notes, vanished, numbers, skipped = draft(root)
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
        "- Merge в main выкладывает сборку.\n\nЗадачи:\n- ISS-0008: Запуск деплоя по merge")
    assert [(n.id, n.issue_id) for n in numbers] == [("ISS-0008", "I1")]
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
    notes, _, numbers, _ = draft(root, previous=first)
    assert {note.action for note in notes} == {"same"}
    assert by_id(notes)["IDEA-0002"].text == "Деплой без ручной работы."   # правка осталась
    assert [n.id for n in numbers] == ["ISS-0008"]


def test_a_file_edited_by_hand_is_left_alone(root):
    first, _, _, _ = export(root)
    path = root / "ideas" / "IDEA-0002.md"
    path.write_text(path.read_text(encoding="utf-8") + "Дописали руками.\n", encoding="utf-8")
    notes, _, _, _ = draft(root, previous=first)
    edited = by_id(notes)["IDEA-0002"]
    assert edited.action == "edited" and "Дописали руками." in edited.current
    record, _, _, _ = export(root, previous=first)
    assert "Дописали руками." in path.read_text(encoding="utf-8")
    assert by_id(record.notes)["IDEA-0002"].digest == first.notes[0].digest


def test_another_choice_is_another_decision_and_the_old_one_is_kept_unless_deleted(root):
    first, _, _, _ = export(root)
    other = STREAM.model_copy(update={"decisions": [
        DECIDED[0].model_copy(update={"proposal": "P1"}), *DECIDED[1:]]})
    notes, vanished, _, _ = draft(root, other, previous=first)
    assert by_id(notes)["ADR-0004"].links == ["PRO-0003"]            # новый номер
    assert [(v.id, v.linked_from) for v in vanished] == [("ADR-0002", [])]
    record, _, _, _ = export(root, other, previous=first)
    assert (root / "adrs" / "ADR-0002.md").exists()                     # само не удаляется
    kept = [note for note in record.notes if note.kept]
    assert [(n.id, n.key) for n in kept] == [("ADR-0002", first.notes[8].key)]   # всё ещё наше
    _, vanished, _, _ = draft(root, other, previous=record)
    assert [v.id for v in vanished] == ["ADR-0002"]                       # и снова к удалению
    _, _, _, _ = export(root, other, previous=first, delete=["ADR-0002"])
    assert not (root / "adrs" / "ADR-0002.md").exists()


def test_a_vanished_note_linked_from_outside_is_not_deleted(root):
    first, _, _, _ = export(root)
    outside = Note("OQ-0009", "open_question", "Пересмотреть?", ("ADR-0002",))
    (root / "open_questions" / "OQ-0009.md").write_text(rendered(outside), encoding="utf-8")
    other = STREAM.model_copy(update={"decisions": [
        DECIDED[0].model_copy(update={"proposal": "P1"}), *DECIDED[1:]]})
    _, vanished, _, _ = draft(root, other, previous=first)
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
    _, vanished, _, _ = draft(root, other, previous=first)
    assert [(v.id, v.linked_from) for v in vanished] == [("ADR-0002", []), ("OUT-0002", [])]
    with pytest.raises(NotesError, match="OUT-0002: ссылка на несуществующую заметку ADR-0002"):
        export(root, other, previous=first, delete=["ADR-0002"])
    assert (root / "adrs" / "ADR-0002.md").exists()                     # файлы не тронуты
    export(root, other, previous=first, delete=["ADR-0002", "OUT-0002"])
    assert Catalog.load(root).problems() == []


def twins(order=(0, 1)):
    twin = OUTCOMES.outcomes[0].model_copy(update={"id": "O3", "behavior": "И откат по merge."})
    other = ISSUES.issues[0].model_copy(update={"id": "I2", "user_story": "As an ops…",
                                                "outcome_ids": ["O3"]})
    outcomes, issues = [OUTCOMES.outcomes[0], twin], [ISSUES.issues[0], other]
    return STREAM.model_copy(update={
        "outcomes": OUTCOMES.model_copy(update={"outcomes": [
            *(outcomes[i] for i in order), OUTCOMES.outcomes[1]]}),
        "issues": ISSUES.model_copy(update={"issues": [issues[i] for i in order]})})


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


def test_outcomes_and_issues_with_the_same_title_stay_separate(root):
    first, notes, _, _ = export(root, twins())
    assert len({note.key for note in notes}) == len(notes)
    assert [n.id for n in notes if n.type == "outcome"] == ["OUT-0002", "OUT-0003"]
    assert "И откат по merge." in (root / "outcomes" / "OUT-0003.md").read_text(encoding="utf-8")
    assert [(n.id, n.issue_id) for n in first.numbers] == [("ISS-0008", "I1"), ("ISS-0009", "I2")]
    again, _, numbers, _ = draft(root, twins(), previous=first)
    assert {note.action for note in again} == {"same"}
    assert [(n.id, n.issue_id) for n in numbers] == [("ISS-0008", "I1"), ("ISS-0009", "I2")]
    # Модель отдала их в другом порядке — номера держатся за суть, а не за место в списке.
    swapped, _, numbers, _ = draft(root, twins((1, 0)), previous=first)
    assert {n.id: n.text.split("\n")[2] for n in swapped if n.type == "outcome"} == {
        "OUT-0002": "После merge CI сам выкладывает.", "OUT-0003": "И откат по merge."}
    assert [(n.id, n.issue_id) for n in numbers] == [("ISS-0009", "I2"), ("ISS-0008", "I1")]


def test_a_second_outcome_with_the_same_title_keeps_the_first_ones_numbers(root):
    first, _, _, _ = export(root)                       # итог «Деплой по merge» один
    notes, vanished, numbers, _ = draft(root, twins(), previous=first)
    assert vanished == []
    assert {n.text.split("\n")[2]: n.id for n in notes if n.type == "outcome"} == {
        "После merge CI сам выкладывает.": "OUT-0002", "И откат по merge.": "OUT-0003"}
    assert [(n.id, n.issue_id) for n in numbers] == [("ISS-0008", "I1"), ("ISS-0009", "I2")]
    second, _, _, _ = export(root, twins(), previous=first)
    notes, vanished, numbers, _ = draft(root, previous=second)   # двойник ушёл
    assert [n.id for n in notes if n.type == "outcome"] == ["OUT-0002"]
    assert [v.id for v in vanished] == ["OUT-0003"]
    assert [(n.id, n.issue_id) for n in numbers] == [("ISS-0008", "I1")]


def test_an_outcome_reworded_under_the_same_title_keeps_its_number(root):
    first, _, _, _ = export(root)
    reworded = OUTCOMES.model_copy(update={"outcomes": [OUTCOMES.outcomes[0].model_copy(
        update={"behavior": "CI выкладывает сборку после merge."}), *OUTCOMES.outcomes[1:]]})
    notes, vanished, _, _ = draft(root, STREAM.model_copy(update={"outcomes": reworded}),
                                  previous=first)
    assert vanished == []
    assert by_id(notes)["OUT-0002"].action == "update"


def test_another_notes_language_translates_the_notes_again(root):
    first, _, _, _ = export(root, edits={"idea": "Деплой без ручной работы."})
    notes, _, _, _ = draft(root, previous=first, language="English")
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


def test_an_issue_whose_outcomes_are_not_exported_gets_no_number(root):
    held = ISSUES.model_copy(update={"issues": [*ISSUES.issues, Issue(
        id="I2", title="Где хранить секреты", user_story="…", outcome_ids=["O2"])]})
    record, _, _, skipped = export(root, STREAM.model_copy(update={"issues": held}))
    # Итог O2 не выгружается: номер ей нигде в каталоге не закрепить — его не раздаём.
    assert [(n.id, n.issue_id) for n in record.numbers] == [("ISS-0008", "I1")]
    assert any("I2" in reason and "без номера" in reason for reason in skipped)


def test_a_previous_issue_number_taken_by_another_stream_is_not_reused(root):
    first, _, _, _ = export(root)
    # Строку задачи из нашего итога убрали руками, а другой поток объявил ISS-0008 своим.
    ours = root / "outcomes" / "OUT-0002.md"
    ours.write_text(ours.read_text(encoding="utf-8").split("\n\nЗадачи:")[0] + "\n",
                    encoding="utf-8")
    other = Note("OUT-0099", "outcome", "Чужой итог\n\nЗадачи:\n- ISS-0008: Чужая", ("ADR-0001",))
    path_of(root, other).write_text(rendered(other), encoding="utf-8")
    numbers = numbered_issues(STREAM, Catalog.load(root), first)
    assert [(n.id, n.issue_id) for n in numbers] == [("ISS-0009", "I1")]


def test_a_file_edited_by_hand_keeps_the_text_it_was_exported_from(root):
    first, _, _, _ = export(root)
    path = root / "ideas" / "IDEA-0002.md"
    original = path.read_bytes()
    path.write_bytes(original + "Дописали руками.\n".encode())
    other = STREAM.model_copy(update={"idea": StreamIdea(text="Деплой идёт сам.", by="human")})
    second, _, _, _ = export(root, other, previous=first)          # файл правили — не трогаем
    path.write_bytes(original)                                       # правку откатили
    notes, _, _, _ = draft(root, other, previous=second)
    idea = by_id(notes)["IDEA-0002"]
    assert (idea.action, idea.text) == ("update", "Деплой идёт сам.")    # новое — предложено


def test_a_new_issue_takes_the_next_number_and_the_old_ones_keep_theirs(root):
    first, _, _, _ = export(root)
    more = ISSUES.model_copy(update={"issues": [
        *ISSUES.issues, Issue(id="I2", title="Уведомление о деплое", user_story="…",
                              outcome_ids=["O1"])]})
    numbers = numbered_issues(STREAM.model_copy(update={"issues": more}), Catalog.load(root),
                              first)
    assert [(n.id, n.issue_id) for n in numbers] == [("ISS-0008", "I1"), ("ISS-0009", "I2")]


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
    notes, _, _, _ = draft(root, previous=first)
    idea = next(note for note in notes if note.type == "idea")
    assert (idea.id, idea.action) == ("IDEA-0100", "create")
    export(root, previous=first)
    assert path.read_text(encoding="utf-8") == rendered(foreign)          # не затёрта


def test_an_edit_must_keep_the_numbers_and_the_issue_lines(root):
    notes, _, _, _ = draft(root)
    outcome = next(note for note in notes if "\n- ISS-" in note.text)
    idea = notes[0]
    catalog = Catalog.load(root)
    wrong = [(outcome, outcome.text.split("\n\n" + WORDS["issues"])[0], "потеряны номера ISS-"),
             (outcome, outcome.text.replace("\n- ISS-", "\nСм. ISS-"), "строки задач не те"),
             (idea, idea.text + " Как в ADR-0042.", "лишние номера ADR-0042")]
    for note, text, problem in wrong:
        with pytest.raises(NotesError, match=f"В правке заметки {note.id} {problem}"):
            written(notes, [], {note.key: text}, [], root, None, catalog)
    assert sorted(Catalog.load(root).notes) == sorted(note.id for note in PAST)   # не тронут


def test_an_empty_text_anywhere_leaves_the_catalog_as_it_was(root):
    notes, _, _, _ = draft(root)
    last = notes[-1]
    with pytest.raises(NotesError, match=f"У заметки {last.id} пустой текст"):
        written(notes, [], {last.key: " "}, [], root, None, Catalog.load(root))
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
    text = outcome_text("Поиск", "Ищется.", ["ISS-0042: регресс не вернулся"], [], words)
    assert declared_issues(text) == []
    # И на языке, подписи которого совет не знает: критерий — не строка задачи.
    foreign = text.replace(f"{words['criteria']}:", "Criterios de aceptación:")
    assert declared_issues(foreign) == [] and "- ISS-0042 — регресс не вернулся" in foreign


def test_a_translation_does_not_turn_a_criterion_into_an_issue_line():
    source = outcome_text("Поиск", "Ищется.", ["ISS-0042: регресс не вернулся"], [],
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
