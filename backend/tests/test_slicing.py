"""Разбор и проверка ответов моделей: нарезка по границам, разметка."""

import pytest

from spec_council.slicing import (
    BadAnswer,
    BoundaryNote,
    JudgeRejected,
    LabelOption,
    SliceOption,
    agreed_label,
    boundary_notes,
    bounds_of,
    cut,
    judged_bounds,
    judged_labels,
    label_options,
    note_places,
    parse_json,
    slice_options,
)

TEXT = ("worker крутится локально, принимает задания по HTTP. "
        "«Главное» — не потерять результат, если что-то упало.")
FRAGMENTS = ["worker крутится локально,", "принимает задания по HTTP.",
             "«Главное» — не потерять результат, если что-то упало."]


def test_json_in_a_fence_or_with_text_around():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Вот ответ:\n{"a": 1}\nГотово.') == {"a": 1}
    with pytest.raises(BadAnswer, match="нет JSON"):
        parse_json("не знаю")
    with pytest.raises(BadAnswer, match="не JSON-объект"):
        parse_json("[1, 2]")


def test_same_boundaries_despite_spaces_and_punctuation_at_the_edges():
    shifted = ["worker крутится локально", ", принимает задания по HTTP. ",
               "«Главное» — не потерять результат, если что-то упало."]
    assert bounds_of(TEXT, FRAGMENTS) == bounds_of(TEXT, shifted)


def test_cut_is_verbatim_and_keeps_opening_quotes_with_their_fragment():
    assert cut(TEXT, bounds_of(TEXT, FRAGMENTS)) == FRAGMENTS


@pytest.mark.parametrize(("fragments", "problem"), [
    (["worker крутится локально,", "принимает задания по HTTP,"], "дословно"),
    (["принимает задания по HTTP.", "worker крутится локально,"], "потерян текст перед"),
    (["worker крутится локально,", "«Главное» — не потерять результат, если что-то упало."],
     "потерян текст перед"),
    (["worker крутится локально,", "принимает задания по HTTP."], "потерян текст в конце"),
    (["worker крутится локально, принимает", "принимает задания по HTTP.",
      "«Главное» — не потерять результат, если что-то упало."], "не по порядку"),
    ([], "нет списка"),
    (["worker крутится локально,", " — "], "без текста"),
])
def test_bad_slicing_is_refused(fragments, problem):
    with pytest.raises(BadAnswer, match=problem):
        bounds_of(TEXT, fragments)


def test_bad_option_is_dropped_while_a_good_one_remains():
    data = {"options": [{"fragments": ["выдумка"]}, {"fragments": FRAGMENTS, "reason": "так"}]}
    assert slice_options(TEXT, data) == [SliceOption(bounds_of(TEXT, FRAGMENTS), "так")]
    with pytest.raises(BadAnswer, match="дословно"):
        slice_options(TEXT, {"options": [{"fragments": ["выдумка"]}]})


def test_judge_cannot_invent_a_boundary():
    whole = SliceOption(bounds_of(TEXT, [TEXT]), None)
    split = SliceOption(bounds_of(TEXT, FRAGMENTS), None)
    two = ["worker крутится локально, принимает задания по HTTP.", FRAGMENTS[2]]
    judged = judged_bounds(TEXT, {"status": "ok", "fragments": two}, [whole, split])
    assert judged == bounds_of(TEXT, two)

    invented = ["worker крутится", "локально, принимает задания по HTTP.", FRAGMENTS[2]]
    with pytest.raises(BadAnswer, match="не было ни в одном варианте"):
        judged_bounds(TEXT, {"status": "ok", "fragments": invented}, [whole, split])


def test_judge_may_refuse_every_option():
    with pytest.raises(JudgeRejected, match="не принял ни один вариант: все теряют текст"):
        judged_bounds(TEXT, {"status": "no_valid_option", "problem": "все теряют текст"}, [])


def test_labels_must_cover_every_fragment_with_known_types():
    good = {"labels": [{"id": 1, "options": [{"label": "idea", "reason": "цель"}]},
                       {"id": 2, "options": [{"label": "risk", "reason": "потеря"},
                                             {"label": "constraint", "reason": "граница"}]}]}
    assert label_options(good, [1, 2])[2] == [
        LabelOption("risk", "потеря"), LabelOption("constraint", "граница")]

    with pytest.raises(BadAnswer, match="не размечены фрагменты 2"):
        label_options({"labels": good["labels"][:1]}, [1, 2])
    with pytest.raises(BadAnswer, match="тип не из"):
        label_options({"labels": [{"id": 1, "options": [{"label": "goal"}]}]}, [1])
    with pytest.raises(BadAnswer, match="неизвестного фрагмента"):
        label_options({"labels": [{"id": 7, "options": [{"label": "idea"}]}]}, [1])


def test_judge_decides_exactly_the_disputed_fragments():
    data = {"labels": [{"id": 3, "label": "constraint", "reason": "уже задано"}]}
    assert judged_labels(data, [3]) == {3: LabelOption("constraint", "уже задано")}
    with pytest.raises(BadAnswer, match="нет решения по фрагментам 4"):
        judged_labels(data, [3, 4])
    with pytest.raises(BadAnswer, match="не давали"):
        judged_labels(data, [4])


def test_agreement_needs_one_option_everywhere_and_the_same_type():
    idea, idea2, risk = LabelOption("idea", "а"), LabelOption("idea", "б"), LabelOption("risk", "в")
    assert agreed_label([[idea], [idea2]]) == idea
    assert agreed_label([[idea], [risk]]) is None
    assert agreed_label([[idea, risk], [idea]]) is None


def test_judge_notes_land_on_the_fragment_where_the_boundary_is():
    data = {"decisions": [
        {"boundary": "локально, | принимает", "decision": "split", "reason": "два решения"},
        {"boundary": "кривая запись без черты", "reason": "пропустить"},
        {"boundary": "нет такого | и такого", "reason": "не найдено"},
        "не объект",
    ]}
    notes = boundary_notes(data)
    assert len(notes) == 2
    assert note_places(FRAGMENTS, notes) == {1: "два решения"}


@pytest.mark.parametrize(("text", "fragments"), [
    ("- Первое\n- Второе", ["- Первое", "- Второе"]),
    ("* один;\n* два.", ["* один;", "* два."]),
    ("1. Раз.\n2. Два.", ["1. Раз.", "2. Два."]),
    ("Слева (см. ниже) справа. «Цитата» — дальше.",
     ["Слева (см. ниже) справа.", "«Цитата» — дальше."]),
    ("склеено«так»", ["склеено", "«так»"]),
])
def test_list_markers_and_quotes_stay_with_their_own_fragment(text, fragments):
    assert cut(text, bounds_of(text, fragments)) == fragments


def test_decisions_that_are_not_a_list_are_just_no_notes():
    assert boundary_notes({"decisions": 1}) == []
    assert boundary_notes({"decisions": "граница"}) == []


def test_note_finds_its_boundary_by_both_quotes_when_a_phrase_repeats():
    fragments = ["Use files.", "Use files remotely."]
    note = BoundaryNote("Use files.", "Use files", "две разные мысли")
    assert note_places(fragments, [note]) == {1: "две разные мысли"}


def test_note_about_a_boundary_not_drawn_lands_inside_the_fragment():
    fragments = ["Первое.", "Одна мысль, её продолжение.", "Третье."]
    note = BoundaryNote("Одна мысль,", "её продолжение", "не делить")
    assert note_places(fragments, [note]) == {1: "не делить"}


def test_quotes_compare_without_edge_punctuation():
    fragments = ["без базы.", "Главное — не потерять."]
    assert note_places(fragments, [BoundaryNote("без базы", "«Главное", "ок")]) == {1: "ок"}
