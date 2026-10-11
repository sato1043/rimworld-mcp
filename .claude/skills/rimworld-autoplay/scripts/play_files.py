"""Where the autoplay keeps its files, and the names those files are kept under.

Each colony has a directory under .claude/play/ of the main checkout: the plan file the
cycles read and write, the watcher's state, the usage of the run, and the parent's mark
of a cycle at work. The watcher, the parent's checks and the usage gate share these, and
the reading of the plan file's sections.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
import unicodedata
from typing import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
PLAY_ROOT = REPO_ROOT / ".claude" / "play"
UNSAFE_NAME_CHARS = set('/\\:*?"<>|')
# Names Windows keeps for devices, whatever follows a dot.
DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
# The parent's mark of a cycle at work, next to the colony's plan file. check_plan.py
# keeps it before the cycle and removes it in the check after.
CYCLE_MARK = "cycle.json"
# The colony's plan file, the only memory the cycles share.
PLAN = "plan.md"
LIST_ITEM = re.compile(r"(?:[-*+]|\d+[.)])(?:\s|$)")
# Where a cycle keeps the `next` its last get_events returned, named as rimworld-play's
# template names it.
EVENTS_PLACE = "## 出来事の位置"
NEXT_FIELD = "next:"
REPLACE_TRIES = 3
REPLACE_WAIT_SECONDS = 0.1


def colony_name_problem(colony: str) -> str | None:
    if (not colony or colony != colony.strip() or colony.startswith(".") or colony.endswith(".")
            or UNSAFE_NAME_CHARS & set(colony)):
        return f"not a usable colony name: {colony!r}"
    if colony.split(".")[0].rstrip().upper() in DEVICE_NAMES:
        return f"not a usable colony name: {colony!r} is a name Windows keeps for a device"
    # A name typed in decomposed form does not match a directory made in composed form on
    # every file system, so the same colony could be missed or made twice.
    if unicodedata.normalize("NFC", colony) != colony:
        return f"not a usable colony name: {colony!r} is not in composed form (NFC); type it again"
    return None


def user_path(text: str) -> pathlib.Path:
    """A path argument, with ~ read as the home directory whether the shell expanded it or not.

    A relative path is taken from the checkout the scripts are in, as the colony's directory
    is, rather than from wherever the command was given."""
    path = pathlib.Path(text).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def missing_colony(colony_dir: pathlib.Path) -> str:
    """Why a colony's directory is not found, with where the colonies are kept."""
    return (f"there is no colony directory {colony_dir}. The colonies are kept under .claude/play/ "
            f"of the main checkout; run this from there")


def replace_file(path: pathlib.Path, text: str, tries: int = REPLACE_TRIES,
                 sleep: Callable[[float], None] = time.sleep) -> None:
    """Write the file whole: a reader sees the text before or after, never a part of it.

    On Windows a file another process holds open for an instant (a virus scanner, the
    indexer) refuses to be replaced, so a refusal is tried again."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    for attempt in range(tries):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            sleep(REPLACE_WAIT_SECONDS)


class MarkUnreadable(Exception):
    """The mark of a cycle does not keep the time the cycle began."""


def mark_time(mark: pathlib.Path) -> float:
    """The time check_plan.py --start kept in the mark of a cycle."""
    try:
        started_at = json.loads(mark.read_text(encoding="utf-8"))["started_at"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise MarkUnreadable(f"cannot read the time kept by --start in {CYCLE_MARK}: {e}") from e
    if not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
        raise MarkUnreadable(f"the time kept in {CYCLE_MARK} is not a number")
    return float(started_at)


def plan_sections(plan: str) -> tuple[dict[str, list[str]], bool]:
    """Read the headings of a plan file outside fenced code blocks with the top-level list
    items (bulleted or numbered) under each, and whether a block is left open (which hides
    everything after it).

    An item runs on through the lines after it up to the next item or heading, nested items
    included. Its lines are joined without a break, so that a field name wrapped across two
    lines is still one name."""
    sections: dict[str, list[str]] = {}
    items: list[str] | None = None
    fenced = False
    for line in plan.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif fenced:
            continue
        elif line.startswith("#"):
            items = sections.setdefault(line.rstrip(), [])
        elif items is None:
            continue
        elif marker := LIST_ITEM.match(line):
            items.append(line[marker.end():].strip())
        elif line.strip():
            # Text before the first item is an item too, so that prose cannot pass as a
            # section without items.
            if items:
                items[-1] += line.strip()
            else:
                items.append(line.strip())
    return sections, fenced


def events_place(plan: str) -> str | None:
    """The `next` a cycle kept in the plan, or None when the plan keeps none."""
    sections, _ = plan_sections(plan)
    for item in sections.get(EVENTS_PLACE, []):
        if item.startswith(NEXT_FIELD):
            return item[len(NEXT_FIELD):].strip() or None
    return None
