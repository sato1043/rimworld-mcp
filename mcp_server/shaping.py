"""
Shape bridge responses into what an LLM needs to read.

The bridge answers with everything it knows: every animal on the map, every powered
building, every training flag. Most of that is noise when the question is "what is
going on in the colony", and every byte of it is paid for in tokens. The functions
here decide what the tools return by default. They take the bridge's JSON and return
JSON, and touch neither the network nor FastMCP, so they can be tested on their own.

A bridge error ({"error": ...}, or a list holding only such objects) is passed through
unchanged, so the caller still sees why the game could not answer.
"""

from collections import defaultdict
from typing import Any


def is_error(payload: Any) -> bool:
    """Whether the bridge answered with an error instead of data.

    The bridge's error is an object holding "error" and nothing else, on its own or
    as every item of a list. A record that merely has an "error" field is data.
    """
    def one(p: Any) -> bool:
        return isinstance(p, dict) and set(p) == {"error"}

    if isinstance(payload, dict):
        return one(payload)
    return isinstance(payload, list) and bool(payload) and all(one(p) for p in payload)


class NoSuchRace(ValueError):
    """`race` matched no animal; the message names the races that are on the map."""

    def __init__(self, race: str, races: list[str]) -> None:
        super().__init__(
            f"no animal of race {race!r} is on the map. race is matched against the "
            f"race labels the game shows, in its display language; the races on the "
            f"map are: {', '.join(races) or 'none'}")


def shape_animals(animals: Any, race: str = "", detail: bool = False) -> Any:
    """Colony animals one by one; every other animal as a head count per race.

    A map can hold hundreds of wild animals, and listing each one costs the same
    tokens whether or not anyone means to hunt it. The count keeps the part for
    animals outside the colony proportional to the number of races rather than of
    animals; colony animals are still listed one by one.

    `race` lists the animals of that race one by one, ids included, for commands
    that need a target. An empty `race` means none was given, as with the other
    optional text arguments of the tools. A race that matches nothing raises
    NoSuchRace, so that it is not mistaken for a race that is merely absent.
    `detail` returns the bridge's list unchanged; `race` takes precedence over it.
    """
    if is_error(animals):
        return animals
    if race:
        wanted = race.casefold()
        matches = [a for a in animals if (a["race"] or "").casefold() == wanted]
        if not matches:
            raise NoSuchRace(race, sorted({a["race"] or "" for a in animals}))
        return matches
    if detail:
        return animals

    colony = [
        {"id": a["id"], "name": a["name"], "race": a["race"],
         "health": a["health"], "job": a["job"]}
        for a in animals if a["tame"]
    ]
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for a in animals:
        if not a["tame"]:
            counts[(a["race"], a["faction"])] += 1
    # A def without a label gives a null race; sort it as empty text.
    others = [
        {"race": r, "faction": f, "count": n}
        for (r, f), n in sorted(counts.items(),
                                key=lambda kv: (-kv[1], kv[0][0] or "", kv[0][1] or ""))
    ]
    return {"colony": colony, "others": others}


def shape_buildings(buildings: Any, detail: bool = False) -> Any:
    """Powered buildings as one line per kind instead of one per building.

    The per-kind summary and the damaged list pass through: the first is already
    one line per kind, and the second lists what needs repair, which is actionable
    building by building. `detail` returns the bridge's answer unchanged.
    """
    if is_error(buildings) or detail:
        return buildings

    groups: dict[str, dict[str, Any]] = {}
    for b in buildings["powered"]:
        g = groups.setdefault(b["defName"], {
            "defName": b["defName"], "label": b["label"],
            "count": 0, "poweredOn": 0, "powerOutput": 0.0,
        })
        g["count"] += 1
        g["poweredOn"] += 1 if b["powered"] else 0
        g["powerOutput"] += b["powerOutput"]
    powered = sorted(groups.values(), key=lambda g: (-g["count"], g["defName"]))
    for g in powered:
        g["powerOutput"] = round(g["powerOutput"], 1)
    return {"summary": buildings["summary"], "damaged": buildings["damaged"],
            "powered": powered}


def shape_training(animals: Any, detail: bool = False) -> Any:
    """Training as two lists of names per animal: learned, and pending.

    The bridge lists every step twice (defName and label) with two flags. The two
    lists keep the same distinction in fewer tokens. Pending is a step set to be
    trained and not learned yet; a step that is learned but no longer wanted
    appears only as learned, which is what the animal can do. `detail` returns the
    bridge's list unchanged.
    """
    if is_error(animals) or detail:
        return animals
    return [
        {
            "id": a["id"], "name": a["name"], "race": a["race"],
            "learned": [s["label"] for s in a["training"] if s["learned"]],
            "pending": [s["label"] for s in a["training"]
                        if s["wanted"] and not s["learned"]],
            "bondedTo": a["bondedTo"],
        }
        for a in animals
    ]


def shape_colonists(pawns: Any) -> Any:
    """Who is where in what state, without skills and passions.

    Skills are what make a colonist's entry large, and they change slowly; the
    overview leaves them to get_pawns.
    """
    if is_error(pawns):
        return pawns
    return [
        {"id": p["id"], "name": p["name"], "health": p["health"],
         "drafted": p["drafted"], "downed": p["downed"], "job": p["job"]}
        for p in pawns
    ]
