"""Check that the watcher's letter table names every LetterDef of Core, and nothing else.

watch_rules.LETTER_CLASSES decides, letter type by letter type, whether a letter wakes a
cycle. A type missing from it wakes a cycle marked unclassified, which is meant for the
LetterDefs a mod adds, not for Core's. This compares the table with the defName of every
LetterDef that is not abstract in the XML files under the game's Data/Core/Defs. Core
keeps them in Misc/LetterDefs, but the game loads a def from any file under Defs, so the
whole tree is read. A Core name missing from the table and a table name that Core does
not have are both reported; the latter is a misspelt name or one the table's comment
does not allow for.

The game is found the way MCP.csproj finds it: --rimworld-dir, else the RimWorldDir
environment variable, else the GOG location. Give the directory unless the game is there
(on macOS, the directory inside RimWorldMac.app that holds Data):

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/check_letter_table.py --rimworld-dir "<where RimWorld is installed>"

Exit status: 0 when the table and Core name the same LetterDefs; 1 when they differ; 2
when the check cannot be trusted - the directory is missing or holds no XML, a file does
not parse, a LetterDef has no defName, no LetterDef is found, or the checker failed. A
developer runs this check, not the parent, so an UNTRUSTED line goes to standard error.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import traceback
# The files read are the installed game's own Defs, and expat does not fetch external
# entities, so the standard parser is kept rather than adding defusedxml to mcp_server.
import xml.etree.ElementTree as ET

from watch_rules import LETTER_CLASSES

DEFAULT_RIMWORLD_DIR = r"C:\GOG Games\RimWorld"
CORE_DEFS = pathlib.Path("Data", "Core", "Defs")


class Untrusted(Exception):
    """The game's files are not in a shape the check can read, so its verdict would mean nothing."""


def core_letter_defs(directory: pathlib.Path) -> set[str]:
    """Read the defName of every LetterDef that is not abstract in the XML files under the directory."""
    if not directory.is_dir():
        raise Untrusted(f"cannot read {directory}")
    files = sorted(directory.rglob("*.xml"))
    if not files:
        raise Untrusted(f"found no XML files in {directory}")
    names: set[str] = set()
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            raise Untrusted(f"{path.relative_to(directory)}: {e}") from e
        for node in root.findall("LetterDef"):
            if node.get("Abstract", "").lower() == "true":
                continue
            name = (node.findtext("defName") or "").strip()
            if not name:
                raise Untrusted(f"{path.relative_to(directory)}: a LetterDef that is not abstract "
                                "has no defName")
            names.add(name)
    if not names:
        raise Untrusted(f"found no LetterDef in {directory}")
    return names


def check(table: set[str], core: set[str]) -> list[str]:
    problems = [f"the table does not name the Core LetterDef '{name}'"
                for name in sorted(core - table)]
    problems += [f"the table names '{name}', which is not a Core LetterDef"
                 for name in sorted(table - core)]
    return problems


def run(rimworld_dir: pathlib.Path) -> int:
    core = core_letter_defs(rimworld_dir / CORE_DEFS)
    table = set(LETTER_CLASSES)
    print(f"LetterDefs: {len(core)} in Core, {len(table)} in the table")
    problems = check(table, core)
    for problem in problems:
        print(problem)
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        return 1
    print("OK: the table names every Core LetterDef and nothing else")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rimworld-dir", type=pathlib.Path,
                        default=pathlib.Path(os.environ.get("RimWorldDir") or DEFAULT_RIMWORLD_DIR),
                        help="where RimWorld is installed")
    args = parser.parse_args()
    # The messages quote paths, which a console's own code page may not encode.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        return run(args.rimworld_dir)
    except Untrusted as e:
        print(f"UNTRUSTED: {e}", file=sys.stderr)
        return 2
    except Exception:
        # A crash says nothing about the table, so it must not read as a failed rule.
        traceback.print_exc()
        print("UNTRUSTED: the checker failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
