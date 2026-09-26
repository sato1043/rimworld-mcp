"""What the default tool output keeps, drops and folds, checked without the game."""

import json

import pytest

from shaping import (
    NoSuchRace, is_error, shape_animals, shape_buildings, shape_colonists,
    shape_training,
)


def size(payload) -> int:
    return len(json.dumps(payload, ensure_ascii=False))


def animal(i: int, race: str = "Deer", tame: bool = False,
           faction: str = "wild") -> dict:
    """One animal as the bridge's /animals lists it."""
    return {"id": f"{race}{i}", "name": f"{race.lower()} {i}", "race": race,
            "position": {"x": i, "z": i}, "health": 1.0,
            "faction": "Colony" if tame else faction, "tame": tame,
            "job": "wandering"}


def powered(i: int, def_name: str = "StandingLamp", on: bool = True,
            output: float = -30.0) -> dict:
    """One entry of /buildings' powered list."""
    return {"id": f"{def_name}{i}", "label": def_name.lower(), "defName": def_name,
            "position": {"x": i, "z": i}, "hp": 100, "maxHp": 100,
            "powered": on, "powerOutput": output}


def buildings(powered_list: list[dict]) -> dict:
    return {"powered": powered_list,
            "damaged": [{"id": "Wall1", "label": "wall", "position": {"x": 0, "z": 0},
                         "hp": 50, "maxHp": 100, "pct": 0.5}],
            "summary": [{"defName": "Wall", "label": "wall", "count": 1, "damaged": 1}]}


# ── Errors pass through ───────────────────────────────────────────────────────

ERRORS = [{"error": "No active map"}, [{"error": "No active map"}]]


@pytest.mark.parametrize("payload", ERRORS)
@pytest.mark.parametrize("shape", [shape_animals, shape_buildings, shape_training,
                                   shape_colonists])
def test_bridge_errors_pass_through_unchanged(shape, payload):
    assert shape(payload) == payload


def test_a_record_that_merely_has_an_error_field_is_data():
    assert not is_error([{"id": "x", "error": "not the bridge's"}])
    assert not is_error({"id": "x", "error": "not the bridge's"})
    assert not is_error([])


# ── Animals ───────────────────────────────────────────────────────────────────

def test_other_animals_cost_the_same_whether_one_or_a_hundred():
    one = shape_animals([animal(0)])
    hundred = shape_animals([animal(i) for i in range(100)])
    assert hundred["others"] == [{"race": "Deer", "faction": "wild", "count": 100}]
    # The only growth allowed is the count itself going from one digit to three.
    assert size(hundred) - size(one) == len("100") - len("1")


def test_colony_animals_are_listed_one_by_one_without_position():
    shaped = shape_animals([animal(1, "Dog", tame=True), animal(2, "Dog", tame=True)])
    assert shaped["colony"] == [
        {"id": "Dog1", "name": "dog 1", "race": "Dog", "health": 1.0, "job": "wandering"},
        {"id": "Dog2", "name": "dog 2", "race": "Dog", "health": 1.0, "job": "wandering"},
    ]
    assert shaped["others"] == []


def test_others_are_counted_per_race_and_faction_largest_first():
    animals = ([animal(i, "Deer") for i in range(2)]
               + [animal(i, "Rat") for i in range(3)]
               + [animal(9, "Muffalo", faction="Traders")])
    assert shape_animals(animals)["others"] == [
        {"race": "Rat", "faction": "wild", "count": 3},
        {"race": "Deer", "faction": "wild", "count": 2},
        {"race": "Muffalo", "faction": "Traders", "count": 1},
    ]


def test_race_lists_that_race_with_ids_for_targeting():
    animals = [animal(1, "Deer"), animal(2, "Rat"), animal(3, "Deer", tame=True)]
    assert shape_animals(animals, race="deer") == [animals[0], animals[2]]


def test_an_empty_race_means_none_was_given():
    animals = [animal(1, "Deer"), animal(2, "Dog", tame=True)]
    assert shape_animals(animals, race="") == shape_animals(animals)


def test_a_race_that_matches_nothing_names_the_races_on_the_map():
    animals = [animal(1, "Deer"), animal(2, "Rat")]
    with pytest.raises(NoSuchRace, match="Deer, Rat"):
        shape_animals(animals, race="Muffalo")


def test_race_takes_precedence_over_detail():
    animals = [animal(1, "Deer"), animal(2, "Rat")]
    assert shape_animals(animals, race="Rat", detail=True) == [animals[1]]


def test_an_animal_without_a_race_label_is_counted_not_crashed_on():
    animals = [animal(1, "Deer"), {**animal(2), "race": None}]
    assert shape_animals(animals)["others"] == [
        {"race": None, "faction": "wild", "count": 1},
        {"race": "Deer", "faction": "wild", "count": 1},
    ]
    assert shape_animals(animals, race="deer") == [animals[0]]


def test_detail_returns_the_bridge_list_unchanged():
    animals = [animal(1), animal(2, "Dog", tame=True)]
    assert shape_animals(animals, detail=True) == animals


# ── Buildings ─────────────────────────────────────────────────────────────────

def test_powered_buildings_cost_the_same_whether_one_or_a_hundred():
    one = shape_buildings(buildings([powered(0)]))
    hundred = shape_buildings(buildings([powered(i) for i in range(100)]))
    assert hundred["powered"] == [{"defName": "StandingLamp", "label": "standinglamp",
                                   "count": 100, "poweredOn": 100,
                                   "powerOutput": -3000.0}]
    # The only growth allowed is in the numbers: count and poweredOn going from one
    # digit to three, and the summed output from -30.0 to -3000.0.
    assert size(hundred) - size(one) == ((len("100") - len("1")) * 2
                                         + len("-3000.0") - len("-30.0"))


def test_powered_kinds_count_what_is_switched_on_and_sum_output():
    shaped = shape_buildings(buildings([
        powered(1, "Battery", on=True, output=0.0),
        powered(2, "SolarGenerator", on=True, output=1700.04),
        powered(3, "SolarGenerator", on=False, output=0.0),
        powered(4, "SolarGenerator", on=True, output=1700.04),
    ]))
    assert shaped["powered"] == [
        {"defName": "SolarGenerator", "label": "solargenerator", "count": 3,
         "poweredOn": 2, "powerOutput": 3400.1},
        {"defName": "Battery", "label": "battery", "count": 1,
         "poweredOn": 1, "powerOutput": 0.0},
    ]


def test_summary_and_damaged_pass_through():
    raw = buildings([powered(1)])
    shaped = shape_buildings(raw)
    assert shaped["summary"] == raw["summary"]
    assert shaped["damaged"] == raw["damaged"]


def test_buildings_detail_returns_the_bridge_answer_unchanged():
    raw = buildings([powered(1), powered(2)])
    assert shape_buildings(raw, detail=True) == raw


# ── Training ──────────────────────────────────────────────────────────────────

def step(label: str, learned: bool, wanted: bool) -> dict:
    return {"defName": label.capitalize(), "label": label,
            "learned": learned, "wanted": wanted}


TRAINING = [{"id": "Dog1", "name": "dog", "race": "Dog", "position": {"x": 1, "z": 1},
             "health": 1.0, "bondedTo": ["Isla"],
             "training": [step("guard", learned=True, wanted=True),
                          step("obedience", learned=True, wanted=False),
                          step("rescue", learned=False, wanted=True)]}]


def test_training_keeps_learned_apart_from_pending():
    assert shape_training(TRAINING) == [
        {"id": "Dog1", "name": "dog", "race": "Dog",
         "learned": ["guard", "obedience"], "pending": ["rescue"],
         "bondedTo": ["Isla"]},
    ]


def test_training_detail_returns_the_bridge_list_unchanged():
    assert shape_training(TRAINING, detail=True) == TRAINING


# ── Colonists ─────────────────────────────────────────────────────────────────

def test_colonists_keep_state_and_drop_skills():
    raw = [{"id": "Human1", "name": "Isla", "position": {"x": 1, "z": 2},
            "health": 0.9, "drafted": False, "downed": True, "job": "resting",
            "jobTarget": "bed", "skills": {"Shooting": 8}, "passions": {"Shooting": "Major"}}]
    assert shape_colonists(raw) == [
        {"id": "Human1", "name": "Isla", "health": 0.9,
         "drafted": False, "downed": True, "job": "resting"},
    ]
