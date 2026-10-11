"""Check that the cycle subagent cannot call the tools that rimworld-play holds back.

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

Run it after changing the definition, the skill or the MCP server's tools:

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/check_cycle_agent.py

Exit status: 0 when every definition grants GRANTED and takes away the listed tools, both
exactly; 1 when one grants or takes away another set, or the skill lists a name that is
not a tool; 2 when the check cannot be trusted - a file is missing, the frontmatter is not
in a form this reads, a list is not found or is empty, or the checker failed. A developer
runs this check, not the parent, so an UNTRUSTED line goes to standard error.
"""

from __future__ import annotations

import argparse
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


def check(skill_md: str, definition: str, tools: dict[str, set[str]]) -> tuple[str, list[str]]:
    """Return a summary of what was compared and the problems found."""
    held_back = held_back_tools(skill_md)
    try:
        fields = frontmatter(definition)
    except FrontmatterUnreadable as e:
        raise Untrusted(str(e)) from e
    disallowed = tool_list(fields.get("disallowedTools", []))
    problems = []
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
    summary = ", ".join(f"{name}: {len(names)}" for name, names in held_back.items())
    return summary, problems


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
    print(f"held back by SKILL.md: {summary}; definitions: {', '.join(definitions)}")
    for problem in problems:
        print(problem)
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        return 1
    print("OK: every definition grants only the tools a cycle holds and takes away every tool "
          "the skill holds back")
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
