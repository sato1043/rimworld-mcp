"""Stop a cycle's Write or Edit that is not on the colony's plan file.

The definition of the cycle (.claude/agents/rimworld-cycle.md) runs this as a PreToolUse
hook before Write and Edit. Claude Code gives the tool call as JSON on standard input.

Exit status: 0 lets the call through; 2 stops it, and the line on standard error goes
back to the cycle as the reason. Claude Code lets a call through when a hook ends with any
other status, so whatever goes wrong here - input this cannot read, a tool it was not
meant for, a module that does not load - ends with 2 as well. A hook that cannot be
started at all is stopped by `onFailure: block` in the definition, not by this script.

It uses the standard library only, and so do the modules it loads (write_rules.py and
play_files.py): a hook is not run through the MCP server's environment.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

LET_THROUGH, STOP = 0, 2
# The tools the hook is set on. Another tool is refused rather than passed, so that a
# matcher widened by mistake does not let it through unjudged.
GATED = frozenset({"Write", "Edit"})
# What every reason opens with, and what follows it when the gate judged nothing. The
# definition of the cycle and SKILL.md of this skill name them to say what a reason means;
# test_write_gate.py holds them to it.
REFUSED = "refused:"
BROKEN = "the write gate is broken"
# How much of what went wrong goes into a reason.
SHOWN = 200
# The section of a plan file the player reads (colony-plan-template.md of rimworld-play).
REQUESTS = "利用者に頼むこと"
# What a cycle does after a gate that judged nothing: the plan file is no way on then.
WHEN_BROKEN = ("No file can be written while this lasts, the plan file among them; do not try "
               f"again, and say in the line you return that {BROKEN}.")


class Stopped(NamedTuple):
    """Why a tool call is stopped, and what the cycle does next."""
    reason: str
    next_step: str


def broken(why: object) -> Stopped:
    """The gate judged nothing, and why: on one line and cut short, as write_rules.shown
    does for a path. This stands alone, since the gate says why when that module does not
    load."""
    told = "".join(char if char.isprintable() else " " for char in str(why))
    return Stopped(f"{BROKEN}: {' '.join(told.split())[:SHOWN]}", WHEN_BROKEN)


def step_after(kind: object) -> str:
    """What a cycle does after a path of the given kind (write_rules.Kind) is refused. A
    kind with no step here is a failure of the gate, which main() ends with STOP."""
    from write_rules import Kind

    return {
        Kind.ANOTHER_FILE: (f"Do not write it elsewhere; put what the player has to do under "
                            f"{REQUESTS} in the plan file, and say in the line you return that a "
                            "write was refused."),
        Kind.NO_PLAN_FILE: ("Write nothing; the player makes the plan file. Say in the line you "
                            "return that the colony has no plan file."),
        Kind.UNREADABLE: ("Do not write elsewhere. Name the plan file by its full path if it is "
                          "what you meant; say in the line you return that a write was refused."),
    }[kind]


def decide(payload_text: str) -> Stopped | None:
    """Why the tool call is stopped and what the cycle does next, or None when the call
    is a write of a colony's plan file."""
    # Loaded here and not at the top, so that a module that does not load is caught in
    # main() and ends with STOP like any other failure.
    import json

    from write_rules import refusal

    try:
        payload = json.loads(payload_text)
    except ValueError as e:
        return broken(f"it cannot read the tool call: {e}")
    if not isinstance(payload, dict):
        return broken("it cannot read the tool call: it is not a JSON object")
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or tool not in GATED:
        return broken(f"it judges {', '.join(sorted(GATED))} only, not {tool!r}")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return broken("it cannot read the tool call: it has no tool_input")
    refused = refusal(tool_input.get("file_path"), payload.get("cwd"))
    return None if refused is None else Stopped(refused.reason, step_after(refused.kind))


def main() -> int:
    try:
        # utf-8-sig: a byte-order mark before the JSON is not part of it.
        stopped = decide(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception as e:  # noqa: BLE001 - any other status would let the write through
        stopped = broken(f"it failed: {type(e).__name__}: {e}")
    if stopped is None:
        return LET_THROUGH
    try:
        # A path may hold a colony's name, which a console's own code page may not encode.
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        print(f"{REFUSED} {stopped.reason}. {stopped.next_step}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        # The status below stops the write whether or not the reason could be said; a
        # failure to say it must not turn into a status that lets the write through.
        pass
    return STOP


if __name__ == "__main__":
    sys.exit(main())
