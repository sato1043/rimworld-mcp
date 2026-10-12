"""Check that the definition a cycle runs as holds the tools, the write gate and the keys
a cycle is meant to have, and no other.

The rimworld-play skill names two lists under 判断の原則 in its SKILL.md: the tools that
count as cheating, which need the player's leave, and the tools whose effect cannot be
undone, which need the player's confirmation. A cycle runs while nobody watches, so the
subagent definition a cycle runs as (DEFINITIONS, under .claude/agents/) must take every
one of them away in `disallowedTools`.

The lists are read from SKILL.md, not copied here: a principle is a list item at column 0
that opens with a bold lead, and the tools are the lowercase names in backticks inside
that item. Each name must be a tool in mcp_server/main.py, and the definition must list
it as `mcp__rimworld__<name>`. The server name is the one README.md registers
(`claude mcp add rimworld`); a server registered under another name is not seen.

`disallowedTools` must list those tools and no other, so that a name left behind by a
renamed tool is seen rather than read as a tool taken away.

A subagent inherits every tool it is not denied, the Agent tool among them, and a subagent
it starts is configured apart from it. So the definition must also name in `tools` the
tools a cycle holds, exactly GRANTED: through any other tool (a command, a browser, a
subagent of its own) the cycle could reach the bridge without the MCP tools.

Write and Edit are among the tools a cycle holds, and they reach any file. So the
definition must also run the write gate (write_gate.py) before either: its `hooks` block
has to be WRITE_GATE, line for line. The block is compared whole, not read, so that a hook
taken out, a matcher that leaves a tool out, another script, and a gate that lets the
call through when it cannot be started all fail alike.

What is compared is what cycle_agent.frontmatter reads, and Claude Code reads the file
with a YAML reader of its own. The two are kept from parting in the ways this check knows
of: the frontmatter holds exactly the keys in KEYS (a key this check does not look at,
such as one that sets how permissions are asked, is not let by), and cycle_agent refuses
the characters and the forms of a value the two would read apart. How Claude Code itself
reads a definition is not something this check can see.

Claude Code loads one definition of a name from .claude/agents/ and its folders, and
which one is not said. So no other file there may name the cycle: one that does could be
the definition that runs, with whatever tools and hooks it gives itself.

Run it after changing the definition, the skill or the MCP server's tools, and before a
run is left alone (the rimworld-autoplay skill does):

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/check_cycle_agent.py

Exit status: 0 when every definition holds KEYS, grants GRANTED, takes away the listed
tools and runs the write gate, each exactly, and no other file names the cycle; 1 when one
does not, or the skill lists a name that is not a tool; 2 when the check cannot be trusted
- a file is missing, the frontmatter is not in a form this reads, a list is not found or
is empty, or the checker failed. An UNTRUSTED line goes to standard error.
"""

from __future__ import annotations

import argparse
import itertools
import pathlib
import re
import sys
import traceback

from cycle_agent import AGENTS, CYCLE_AGENT, FrontmatterUnreadable, frontmatter
from play_files import REPO_ROOT
PLAY_SKILL = REPO_ROOT / ".claude" / "skills" / "rimworld-play"
# The definitions a cycle runs as; every signal wakes this one.
DEFINITIONS = (f"{CYCLE_AGENT}.md",)
sys.path.insert(0, str(PLAY_SKILL / "scripts"))

from check_skill import tool_arguments  # noqa: E402

SERVER = "rimworld"
PRINCIPLES = "## 判断の原則"
# The bold lead that opens each principle, and the name this check gives its list.
HELD_BACK = {
    "ズルに当たる tool": "cheating",
    "取り消せない操作": "irreversible",
}
# The tools a cycle holds: the game's tools (the server as a whole, less disallowedTools),
# the files of the policy, ToolSearch to load the game's tools, and SubagentHandback, by
# which a cycle run in the background returns.
GRANTED = frozenset({f"mcp__{SERVER}", "Read", "Write", "Edit", "Glob", "Grep", "ToolSearch",
                     "SubagentHandback"})
# The keys a definition holds, and no other: a key decides what a cycle may do (the mode
# permissions are asked in, the servers it reaches), so one this check does not look at
# is not passed over.
KEYS = frozenset({"name", "description", "skills", "model", "effort", "tools", "disallowedTools",
                  "hooks"})
# All of what is under `hooks:` in a definition, as cycle_agent.frontmatter gives it. The
# hook runs before Write and Edit; `onFailure: block` stops the call when the gate cannot
# be started, ends with a status it does not know or runs out of time, which Claude Code
# lets through unless told otherwise. A definition that is to run another hook as well
# needs this block, the wording of the problem below and the docstring changed together.
WRITE_GATE = """\
  PreToolUse:
    - matcher: "Write|Edit"
      hooks:
        - type: command
          command: python
          args:
            - "${CLAUDE_PROJECT_DIR}/.claude/skills/rimworld-autoplay/scripts/write_gate.py"
          timeout: 10
          onFailure: block"""

LEAD = re.compile(r"^- \*\*([^*]+)\*\*")
BACKTICKED = re.compile(r"`([a-z][a-z0-9_]*)`")


class Untrusted(Exception):
    """The files are not in a shape the check can read, so its verdict would mean nothing."""


def held_back_tools(skill_md: str) -> dict[str, list[str]]:
    """Read the tools each held-back principle of SKILL.md names, by the name of its list."""
    items: list[str] = []
    inside = False
    for line in skill_md.splitlines():
        if line.startswith("## "):
            inside = line.strip() == PRINCIPLES
        elif not inside:
            continue
        elif line.startswith("- "):
            items.append(line)
        elif items and line.startswith(" "):
            items[-1] += "\n" + line
        elif line.strip():
            items.append("")
    found: dict[str, list[str]] = {}
    for item in items:
        lead = LEAD.match(item)
        if not lead:
            continue
        for prefix, name in HELD_BACK.items():
            if lead.group(1).startswith(prefix):
                if name in found:
                    raise Untrusted(f"SKILL.md has two principles opening with '{prefix}'")
                found[name] = BACKTICKED.findall(item)
    for prefix, name in HELD_BACK.items():
        if name not in found:
            raise Untrusted(f"found no principle opening with '**{prefix}' under {PRINCIPLES}")
        if not found[name]:
            raise Untrusted(f"the principle opening with '{prefix}' names no tool")
    return found


def tool_list(value: str | list[str]) -> set[str]:
    """Read a tools field, given as a YAML list or as a comma-separated string."""
    entries = value if isinstance(value, list) else value.split(",")
    return {entry.strip().strip("'\"") for entry in entries if entry.strip()}


def first_difference(hooks: str | list[str]) -> str:
    """Where a `hooks` field that is not WRITE_GATE first parts from it, for the one who
    changed it. The lines are counted in the block, comment and blank lines left out, and
    not in the file."""
    if not isinstance(hooks, str):
        return f"it is the list {hooks!r}, not a block"
    if hooks and not hooks.startswith(" "):
        return f"it is the value {hooks!r} on the line of the key, not a block"
    for number, (line, wanted) in enumerate(
            itertools.zip_longest(hooks.split("\n") if hooks else [], WRITE_GATE.split("\n")),
            start=1):
        if line != wanted:
            found = "nothing" if line is None else repr(line)
            return (f"line {number} of the block is {found}, where "
                    f"{'nothing more' if wanted is None else repr(wanted)} is expected")
    raise ValueError("the hooks field is the write gate")


def check(skill_md: str, definition: str, tools: dict[str, set[str]]) -> tuple[str, list[str]]:
    """Return a summary of what was compared and the problems found."""
    held_back = held_back_tools(skill_md)
    try:
        fields = frontmatter(definition)
    except FrontmatterUnreadable as e:
        raise Untrusted(str(e)) from e
    disallowed = tool_list(fields.get("disallowedTools", []))
    problems = []
    for key in sorted(set(fields) - KEYS):
        problems.append(f"the definition sets {key}, which this check does not look at")
    for key in sorted(KEYS - set(fields) - {"tools", "disallowedTools", "hooks"}):
        problems.append(f"the definition does not set {key}")
    if "name" in fields and fields["name"] != CYCLE_AGENT:
        problems.append(f"the definition is named {fields['name']!r}, not {CYCLE_AGENT!r}")
    taken_away = set()
    for name, names in held_back.items():
        for tool in names:
            if tool not in tools:
                problems.append(f"SKILL.md holds back '{tool}' ({name}), which is not a tool "
                                "in main.py")
            taken_away.add(f"mcp__{SERVER}__{tool}")
            if f"mcp__{SERVER}__{tool}" not in disallowed:
                problems.append(f"disallowedTools does not list mcp__{SERVER}__{tool} ({name})")
    for tool in sorted(disallowed - taken_away):
        problems.append(f"disallowedTools lists {tool}, which SKILL.md does not hold back")
    if "tools" not in fields:
        problems.append("the definition has no tools field, so it inherits every tool")
    else:
        granted = tool_list(fields["tools"])
        for tool in sorted(granted - GRANTED):
            problems.append(f"tools grants {tool}, which a cycle does not hold")
        for tool in sorted(GRANTED - granted):
            problems.append(f"tools does not grant {tool}")
    if "hooks" not in fields:
        problems.append("the definition has no hooks field, so a cycle can write any file")
    elif fields["hooks"] != WRITE_GATE:
        problems.append("hooks is not the write gate (WRITE_GATE in check_cycle_agent.py, held "
                        f"to as text): {first_difference(fields['hooks'])}")
    summary = ", ".join(f"{name}: {len(names)}" for name, names in held_back.items())
    return summary, problems


def others_naming_the_cycle(agents: list[pathlib.Path]) -> list[pathlib.Path]:
    """The files beside the definitions, in their folders and the folders under them, that
    name the cycle anywhere in their text. The text is searched and not read as a
    definition: a file this could not read as one would otherwise go unseen, and Claude
    Code may read it. A name written so that the text does not hold it (an escape inside
    quotes) is not found."""
    given = {agent.resolve() for agent in agents}
    found = []
    for folder in sorted({agent.parent for agent in agents}):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.resolve() not in given:
                try:
                    text = path.read_bytes().decode("utf-8", errors="replace")
                except OSError as e:
                    raise Untrusted(f"cannot read {path}: {e}") from e
                if CYCLE_AGENT in text:
                    found.append(path)
    return found


def run(skill: pathlib.Path, agents: list[pathlib.Path], main_py: pathlib.Path) -> int:
    for path in (skill, *agents, main_py):
        if not path.is_file():
            raise Untrusted(f"cannot read {path}")
    # The definitions are told apart by file name, so two of one name would leave one unread.
    if len({agent.name for agent in agents}) != len(agents):
        raise Untrusted("two definitions given share a file name")
    tools = tool_arguments(main_py)
    if not tools:
        raise Untrusted(f"found no tools in {main_py}")
    skill_md = skill.read_text(encoding="utf-8")
    definitions = {agent.name: agent.read_text(encoding="utf-8") for agent in agents}
    problems = []
    summary = ""
    for name, definition in definitions.items():
        summary, found = check(skill_md, definition, tools)
        problems += [f"{name}: {problem}" for problem in found]
    for other in others_naming_the_cycle(agents):
        problems.append(f"{other} names {CYCLE_AGENT} too: Claude Code loads one definition of "
                        "a name, and it may be that one")
    print(f"held back by SKILL.md: {summary}; definitions: {', '.join(definitions)}")
    for problem in problems:
        print(problem)
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        return 1
    print("OK: every definition holds only the keys and the tools a cycle is meant to have, "
          "takes away every tool the skill holds back and runs the write gate, and no other "
          "file names the cycle")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--skill", type=pathlib.Path, default=PLAY_SKILL / "SKILL.md",
                        help="the SKILL.md that lists the held-back tools")
    parser.add_argument("--agent", type=pathlib.Path, action="append",
                        help="a subagent definition to check, given once for each; "
                             "the definitions a cycle runs as by default")
    parser.add_argument("--main", type=pathlib.Path, default=REPO_ROOT / "mcp_server" / "main.py",
                        help="the MCP server whose tools the skill names")
    args = parser.parse_args()
    # The messages quote SKILL.md, which a console's own code page may not encode.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        return run(args.skill, args.agent or [AGENTS / name for name in DEFINITIONS], args.main)
    except Untrusted as e:
        print(f"UNTRUSTED: {e}", file=sys.stderr)
        return 2
    except Exception:
        # A crash says nothing about the definition, so it must not read as a failed rule.
        traceback.print_exc()
        print("UNTRUSTED: the checker failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
