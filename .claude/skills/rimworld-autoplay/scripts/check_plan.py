"""Check that a cycle wrote the colony's plan file and left every section in it.

The parent session runs this twice around each cycle, from the main checkout:

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/check_plan.py --colony <name> --start
    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/check_plan.py --colony <name>

--start keeps the time in .claude/play/<colony>/cycle.json, which is also the mark that
tells the watcher a cycle is at work, and copies plan.md to plan.md.prev. A failed check
copies that to plan.md.before-<the cycle's start in UTC> and names it, since the next
--start writes plan.md.prev again. The run after the cycle checks that
.claude/play/<colony>/plan.md was written after that time, and that it has every heading
of level two or below that the code block of rimworld-play's
references/colony-plan-template.md has. The sections are read from the template, not
copied here. Each item of the sections that carry work over to the next cycle must have
the field that says when it is done with (ITEM_FIELDS), so that a cycle can tell when to
remove it; a section without items passes. The sample item the template shows in those
sections fails, since it has its field. What the sections and the fields say is not
checked. The check uses the kept time up and so closes the cycle; a cycle that was not
preceded by --start cannot pass on the time of an earlier one.

--start refuses a mark that is already there, rather than overwrite it: either the
parent stopped in the middle of a cycle, or a second cycle is about to open while one is
at work. Running the check after (without --start) once closes the old mark; a mark that
keeps no time is removed too, and the check then refuses to judge the plan.

It writes one line on standard output, an UNTRUSTED line included, which the parent adds
to the next cycle's prompt. Exit status: 0 when the plan passes (or the time was kept); 1
when the plan was not written, misses a section, has an item without its field or keeps a
sample item; 2 when the check cannot be trusted - the colony name is not usable or has no
directory, a cycle is still open at --start, the time was not kept, the template has no
headings, or the checker failed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import time
import traceback

from play_files import (CYCLE_MARK, PLAN, PLAY_ROOT, REPO_ROOT, MarkUnreadable, colony_name_problem,
                        mark_time, missing_colony, plan_sections)

TEMPLATE = REPO_ROOT / ".claude" / "skills" / "rimworld-play" / "references" / "colony-plan-template.md"
# The plan as it was when the cycle began: the plan is the only memory the cycles share, and
# a cycle that spoils it leaves nothing else to put it back from.
PLAN_BEFORE = "plan.md.prev"
# The field each item of a section must have, named as rimworld-play's template and step 6
# name it. A cycle removes the item when what the field says has come about.
ITEM_FIELDS = {"### 進行中の対応": "終わる条件", "### 前提と根拠": "見直す条件"}
# What the count of items means, said on the line a cycle is handed: a cycle that wrote a
# bullet for each field of one item could not tell from the count alone why it failed.
ONE_ITEM = ("a list entry at the start of a line is one item, with the lines under it; "
            "keep all the fields of an item in that one entry")
# The watcher holds the mark open for about 0.1 ms (measured 2026-09-29) per poll of 1.5 s.
REMOVE_TRIES = 5
REMOVE_WAIT_SECONDS = 0.1


class Untrusted(Exception):
    """The check cannot judge the plan, so its verdict would mean nothing."""


def template_body(template: str) -> str:
    """The plan the template shows: the lines of its markdown code block."""
    body = []
    inside = False
    for line in template.splitlines():
        if line.startswith("```"):
            inside = not inside and line.strip() == "```markdown"
        elif inside:
            body.append(line)
    return "\n".join(body)


def required_headings(template: str) -> list[str]:
    """Read the headings of level two or below in the template's markdown code block."""
    headings = [line.rstrip() for line in template_body(template).splitlines() if line.startswith("##")]
    if not headings:
        raise Untrusted("found no headings in the template's markdown code block")
    return headings


def items_without_fields(sections: dict[str, list[str]]) -> list[str]:
    """Return a problem for each section in ITEM_FIELDS that has items without the field."""
    problems = []
    for heading, field in ITEM_FIELDS.items():
        name = re.compile(re.escape(field) + "[:：]")
        lacking = sum(1 for item in sections.get(heading, []) if not name.search(item))
        if lacking:
            problems.append(f"{PLAN} has {lacking} item(s) without the field {field}: in {heading} ({ONE_ITEM})")
    return problems


def samples_kept(sections: dict[str, list[str]], template: str) -> list[str]:
    """Return a problem for each section in ITEM_FIELDS that still holds the template's
    sample item: the sample has its field, so the field check alone would pass it."""
    samples = plan_sections(template_body(template))[0]
    problems = []
    for heading in ITEM_FIELDS:
        if set(sections.get(heading, [])) & set(samples.get(heading, [])):
            problems.append(f"{PLAN} keeps the template's sample item in {heading}: write the colony's "
                            f"own or remove it")
    return problems


def check(plan: pathlib.Path, template: str, started_at: float) -> list[str]:
    """Return the problems with the plan file after a cycle that began at started_at."""
    required = required_headings(template)
    if not plan.is_file():
        return [f"{PLAN} is missing"]
    problems = []
    if plan.stat().st_mtime <= started_at:
        problems.append(f"{PLAN} was not written during the cycle")
    # utf-8-sig: an editor that saves a byte order mark would hide the first heading behind it.
    sections, unclosed = plan_sections(plan.read_text(encoding="utf-8-sig"))
    if unclosed:
        problems.append(f"{PLAN} has a code block that is not closed")
    missing = [heading for heading in required if heading not in sections]
    if missing:
        problems.append(f"{PLAN} misses the sections {', '.join(missing)}")
    problems.extend(items_without_fields(sections))
    problems.extend(samples_kept(sections, template))
    return problems


def keep_start(colony_dir: pathlib.Path, now: float) -> None:
    """Keep the time in a new mark. FileExistsError when a mark is there already: creating
    only what is not there keeps two parents starting at once from both opening a cycle.

    The watcher reads the mark at any moment and stops on one without a time, so the time
    is written to a draft first and the mark appears whole, as a link to it."""
    mark = colony_dir / CYCLE_MARK
    draft = mark.with_name(f"{CYCLE_MARK}.{os.getpid()}.draft")
    draft.write_text(json.dumps({"started_at": now}) + "\n", encoding="utf-8", newline="")
    try:
        os.link(draft, mark)
    finally:
        draft.unlink()


def remove_mark(mark: pathlib.Path) -> None:
    """Remove the mark. On Windows a file another process holds open cannot be removed, and
    the watcher opens the mark for an instant on each poll, so a refusal is tried again."""
    for attempt in range(REMOVE_TRIES):
        try:
            mark.unlink()
            return
        except PermissionError:
            if attempt == REMOVE_TRIES - 1:
                raise
            time.sleep(REMOVE_WAIT_SECONDS)


def kept_start(colony_dir: pathlib.Path) -> float:
    try:
        return mark_time(colony_dir / CYCLE_MARK)
    except MarkUnreadable as e:
        raise Untrusted(str(e)) from e


def keep_plan_before(colony_dir: pathlib.Path, started_at: float) -> str:
    """Copy the plan as it was before a failed cycle to a name of its own, and say where.

    The next --start writes PLAN_BEFORE again, from the plan the failed cycle left, before
    anyone may have put it right; a copy named for the cycle's start is not written again."""
    stamp = datetime.datetime.fromtimestamp(started_at, datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    kept = f"{PLAN}.before-{stamp}"
    try:
        shutil.copyfile(colony_dir / PLAN_BEFORE, colony_dir / kept)
    except OSError as e:
        return (f"the plan as it was before the cycle is in {PLAN_BEFORE} until the next --start "
                f"(copying it to {kept} failed: {e.strerror or type(e).__name__})")
    return f"the plan as it was before the cycle is in {kept}"


def run(colony_dir: pathlib.Path, start: bool) -> int:
    if not colony_dir.is_dir():
        raise Untrusted(missing_colony(colony_dir))
    mark = colony_dir / CYCLE_MARK
    if start:
        try:
            keep_start(colony_dir, time.time())
        except FileExistsError as e:
            raise Untrusted(f"a cycle is still open ({CYCLE_MARK} is there): the parent stopped in the "
                            f"middle of one, or another is at work. Run the check without --start "
                            f"once to close it") from e
        try:
            if (colony_dir / PLAN).is_file():
                shutil.copyfile(colony_dir / PLAN, colony_dir / PLAN_BEFORE)
            else:
                # A copy from an older cycle would be named as this cycle's.
                (colony_dir / PLAN_BEFORE).unlink(missing_ok=True)
        except OSError as e:
            remove_mark(mark)
            raise Untrusted(f"cannot keep {PLAN} as it is in {PLAN_BEFORE}: {e}") from e
        print(f"started: the check after the cycle compares {PLAN} with this time")
        return 0
    try:
        started_at = kept_start(colony_dir)
    except Untrusted as e:
        if not mark.exists():
            raise
        # A mark that keeps no time would stand for a cycle at work until someone removed it.
        remove_mark(mark)
        raise Untrusted(f"{e}; the mark was removed, so a cycle can open again") from e
    remove_mark(mark)
    problems = check(colony_dir / PLAN, TEMPLATE.read_text(encoding="utf-8"), started_at)
    if problems:
        if (colony_dir / PLAN_BEFORE).is_file():
            problems.append(keep_plan_before(colony_dir, started_at))
        print(f"FAILED: {'; '.join(problems)}")
        return 1
    print(f"OK: {PLAN} was written during the cycle and has every section of the template and "
          f"every field of its items")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--colony", required=True, help="the directory name under .claude/play/")
    parser.add_argument("--start", action="store_true",
                        help="keep the time before waking a cycle, instead of checking")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        if problem := colony_name_problem(args.colony):
            raise Untrusted(problem)
        return run(PLAY_ROOT / args.colony, args.start)
    except Untrusted as e:
        print(f"UNTRUSTED: {e}")
        return 2
    except Exception as e:
        # A crash says nothing about the plan, so it must not read as a failed rule. The
        # parent reads one line, so the trace goes to standard error.
        traceback.print_exc()
        print(f"UNTRUSTED: the checker failed: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
