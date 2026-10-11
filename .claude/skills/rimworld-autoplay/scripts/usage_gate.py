"""Decide before each cycle whether the run still has room in the plan limits, and log
what was read.

The parent session reads the 5-hour window (get_usage in the desktop app) and passes the
numbers here; the decision is usage_rules.usage_verdict, so the parent judges nothing
itself. Run it from the main checkout:

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/usage_gate.py --colony <name> --start --limit 30 --five-hour 3 --five-hour-resets 2026-09-28T15:40:00.102Z --context 284970
    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/usage_gate.py --colony <name> --phase before --reason patrol --agent rimworld-cycle --five-hour 5 --five-hour-resets ... --context 290000
    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/usage_gate.py --colony <name> --phase after --reason patrol --agent rimworld-cycle --five-hour 6 ...

The CLI has no get_usage. There --rate-limits <record> stands in for --five-hour and
--five-hour-resets on every call: the 5-hour window is read from the record
record_rate_limits.py keeps of the status line (usage_rules.usage_from_record), as the
highest value its latest lines give for the window of the last line. A last line that is
old, does not read or has no current window gives no reading, which is waited for and
asked again like get_usage's. A record that is not there cannot be trusted, and neither
can one whose last line is still old or unread after three readings in a row: the status
line is not keeping it.

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/usage_gate.py --colony <name> --phase before --reason patrol --agent rimworld-cycle --rate-limits .claude/rate-limits.jsonl

--start keeps the limit in .claude/play/<colony>/usage.json. The limit is on the 5-hour
window itself, whoever used it, so a start does not begin while the window is already at
the limit (the log keeps the reading as a line of the phase "refused"), and a start again
takes nothing from the one before. Nor does a start begin on a usage.log that does not
read, or while the mark of a cycle (cycle.json) is still there: a run stopped in the
middle of a cycle leaves the mark, and the watcher would take it for a cycle at work and
never wake one. A start that does not begin, at the limit or as one not to be trusted,
removes the limit of an earlier run, so that no later check judges by it.

Every call that goes through appends one JSON line to .claude/play/<colony>/usage.log,
which the metrics are computed from; a line read from the record carries "source":
"statusline". A value that could not be read is left out; a check before a cycle then
wakes none, since not knowing is not the same as having room.

get_usage cannot read the plan for a moment now and then, and asks to be tried again in a
minute, so a check before a cycle that got no reading waits and asks for the usage to be
read again, for as long as it does not read: one minute, two, then four each time. The
check never wakes a cycle without a reading, and get_usage's lack of one never stops the
run; the log keeps how many times in a row it asked.

The script writes one line on standard output, an UNTRUSTED line included, for the parent
to read. Exit status: 0 when a cycle may wake (and for a --start that begins and the phase
after a cycle); 1 when the run must stop, or must not begin, at the limit; 3 when the
usage could not be read and the wait is over - read get_usage again (the record is read
by the check itself) and run the same check; 2 when the check cannot be trusted - the
colony name is not usable or has no directory, --start was not run, a start finds a cycle
still open or lacks the usage, a value does not read, the definition --agent names does
not tell its model, the run mixes get_usage and the record, the status line is not
keeping the record, or the checker failed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time
import traceback
from dataclasses import dataclass

import usage_index
from cycle_agent import CYCLE_AGENT, AgentUnreadable, agent_model
from play_files import CYCLE_MARK, PLAY_ROOT, colony_name_problem, missing_colony, replace_file, user_path
from record_rate_limits import read_tail
from usage_rules import READ, RECORDED, SOURCES, UsageWindow, is_percent, usage_from_record, usage_verdict
from watch_rules import Reason, wakes_cycle

SETTINGS = "usage.json"
LOG = "usage.log"
# The reasons a signal wakes a cycle for; an ended game or an error wakes none.
WAKING_REASONS = tuple(reason.value for reason in Reason if wakes_cycle(reason))
# get_usage asks to be tried again in a minute when it cannot read the plan. On one live run
# every such reading came back within the minute (5 of 22 readings failed); on another the
# plan stayed unread for over three minutes, and giving up there ended the run. So the check
# never gives up. Each reading again costs the parent a turn, so the waits grow; the last one
# is repeated, and is kept short enough that a run is not held long after the plan reads.
READ_AGAIN_WAITS = (60, 120, 240)
# Every source a run reads the usage from, and what the parent does to have a reading
# that failed read again. The status line writes the record when the parent's next
# response arrives, so the parent's running the check again is itself what renews it.
READ_AGAIN_HOW = {READ: "read get_usage again and run this check again",
                  RECORDED: "run this check again, which reads the record again"}
# The record is renewed by the parent's own responses, so one the status line keeps reads
# again by the next check. Once it has not, as many times in a row as there are waits,
# waiting longer brings nothing, and the check is no longer to be trusted. A window that
# has only just reset is still waited for without end, as get_usage is, and such a wait
# is none of those times.
RECORD_READ_AGAIN_LIMIT = len(READ_AGAIN_WAITS)
WAKE, STOP, READ_AGAIN = 0, 1, 3
# How much of the end of the status line's record is read. The check takes the lines no
# older than usage_rules.RECORD_MAX_AGE; a line is about 230 bytes (the live run of
# 2026-10-11), so this holds some 280 of them, which is 18 a minute over that age.
RECORD_TAIL_BYTES = 64 * 1024


class Untrusted(Exception):
    """The check cannot decide, so its verdict would mean nothing."""


@dataclass(frozen=True)
class Settings:
    limit: int
    source: str


@dataclass(frozen=True)
class UsageReading:
    """What the parent read of the 5-hour window and its own context.

    Each is None when unknown; problem says why the record gave no reading, and stalled
    whether that is the status line not keeping it (usage_rules.Recorded).
    """

    five_hour: UsageWindow | None
    context_tokens: int | None
    source: str = READ
    problem: str | None = None
    stalled: bool = False


def parse_time(text: str) -> datetime.datetime:
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError as e:
        raise Untrusted(f"not a time: {text!r}") from e
    if moment.tzinfo is None:
        raise Untrusted(f"the time {text!r} has no time zone")
    return moment


def window_json(window: UsageWindow | None) -> dict | None:
    if window is None:
        return None
    return {"percent_used": window.percent_used, "resets_at": window.resets_at.isoformat()}


def is_limit(value: object) -> bool:
    """Whether a value is a limit: a whole percent, by the rule a usage is a percent by."""
    return isinstance(value, int) and is_percent(value)


def load_settings(colony_dir: pathlib.Path) -> Settings:
    try:
        body = json.loads((colony_dir / SETTINGS).read_text(encoding="utf-8"))
        # The file lies where a cycle can write, so its values are held to what --start
        # writes, and are not told on: the parent reads the line as the check's own word.
        source = body["source"]
        if source not in SOURCES:
            raise ValueError("the source is not one a run reads the usage from")
        limit = body["limit"]
        if not is_limit(limit):
            raise ValueError("the limit is not a whole percentage")
        return Settings(limit, source)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Untrusted(f"cannot read the limit kept by --start in {SETTINGS}: {e}. A run begins with "
                        f"--start, which writes it anew") from e


def save_settings(colony_dir: pathlib.Path, settings: Settings) -> None:
    body = {"limit": settings.limit, "source": settings.source}
    replace_file(colony_dir / SETTINGS, json.dumps(body) + "\n")


def append_log(colony_dir: pathlib.Path, entry: dict) -> None:
    with (colony_dir / LOG).open("a", encoding="utf-8", newline="") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_entry(now: datetime.datetime, phase: str, reading: UsageReading, reason: str | None = None,
              model: str | None = None) -> dict:
    return {"time": now.isoformat(), "phase": phase, "reason": reason, "model": model,
            "source": reading.source, "five_hour": window_json(reading.five_hour),
            "context_tokens": reading.context_tokens}


def stop_line(why: str, window: UsageWindow) -> str:
    """The line of a stop at the limit, with when the window resets.

    A run can start again after that time, and the CLI has no other place to read it from.
    The time is told to the nearest minute, not cut to it: get_usage gives one reset a
    little to either side of its minute (04:49:59.997 and 04:50:00.196 in the live run of
    2026-10-11), and cut, the first of those reads a minute early.
    """
    half_a_minute_on = window.resets_at.astimezone(datetime.UTC) + datetime.timedelta(seconds=30)
    nearest_minute = half_a_minute_on.replace(second=0, microsecond=0)
    return f"STOP: {why}; the window resets at {nearest_minute:%Y-%m-%d %H:%M} UTC"


def start(colony_dir: pathlib.Path, now: datetime.datetime, reading: UsageReading, limit: int) -> tuple[int, str]:
    if (colony_dir / CYCLE_MARK).exists():
        raise Untrusted(f"a cycle is still open ({CYCLE_MARK} is there) from a run stopped in the "
                        f"middle of it. Run check_plan.py once without --start to close it")
    if reading.five_hour is None:
        raise Untrusted("--start needs the 5-hour window's usage"
                        + ("" if reading.problem is None else f": {reading.problem}"))
    if (colony_dir / LOG).exists():
        # Found now rather than in the middle of the run, where the check and the indices read it.
        try:
            usage_index.read_log(colony_dir / LOG)
        except usage_index.Unreadable as e:
            raise Untrusted(f"{e}. Mend or remove {LOG} before starting") from e
    verdict = usage_verdict(reading.five_hour, limit)
    if not verdict.wake:
        # No run began. The limit of an earlier run is not left for a later check to judge
        # by, and the line is not a start's, which the indices would take for a run.
        (colony_dir / SETTINGS).unlink(missing_ok=True)
        append_log(colony_dir, log_entry(now, usage_index.REFUSED, reading) | {
            "limit": limit, "verdict": {"wake": verdict.wake, "reason": verdict.reason}})
        return STOP, f"{stop_line(verdict.reason, reading.five_hour)}; the run does not start"
    save_settings(colony_dir, Settings(limit, reading.source))
    append_log(colony_dir, log_entry(now, "start", reading) | {"limit": limit})
    return WAKE, f"started: {verdict.reason} ({reading.source})"


def times_read_again(colony_dir: pathlib.Path) -> tuple[int, int]:
    """How many checks in a row, at the end of the log, asked for the usage to be read again,
    and how many of them, the latest in a row, found the status line not keeping its record."""
    try:
        lines = (colony_dir / LOG).read_text(encoding="utf-8").splitlines()
        asked = stalled = 0
        for line in reversed(lines):
            if not line:
                # As usage_index.read_log passes over it, which a start held the log to.
                continue
            entry = json.loads(line)
            if entry.get("phase") != "before" or "read_again" not in entry.get("verdict", {}):
                break
            if stalled == asked and entry["verdict"].get("stalled"):
                stalled += 1
            asked += 1
    except (OSError, ValueError, AttributeError) as e:
        raise Untrusted(f"cannot read {LOG} to count the readings asked again: {e}") from e
    return asked, stalled


def before(colony_dir: pathlib.Path, now: datetime.datetime, settings: Settings, reading: UsageReading,
           reason: str, model: str) -> tuple[int, str]:
    verdict = usage_verdict(reading.five_hour, settings.limit)
    why = verdict.reason if reading.problem is None else f"{verdict.reason} ({reading.problem})"
    entry = log_entry(now, "before", reading, reason, model) | {"verdict": {"wake": verdict.wake, "reason": why}}
    if reading.five_hour is None:
        asked, stalled = times_read_again(colony_dir)
        if reading.stalled and stalled >= RECORD_READ_AGAIN_LIMIT:
            raise Untrusted(f"the status line's record gave no reading {stalled} times in a row "
                            f"({reading.problem}): the status line is not keeping it, and reading it "
                            f"again brings none")
        wait = READ_AGAIN_WAITS[min(asked, len(READ_AGAIN_WAITS) - 1)]
        # Logged before the wait: a check cut short while it waits still counts.
        entry["verdict"]["read_again"] = asked + 1
        if reading.stalled:
            # A wait for the plan to report a new window is not one of these, and uses up none.
            entry["verdict"]["stalled"] = True
        append_log(colony_dir, entry)
        time.sleep(wait)
        return READ_AGAIN, (f"READ AGAIN: {why}; waited {wait}s, {READ_AGAIN_HOW[reading.source]} "
                            f"({asked + 1} in a row)")
    append_log(colony_dir, entry)
    if verdict.wake:
        return WAKE, f"WAKE: {why}"
    return STOP, stop_line(why, reading.five_hour)


def after(colony_dir: pathlib.Path, now: datetime.datetime, reading: UsageReading, reason: str,
          model: str) -> str:
    append_log(colony_dir, log_entry(now, "after", reading, reason, model))
    return "logged: the usage after the cycle"


def read_record(record: pathlib.Path, now: datetime.datetime, context: int | None) -> UsageReading:
    """The 5-hour window from the latest lines of the record kept of the status line."""
    # No waiting brings a record that is not there: the status line is not set to keep it.
    if not record.is_file():
        raise Untrusted(f"cannot read the status line's record {record}: there is no such file")
    try:
        tail = read_tail(record, RECORD_TAIL_BYTES).decode("utf-8", errors="replace")
    except OSError as e:
        # The file is there and did not open or read this once, which the next reading may
        # mend: no reading, as for a record that is not kept.
        return UsageReading(None, context, RECORDED,
                            f"the record did not read: {e.strerror or type(e).__name__}", stalled=True)
    # A line the recorder was cut short in has no line end, and is the last line all the same.
    # The first line of the tail may begin partway; it does not read and is passed over.
    # The recorder ends a line with a line feed alone; splitlines would also cut a line at
    # the separators a string inside it may hold.
    lines = [line for line in tail.split("\n") if line.strip()]
    recorded = usage_from_record(lines, now)
    return UsageReading(recorded.five_hour, context, RECORDED, recorded.problem, recorded.stalled)


def reading_from(args: argparse.Namespace, now: datetime.datetime) -> UsageReading:
    """The usage the call gives, or reads from the record."""
    if args.rate_limits is not None:
        if args.five_hour is not None or args.five_hour_resets is not None:
            raise Untrusted("give the usage either by --rate-limits or by --five-hour, not both")
        return read_record(args.rate_limits, now, args.context)
    if (args.five_hour is None) != (args.five_hour_resets is None):
        raise Untrusted("give --five-hour and --five-hour-resets together, or neither")
    five_hour = None
    if args.five_hour is not None:
        five_hour = UsageWindow(args.five_hour, parse_time(args.five_hour_resets))
    return UsageReading(five_hour, args.context)


def run(args: argparse.Namespace, now: datetime.datetime) -> int:
    if problem := colony_name_problem(args.colony):
        raise Untrusted(problem)
    colony_dir = PLAY_ROOT / args.colony
    if not colony_dir.is_dir():
        raise Untrusted(missing_colony(colony_dir))
    if args.start:
        try:
            if args.limit is None:
                raise Untrusted("--start needs --limit")
            code, line = start(colony_dir, now, reading_from(args, now), args.limit)
        except Untrusted:
            # No run began here either: the limit of an earlier run is not left to judge by.
            (colony_dir / SETTINGS).unlink(missing_ok=True)
            raise
        print(line)
        return code
    if args.phase is None or args.reason is None or args.agent is None:
        raise Untrusted("give --start, or --phase with --reason and --agent")
    try:
        model = agent_model(args.agent)
    except AgentUnreadable as e:
        raise Untrusted(str(e)) from e
    settings = load_settings(colony_dir)
    reading = reading_from(args, now)
    if reading.source != settings.source:
        # The desktop app has get_usage and the CLI the record, and a run is in one of them:
        # a call that gives the other was put together wrongly.
        raise Untrusted(f"the run started from {settings.source} but this call gives {reading.source}")
    match args.phase:
        case "before":
            code, line = before(colony_dir, now, settings, reading, args.reason, model)
            print(line)
            return code
        case "after":
            print(after(colony_dir, now, reading, args.reason, model))
            return 0
        case _:
            raise AssertionError(f"a phase argparse lets through: {args.phase!r}")


def percent(text: str) -> int:
    value = int(text)
    if not is_limit(value):
        raise argparse.ArgumentTypeError(f"{value} is not a percentage")
    return value


def percent_used(text: str) -> float:
    """A usage as get_usage gives it, held to the rule the record is read by.

    A whole number stays one, so the log tells it as it was given.
    """
    try:
        value: float = int(text)
    except ValueError:
        value = float(text)
    if not is_percent(value):
        raise argparse.ArgumentTypeError(f"{text} is not a percentage")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--colony", required=True, help="the directory name under .claude/play/")
    parser.add_argument("--start", action="store_true", help="keep the limit, unless the window is at it already")
    parser.add_argument("--limit", type=percent, help="with --start: the percent of the 5-hour window the run stops at")
    parser.add_argument("--phase", choices=("before", "after"), help="before or after a cycle")
    parser.add_argument("--reason", choices=WAKING_REASONS, help="the reason of the signal")
    parser.add_argument("--agent", choices=(CYCLE_AGENT,),
                        help="the definition the signal wakes; the log keeps the model it runs on")
    parser.add_argument("--five-hour", type=percent_used, help="the 5-hour window's percent used")
    parser.add_argument("--five-hour-resets", help="when the 5-hour window resets, in ISO 8601 with a zone")
    parser.add_argument("--rate-limits", type=user_path,
                        help="in the CLI: the record record_rate_limits.py keeps of the status line, "
                             "in place of --five-hour")
    parser.add_argument("--context", type=int, help="the parent session's context tokens used")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        return run(args, datetime.datetime.now(datetime.UTC))
    except Untrusted as e:
        print(f"UNTRUSTED: {e}")
        return 2
    except Exception as e:
        # A crash says nothing about the usage, so it must not read as room or as a stop.
        # The parent reads one line, so the trace goes to standard error.
        traceback.print_exc()
        print(f"UNTRUSTED: the checker failed: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
