"""The subagent definitions a cycle runs as, and how their frontmatter is read.

The definitions live under .claude/agents/ of the repository. check_cycle_agent.py checks
the tools a definition holds; others read what a definition says of itself.
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
LIST_ITEM = re.compile(r"^\s+-\s+(.*)$")
BLOCK_SCALAR = (">", ">-", "|", "|-")


class FrontmatterUnreadable(ValueError):
    """The definition's frontmatter is not in a form this module reads."""


def frontmatter_end(lines: list[str]) -> int:
    """The index of the line that closes the frontmatter."""
    if not lines or lines[0].strip() != "---":
        raise FrontmatterUnreadable("the definition does not open with a frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise FrontmatterUnreadable("the frontmatter is not closed")
    return end


def frontmatter(text: str) -> dict[str, str | list[str]]:
    """Read the frontmatter of a subagent definition: scalars, block scalars and lists.

    Only the forms a definition needs are read; anything else is refused rather than
    guessed at, since a misread list would pass or fail for the wrong reason.
    """
    lines = text.splitlines()
    end = frontmatter_end(lines)
    fields: dict[str, str | list[str]] = {}
    key = None
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if key_match := KEY.match(line):
            key, value = key_match.group(1), key_match.group(2).strip()
            if key in fields:
                raise FrontmatterUnreadable(f"line {number}: '{key}' is given twice")
            if value.startswith("[") and value.endswith("]"):
                fields[key] = [part.strip() for part in value[1:-1].split(",") if part.strip()]
            elif value in BLOCK_SCALAR:
                fields[key] = ""
            else:
                fields[key] = value if value else []
        elif key is not None and isinstance(fields[key], list) and (item := LIST_ITEM.match(line)):
            fields[key].append(item.group(1).strip())
        elif key is not None and isinstance(fields[key], str) and line.startswith(" "):
            fields[key] = (fields[key] + " " + line.strip()).strip()
        else:
            raise FrontmatterUnreadable(f"line {number}: the frontmatter is not in a form this "
                                        f"module reads")
    return fields
