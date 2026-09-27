"""Check the rimworld-play skill against the rules its files state.

Three checks:

- Every entry in the strategy files (references/basics.md, references/advanced.md) has
  one source line and one confidence line, in the form SKILL.md states. An entry is a
  list item at column 0 and must start with "- "; a list item indented by one to three
  spaces where no entry is open is reported. Its children are "  - 出典: ..." and
  "  - 確度: ...", each of which may continue on lines indented by four spaces.
  - A source is one or more of 実機（YYYY-MM-DD・Mod なし|あり）, Defs（`<path>`…）
    whose backticked paths, joined by "・", each name an .xml file or a directory ending
    in "/" and may be followed by a note, a RimWorld Wiki URL, or 推論（...）, joined
    by "、".
  - A confidence is 高, 中 or 低, optionally followed by a note in full-width
    parentheses. An entry whose only sources are Wiki URLs cannot be 高.
- Every lowercase name written in backticks in the skill's markdown is a tool or an
  argument in mcp_server/main.py, or one of the answer fields listed in RESPONSE_FIELDS.
  A call such as `set_pause(paused=true)` must name a tool, and its argument names must
  be arguments of that tool; a lone `name=value` must name an argument of some tool.
- Every answer field in RESPONSE_FIELDS is used by the skill, and appears either as a
  string in main.py or as a member of an object initializer (`new { name = ... }`) in the
  mod's C# sources; a local variable of that name does not count. This catches a
  field that was renamed or dropped on both sides of the list, not one that merely moved
  to another answer.

Tools are the functions at the top level of main.py decorated with `@<server>.tool` or
`@<server>.tool(...)`; a `name=` given to the decorator is the tool's name. Tools
registered by calling `add_tool` are not seen.

Run it after changing the skill or the MCP server's tools:

    uv run --project mcp_server python .claude/skills/rimworld-play/scripts/check_skill.py

Exit status: 0 when every check passes; 1 when an entry or a name breaks the rules; 2 when
the check itself cannot be trusted - a file is missing or unreadable, a code fence is not
closed, the parsing found no entries or no names, or the checker failed.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
import traceback

SKILL_DIR = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[2]
STRATEGY_FILES = ("references/basics.md", "references/advanced.md")
REQUIRED_FILES = ("SKILL.md", *STRATEGY_FILES)

LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)]) ")
INDENTED_ITEM = re.compile(r"^ {1,3}(?:[-*+]|\d+[.)]) ")
CHILD = re.compile(r"^  - (出典|確度): (.*)$")
CONTINUATION = "    "
CONFIDENCES = ("高", "中", "低")
CONFIDENCE = re.compile(r"^(高|中|低)(?:（[^（）]*）)?$")
DEFS_PATH = r"`[^`（）\s]+(?:\.xml|/)`"
WIKI_URL = re.compile(r"^https://rimworldwiki\.com/\S+$")
SOURCE_FORMS = (
    re.compile(r"^実機（\d{4}-\d{2}-\d{2}・Mod (?:なし|あり)）$"),
    re.compile(rf"^Defs（{DEFS_PATH}(?:・{DEFS_PATH})*[^（）]*）$"),
    WIKI_URL,
    re.compile(r"^推論（.+）$"),
)
# A member of an object initializer (`new { name = ... }`): it follows "{" or ",", and a
# "," or "}" comes before any ";". A local (`var name = ...;`) or a statement that assigns
# to it does not match; a statement that opens a block and has a "," before its ";"
# (`{ name = Call(a, b); }`) still does.
CSHARP_MEMBER = r"[{{,]\s*\b{name}\s*=(?!=)[^;]*?[,}}]"

BACKTICKED = re.compile(r"`([^`\n]+)`")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
CALL = re.compile(r"^([a-z][a-z0-9_]*)\((.*)\)$")
ARGUMENT = re.compile(r"([a-z][a-z0-9_]*)\s*=")
ASSIGNMENT = re.compile(r"^([a-z][a-z0-9_]*)=\S+$")

# Fields of the tools' answers that the skill names. They are not tools or arguments,
# so the tools cannot vouch for them; check_fields looks for each in main.py and in
# the mod's sources instead.
RESPONSE_FIELDS = frozenset({
    "alerts", "colonists", "error", "gap", "id", "messages", "more", "next", "reloaded",
    "rotation", "stuff", "threats", "type",
})


class Untrusted(Exception):
    """The files are not in a shape the check can read, so its verdict would mean nothing."""


def tool_arguments(main_py: pathlib.Path) -> dict[str, set[str]]:
    """Map each tool registered in main.py to the names of its arguments."""
    tree = ast.parse(main_py.read_text(encoding="utf-8"))
    tools: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if not (isinstance(target, ast.Attribute) and target.attr == "tool"):
                continue
            name = node.name
            if isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                        name = keyword.value.value
            arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            tools[name] = {a.arg for a in arguments if a.arg != "ctx"}
    return tools


def lines_outside_fences(path: pathlib.Path) -> list[tuple[int, str]]:
    """Number the lines of a markdown file, leaving out fenced code blocks."""
    kept = []
    fenced_at = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith("```"):
            fenced_at = 0 if fenced_at else number
            continue
        if not fenced_at:
            kept.append((number, line))
    if fenced_at:
        raise Untrusted(f"{where(path, fenced_at)}: the code fence opened here is not closed")
    return kept


def where(path: pathlib.Path, number: int) -> str:
    return f"{path.relative_to(SKILL_DIR).as_posix()}:{number}"


def split_sources(text: str) -> list[str]:
    """Split a source line at the "、" that stand outside full-width parentheses."""
    parts, depth, current = [], 0, ""
    for char in text:
        depth += {"（": 1, "）": -1}.get(char, 0)
        if char == "、" and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return parts


def check_entry(at: str, children: dict[str, list[str]]) -> list[str]:
    problems = []
    for label in ("出典", "確度"):
        if len(children.get(label, [])) != 1:
            problems.append(f"{at}: the entry needs exactly one {label} line")
    if problems:
        return problems
    sources = split_sources(children["出典"][0])
    for source in sources:
        if not any(form.match(source) for form in SOURCE_FORMS):
            problems.append(f"{at}: '{source}' is not a source form SKILL.md allows")
    confidence = children["確度"][0]
    if not CONFIDENCE.match(confidence):
        problems.append(f"{at}: the confidence must be one of {'/'.join(CONFIDENCES)}, "
                        "optionally followed by a note in （）")
    elif confidence.startswith("高") and all(WIKI_URL.match(s) for s in sources):
        problems.append(f"{at}: an entry sourced only from the Wiki cannot be 高")
    return problems


def check_entries(path: pathlib.Path) -> tuple[int, list[str]]:
    """Return the number of entries in a strategy file and the problems found in them."""
    entries: list[tuple[int, dict[str, list[str]]]] = []
    problems = []
    current: dict[str, list[str]] | None = None
    last: list[str] | None = None
    for number, line in lines_outside_fences(path):
        if line.startswith("#"):
            current = last = None
        elif LIST_ITEM.match(line):
            if not line.startswith("- "):
                problems.append(f"{where(path, number)}: start the entry with '- '")
            current = {}
            last = None
            entries.append((number, current))
        elif current is None and INDENTED_ITEM.match(line):
            # Markdown still shows it as a list item, so it must not pass unchecked. Its
            # children go to a dict that is not counted, so the problem is reported once.
            problems.append(f"{where(path, number)}: start the entry at column 0")
            current = {}
            last = None
        elif current is not None and (child := CHILD.match(line)):
            last = current.setdefault(child.group(1), [])
            last.append(child.group(2))
        elif line.startswith("  - "):
            last = None
        elif current is not None and last is not None and line.startswith(CONTINUATION):
            last[-1] += line.strip()
    for number, children in entries:
        problems += check_entry(where(path, number), children)
    return len(entries), problems


def check_names(path: pathlib.Path, tools: dict[str, set[str]],
                used_fields: set[str]) -> tuple[int, list[str]]:
    """Return the number of names a markdown file refers to and the problems with them."""
    arguments = set().union(*tools.values())
    problems = []
    count = 0
    for number, line in lines_outside_fences(path):
        at = where(path, number)
        for token in BACKTICKED.findall(line):
            if call := CALL.match(token):
                tool = call.group(1)
                count += 1
                if tool not in tools:
                    problems.append(f"{at}: '{tool}' is not a tool in main.py")
                    continue
                for argument in ARGUMENT.findall(call.group(2)):
                    count += 1
                    if argument not in tools[tool]:
                        problems.append(f"{at}: '{argument}' is not an argument of {tool}")
            elif assignment := ASSIGNMENT.match(token):
                count += 1
                if assignment.group(1) not in arguments:
                    problems.append(f"{at}: '{assignment.group(1)}' is not an argument of any tool")
            elif NAME.match(token):
                count += 1
                if token in RESPONSE_FIELDS:
                    used_fields.add(token)
                elif token not in tools and token not in arguments:
                    problems.append(f"{at}: '{token}' is not a tool, an argument, or a listed "
                                    "answer field (an answer field goes in RESPONSE_FIELDS in "
                                    "scripts/check_skill.py)")
    return count, problems


def check_fields(main_py: pathlib.Path, mod_sources: list[pathlib.Path],
                 used_fields: set[str]) -> list[str]:
    """Check that each listed answer field is used by the skill and named by the code."""
    strings = {node.value for node in ast.walk(ast.parse(main_py.read_text(encoding="utf-8")))
               if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    csharp = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in mod_sources)
    problems = []
    for field in sorted(RESPONSE_FIELDS):
        if field not in used_fields:
            problems.append(f"RESPONSE_FIELDS lists '{field}', which the skill does not name")
        member = CSHARP_MEMBER.format(name=re.escape(field))
        if field not in strings and not re.search(member, csharp):
            problems.append(f"RESPONSE_FIELDS lists '{field}', which neither main.py nor the "
                            "mod's sources name")
    return problems


def run(main_py: pathlib.Path) -> int:
    for relative in REQUIRED_FILES:
        if not (SKILL_DIR / relative).is_file():
            raise Untrusted(f"cannot read {relative}")
    if not main_py.is_file():
        raise Untrusted(f"cannot read {main_py}")
    tools = tool_arguments(main_py)
    if not tools:
        raise Untrusted(f"found no tools in {main_py}")
    mod_sources = sorted((REPO_ROOT / "MCP" / "Source").rglob("*.cs"))
    if not mod_sources:
        raise Untrusted("found no C# sources under MCP/Source")

    problems: list[str] = []
    for relative in STRATEGY_FILES:
        count, found = check_entries(SKILL_DIR / relative)
        print(f"entries: {relative}: {count}")
        if count == 0:
            raise Untrusted(f"found no entries in {relative}")
        problems += found

    used_fields: set[str] = set()
    name_count = 0
    for path in sorted(SKILL_DIR.rglob("*.md")):
        count, found = check_names(path, tools, used_fields)
        name_count += count
        problems += found
    print(f"names: {name_count} in the skill's markdown, against {len(tools)} tools in main.py")
    if name_count == 0:
        raise Untrusted("found no names in the skill's markdown")
    problems += check_fields(main_py, mod_sources, used_fields)

    for problem in problems:
        print(problem)
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        return 1
    print("OK: every entry and name follows the rules")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--main", type=pathlib.Path, default=REPO_ROOT / "mcp_server" / "main.py",
                        help="the MCP server whose tools the skill names")
    args = parser.parse_args()
    try:
        return run(args.main)
    except Untrusted as e:
        print(f"UNTRUSTED: {e}", file=sys.stderr)
        return 2
    except Exception:
        # A crash says nothing about the skill, so it must not read as a failed rule.
        traceback.print_exc()
        print("UNTRUSTED: the checker failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
