"""The subagent definitions a cycle runs as, and how their frontmatter is read.

The definitions live under .claude/agents/ of the repository. check_cycle_agent.py checks
the tools a definition holds and the hook its writes go through; others read what a
definition says of itself.
"""

from __future__ import annotations

import pathlib
import re

from play_files import REPO_ROOT

AGENTS = REPO_ROOT / ".claude" / "agents"
# The definition every signal wakes: <AGENTS>/<CYCLE_AGENT>.md.
CYCLE_AGENT = "rimworld-cycle"


class AgentUnreadable(ValueError):
    """What a definition says of itself cannot be read."""


def agent_model(name: str, agents: pathlib.Path = AGENTS) -> str:
    """The model the definition of the given name runs a cycle on."""
    try:
        fields = frontmatter((agents / f"{name}.md").read_text(encoding="utf-8"))
    except (OSError, FrontmatterUnreadable) as e:
        raise AgentUnreadable(f"cannot read the definition {name}: {e}") from e
    model = fields.get("model")
    if not isinstance(model, str) or not model:
        raise AgentUnreadable(f"the definition {name} names no model")
    return model

KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(.*)$")
LIST_ITEM = re.compile(r"^ +- +(.*)$")
BLOCK_SCALAR = (">", ">-", "|", "|-")
# The three ends of a line in YAML. str.splitlines() ends a line at more characters than
# these (U+2028 among them), and a line this module ended there would be read on by
# whoever runs the definition.
LINE_END = re.compile(r"\r\n|\r|\n")
# What opens a value in a form of YAML this module does not read: a tag, an anchor, an
# alias, a mapping or a list in braces or brackets, a block scalar with an indicator this
# does not know, a directive, and the two characters YAML keeps for itself.
NOT_PLAIN = "!&*{[|>%@`"
QUOTES = "'\""
# The keys whose value is a nested block. The block is kept as its lines and not read:
# check_cycle_agent.py compares it whole with the block it expects, and a nested form read
# wrongly would pass or fail for the wrong reason. A key added here is given as a string
# whatever is under it, a list of one level too, and nothing looks at what it holds until
# check_cycle_agent.py is given the block to hold it to.
KEPT_AS_LINES = frozenset({"hooks"})


class FrontmatterUnreadable(ValueError):
    """The definition's frontmatter is not in a form this module reads."""


def unreadable(number: int, why: str) -> FrontmatterUnreadable:
    return FrontmatterUnreadable(f"line {number}: the frontmatter is not in a form this module "
                                 f"reads{why and ': ' + why}")


def frontmatter_end(lines: list[str]) -> int:
    """The index of the line that closes the frontmatter."""
    if not lines or lines[0] != "---":
        raise FrontmatterUnreadable("the definition does not open with a frontmatter")
    end = next((i for i in range(1, len(lines)) if "---" in lines[i]), None)
    if end is None:
        raise FrontmatterUnreadable("the frontmatter is not closed")
    if lines[end] != "---":
        # Whoever runs the definition may end the frontmatter here and never see the keys
        # below, which this module would go on to read; or may read on past a line this
        # module would end at (one with spaces around the three hyphens).
        raise FrontmatterUnreadable(f"line {end + 1}: '---' inside a line may be read as the "
                                    "end of the frontmatter")
    return end


def plain(value: str, number: int) -> str:
    """A value as it stands, once it is seen to be one this module reads as YAML does: a
    plain one, or one in quotes that open and close on the line. A quote left open would
    take the lines below into the value for a YAML reader, keys among them."""
    if not value:
        return value
    if value[0] in QUOTES and (len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1]):
        raise unreadable(number, "a value in quotes has to open and close on its line, with "
                                 "no quote of the same kind inside")
    if value[0] in NOT_PLAIN:
        raise unreadable(number, f"a value that opens with {value[0]!r}")
    return value


def frontmatter(text: str) -> dict[str, str | list[str]]:
    """Read the frontmatter of a subagent definition: scalars, block scalars and lists.

    Only the forms a definition needs are read; anything else is refused rather than
    guessed at, since a misread list would pass or fail for the wrong reason. That holds
    for characters too: a space is the only blank read and a line ends where YAML ends
    one, so that a no-break space or a line separator, which Python takes for a blank and
    for the end of a line, does not make this module read other keys than whoever runs the
    definition. The nested block of a key in KEPT_AS_LINES is given as its lines joined by
    newlines, indentation kept, with blank lines and comment lines left out as they are
    everywhere else.
    """
    lines = LINE_END.split(text)
    end = frontmatter_end(lines)
    for number, line in enumerate(lines[:end], start=1):
        if odd := next((char for char in line if not char.isprintable()), None):
            raise unreadable(number, f"U+{ord(odd):04X} is neither a space nor a character "
                                     "that prints")
    fields: dict[str, str | list[str]] = {}
    key = None
    kept_as_lines = False
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if key_match := KEY.match(line):
            key, value = key_match.group(1), key_match.group(2).strip()
            if key in fields:
                raise FrontmatterUnreadable(f"line {number}: '{key}' is given twice")
            kept_as_lines = key in KEPT_AS_LINES and not value
            if kept_as_lines:
                fields[key] = ""
            elif value.startswith("[") and value.endswith("]"):
                fields[key] = [plain(part.strip(), number) for part in value[1:-1].split(",")
                               if part.strip()]
            elif value in BLOCK_SCALAR:
                fields[key] = ""
            else:
                fields[key] = plain(value, number) if value else []
        # Before the two arms below, which would take the lines of a kept block for the
        # items of a list or for a value run on.
        elif kept_as_lines and line.startswith(" "):
            fields[key] = f"{fields[key]}\n{line.rstrip()}" if fields[key] else line.rstrip()
        elif key is not None and isinstance(fields[key], list) and (item := LIST_ITEM.match(line)):
            fields[key].append(plain(item.group(1).strip(), number))
        elif key is not None and isinstance(fields[key], str) and line.startswith(" "):
            fields[key] = (fields[key] + " " + line.strip()).strip()
        else:
            raise unreadable(number, "")
    return fields
