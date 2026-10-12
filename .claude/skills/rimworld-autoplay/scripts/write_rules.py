"""Which file a cycle may write, decided from the path and from where it leads.

A cycle runs while nobody watches, and it holds Write and Edit to keep the colony's plan
file. Those two tools reach any file, the ways a session is run among them: settings and
hooks, the scripts of this skill, the definition of the cycle itself, and the state the
parent keeps next to the plan file (the limit of the run, the mark of a cycle, the
watcher's place). write_gate.py asks this module before either tool runs.

The rule is an equality, not a place to be under: the path is spelled as a plan file and,
once resolved, is <play root>/<colony>/plan.md, a file that is already there, and nothing
else. A list of what to refuse could not name every file ahead of time, while the one file
a cycle writes can be named.

The file system is read, to follow links and to see that the plan file is there; nothing
is written. A path that its spelling already rules out is refused before the file system
is asked, so that a path on another machine is not looked up to be refused.
"""

from __future__ import annotations

import enum
import pathlib
from typing import NamedTuple

from play_files import PLAN, PLAY_ROOT, colony_name_problem

# How much of a path or of an error goes into a reason.
SHOWN = 200
# What a reason opens with, by kind. SKILL.md of this skill tells the kinds apart by these
# words, and they come before the path: a cycle hands on the head of a reason only, and a
# path may hold any words.
NOT_A_PLAN_FILE = "not a plan file"
NOT_THERE = "no plan file there"
UNJUDGED = "cannot judge the path"


class Kind(enum.Enum):
    """What a refused path is; what a cycle does next differs by it (write_gate.step_after)."""
    ANOTHER_FILE = "another file"
    NO_PLAN_FILE = "a plan file that is not there"
    UNREADABLE = "a path that cannot be judged"


class Refusal(NamedTuple):
    """Why a cycle may not write a path."""
    reason: str
    kind: Kind


def shown(text: str) -> str:
    """A path or a message as it goes into a reason: in quotes, on one line, and cut short,
    so that what a cycle put into the path does not read as a line of the reason."""
    clipped = text if len(text) <= SHOWN else f"{text[:SHOWN]}..."
    return '"' + "".join(char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
                         for char in clipped) + '"'


def same_name(name: str, other: str) -> bool:
    """Whether two names of a file or of a drive are one where this runs: case is folded on
    Windows and kept elsewhere. The one rule for every comparison of this module."""
    return pathlib.PurePath(name) == pathlib.PurePath(other)


def refusal(path_text: object, cwd: object, play_root: pathlib.Path = PLAY_ROOT) -> Refusal | None:
    """Why a cycle may not write the path, or None when it is a colony's plan file.

    A relative path is taken from cwd, the directory the tool call was made in. The last
    part of the path has to be spelled as the plan file's name: another spelling Windows
    opens as the same file (a dot or a space at the end, a stream) is refused. The path is
    then judged where it leads: `..` and links (junctions among them) are followed, so that
    another spelling of a refused file is refused and a link out of the colony's directory
    is not taken for the plan file. A cycle keeps a plan file the player has made and makes
    none, so the file has to be there."""
    if not isinstance(path_text, str) or not path_text or "\0" in path_text:
        return Refusal(f"{UNJUDGED}: the tool call names none this can read", Kind.UNREADABLE)
    path = pathlib.Path(path_text)
    if not path.is_absolute():
        # A directory that is itself relative would be taken from wherever the hook runs.
        if not isinstance(cwd, str) or not pathlib.Path(cwd).is_absolute():
            return Refusal(f"{UNJUDGED}: {shown(path_text)} is a relative path, and the "
                           "directory it is taken from is not known", Kind.UNREADABLE)
        path = pathlib.Path(cwd) / path
        if not path.is_absolute():
            # A path that names a drive and no place on it (C:plan.md), from a directory on
            # another drive: Windows takes it from where the hook runs.
            return Refusal(f"{UNJUDGED}: {shown(path_text)} names a drive other than the one "
                           "it is taken from, and no place on it", Kind.UNREADABLE)
    another_file = Refusal(f"{NOT_A_PLAN_FILE}: {shown(path_text)}. A cycle writes the colony's "
                           f"plan file only (.claude/play/<colony>/{PLAN})", Kind.ANOTHER_FILE)
    # A share of another machine and a device (a drive that opens with two backslashes on
    # Windows) are not asked where they lead: asking would reach them. The share the
    # colonies themselves are on, if they are on one, is the only one looked at.
    if path.drive.startswith("\\\\") and not same_name(path.drive, play_root.drive):
        return another_file
    if not same_name(path.name, PLAN):
        return another_file
    try:
        resolved = path.resolve(strict=False)
        root = play_root.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as e:
        return Refusal(f"{UNJUDGED}: where {shown(path_text)} leads cannot be told: "
                       f"{shown(str(e))}", Kind.UNREADABLE)
    colony_dir = resolved.parent
    if (colony_dir.parent != root or not same_name(resolved.name, PLAN)
            or colony_name_problem(colony_dir.name) is not None):
        return another_file
    if not resolved.is_file():
        return Refusal(f"{NOT_THERE}: {shown(path_text)}. A cycle makes no plan file",
                       Kind.NO_PLAN_FILE)
    return None
