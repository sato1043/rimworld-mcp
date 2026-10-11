"""The rules of the usage limit, free of the clock, the files and the network.

The parent session checks the usage before waking each cycle; `usage_verdict` decides
whether it may. In the CLI the usage is read from the record kept of the status line
(`usage_from_record`). The caller passes the time and the readings in.

record_rate_limits.py imports this from the status line, outside the MCP server's
environment, so it uses the standard library alone.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

# Where the usage of a run comes from, as usage_gate.py writes it on each log line: read
# from get_usage, or read in the CLI from the record kept of the status line.
READ = "get_usage"
RECORDED = "statusline"
SOURCES = (READ, RECORDED)


@dataclass(frozen=True)
class UsageWindow:
    """The 5-hour window of the plan limits, as get_usage or the status line gives it."""

    percent_used: float
    resets_at: datetime.datetime


@dataclass(frozen=True)
class UsageVerdict:
    wake: bool
    reason: str


def percent_text(value: float) -> str:
    """A percent as a person reads it: 3 stays 3, and 29.900000000000002 reads 29.9."""
    return f"{value:g}"


def is_percent(value: object) -> bool:
    """Whether a value is a percent used: a number from 0 to 100, which JSON's true is not.

    The one rule for every way a usage comes in. A value below the range would read as
    room under any limit. JSON as Python reads it also has NaN and the infinities, which
    lie in no range.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100


def is_unix_seconds(value: object) -> bool:
    """Whether a value is a reset time as the status line gives it: whole seconds."""
    return isinstance(value, int) and not isinstance(value, bool)


def usage_verdict(five_hour: UsageWindow | None, limit: int) -> UsageVerdict:
    """Whether the parent may wake one more cycle.

    The limit is on the 5-hour window itself, whoever used it: it leaves the rest of the
    window to other work, so what the run added since it started is not what counts. A new
    window is judged by its own value. A usage that cannot be read wakes none: not knowing
    is not the same as having room. Whether the run then waits or stops is the caller's.
    """
    if five_hour is None:
        return UsageVerdict(False, "usage unreadable")
    reason = f"5-hour window: {percent_text(five_hour.percent_used)}% used, the limit is {limit}%"
    return UsageVerdict(five_hour.percent_used < limit, reason)


# How old a line of the status line's record may be and still be read. The recorder writes
# a line at least every five minutes while the status line runs (record_rate_limits.py's
# HEARTBEAT, which has to stay well under this), so a last line older than this means it
# has stopped. It is also how far back an earlier line may give the value: on the live run
# of 2026-10-11 an idle session's value came up to date within 3 minutes. The other side of
# it: a record that stops is still read, at the value it stopped at, for this long. On that
# run the record gained a line every five minutes and the usage rose by 2 in 14 minutes.
RECORD_MAX_AGE = datetime.timedelta(minutes=15)
# The recorder and the check read the same clock, a moment apart: a line may be dated this
# much after the time the check took as now.
CLOCK_SLACK = datetime.timedelta(minutes=1)


# A new 5-hour window resets at least five hours after the one before it; a smaller move
# of the reset time is taken as the same window.
WINDOW_MOVED = datetime.timedelta(hours=1)


def same_window(one: UsageWindow, other: UsageWindow) -> bool:
    """Whether two readings are of one 5-hour window, whose reset time may move a little."""
    return abs(one.resets_at - other.resets_at) < WINDOW_MOVED


@dataclass(frozen=True)
class Recorded:
    """The 5-hour window as the record of the status line gives it, or None and why.

    stalled tells the two kinds of why apart. A record with no line, or whose last line is
    old, dated after now or does not read, is one the status line is not keeping: the
    parent's next response would have mended it. A record whose last line has no current
    window is kept, and waits for the plan to report the new window.
    """

    five_hour: UsageWindow | None
    problem: str | None = None
    stalled: bool = False


class RecorderError(ValueError):
    """The line is one the recorder wrote for an input it could not read."""


def line_reading(line: str) -> tuple[datetime.datetime, UsageWindow | None]:
    """When one line of the record was written and the 5-hour window it holds, if any.

    Raises ValueError for a line that is not a reading: an error line (which has no
    window), one cut short, or one whose values are not what the recorder writes.
    """
    try:
        body = json.loads(line)
        if isinstance(body, dict) and "error" in body:
            raise RecorderError("an error line")
        written = datetime.datetime.fromisoformat(body["time"])
        if written.tzinfo is None:
            raise ValueError("a time without a time zone")
        window = body["five_hour"]
        if window is None:
            return written, None
        percent, resets = window["used_percentage"], window["resets_at"]
        if not is_percent(percent) or not is_unix_seconds(resets):
            raise ValueError("not a window")
        return written, UsageWindow(percent, datetime.datetime.fromtimestamp(resets, datetime.UTC))
    # A reset time out of the clock's range (milliseconds, say) overflows or, on Windows,
    # fails in the C library; either way the line is not a reading.
    except (KeyError, TypeError, OverflowError, OSError) as e:
        raise ValueError(f"not a line of the record: {e}") from e


def why_not_recent(written: datetime.datetime, now: datetime.datetime, max_age: datetime.timedelta) -> str | None:
    """Why a line written at this time is not a reading of now, or None when it is."""
    age = now - written
    if age < -CLOCK_SLACK:
        # Its age cannot be told, so it would never grow old.
        return "dated after now"
    if age > max_age:
        return f"{age.total_seconds() / 60:.0f} minutes old"
    return None


def usage_from_record(lines: list[str], now: datetime.datetime,
                      max_age: datetime.timedelta = RECORD_MAX_AGE) -> Recorded:
    """The 5-hour window now, from the lines record_rate_limits.py wrote, oldest first.

    The last line says whether the record is alive and which window is the current one:
    an error line or one cut short there says the newest input was not read, and a line
    older than max_age means the status line has stopped writing. The status line drops a
    window once its reset time passes, and a window read here past its reset time is
    dropped the same way: the new window's usage is not known until the next response
    brings it.

    The value is the highest any line no older than max_age gives for that window. Every
    session of the checkout writes to the record, and one that is idle writes what it last
    knew under a new time; within a window the usage does not fall, so a lower value on a
    later line is an older one.
    """
    if not lines:
        return Recorded(None, "the record is empty", stalled=True)
    try:
        written, window = line_reading(lines[-1])
    except RecorderError:
        # What the recorder wrote there is not told on: the record lies where others can
        # write, and the parent reads this as the check's own word.
        return Recorded(None, "the last line of the record is an error line: the recorder could not "
                              "read what the status line gave it", stalled=True)
    except ValueError:
        return Recorded(None, "the last line of the record does not read", stalled=True)
    stale = why_not_recent(written, now, max_age)
    if stale is not None:
        return Recorded(None, f"the last line of the record is {stale}", stalled=True)
    if window is None or window.resets_at <= now:
        return Recorded(None, "the record has no current 5-hour window")
    highest = window.percent_used
    for line in lines[:-1]:
        try:
            earlier_written, earlier = line_reading(line)
        except ValueError:
            # Only the last line has to read: an earlier one that does not is passed over.
            continue
        if earlier is None or not same_window(earlier, window):
            continue
        if why_not_recent(earlier_written, now, max_age) is None:
            highest = max(highest, earlier.percent_used)
    return Recorded(UsageWindow(highest, window.resets_at))
