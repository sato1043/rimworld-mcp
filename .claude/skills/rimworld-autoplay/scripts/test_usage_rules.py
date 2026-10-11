"""Tests of the usage limit's rules. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import datetime
import json

import pytest

from usage_rules import Recorded, UsageVerdict, UsageWindow, is_percent, usage_from_record, usage_verdict


# ── Usage ──────────────────────────────────────────────────────────────────────

T0 = datetime.datetime(2026, 9, 28, 10, 40, tzinfo=datetime.UTC)


@pytest.mark.parametrize("used, wake", [(24, True), (25, False), (26, False)])
def test_the_limit_is_on_the_5_hour_window_itself(used, wake):
    assert usage_verdict(UsageWindow(used, T0), 25).wake is wake


def test_an_unreadable_usage_wakes_no_cycle():
    assert usage_verdict(None, 25) == UsageVerdict(False, "usage unreadable")


@pytest.mark.parametrize("value, percent", [
    (0, True), (100, True), (23.5, True), (-0.1, False), (100.1, False), (-5, False), (150, False),
    (float("nan"), False), (float("inf"), False), (float("-inf"), False),
    (True, False), ("23", False), (None, False),
], ids=repr)
def test_a_percent_used_is_a_number_from_0_to_100(value, percent):
    assert is_percent(value) is percent


@pytest.mark.parametrize("used, wake, reason", [
    (24.9, True, "5-hour window: 24.9% used, the limit is 25%"),
    (25.0, False, "5-hour window: 25% used, the limit is 25%"),
])
def test_fractions_of_a_percent_are_judged_and_told(used, wake, reason):
    assert usage_verdict(UsageWindow(used, T0), 25) == UsageVerdict(wake, reason)


# ── The status line's record ───────────────────────────────────────────────────

NOW = datetime.datetime(2026, 9, 28, 18, 0, tzinfo=datetime.UTC)
RESETS_AT = NOW + datetime.timedelta(hours=2)


def record_line(minutes_ago: float = 1, five: object = 23.5, resets: object = int(RESETS_AT.timestamp()),
                **changed) -> str:
    time = (NOW - datetime.timedelta(minutes=minutes_ago)).isoformat()
    window = None if five is None else {"used_percentage": five, "resets_at": resets}
    return json.dumps({"time": time, "session_id": "s1", "five_hour": window, "seven_day": None} | changed)


def test_the_last_line_of_the_record_gives_the_window():
    assert usage_from_record([record_line()], NOW) == Recorded(UsageWindow(23.5, RESETS_AT))


def test_the_record_passes_through_to_the_verdict():
    recorded = usage_from_record([record_line(five=30)], NOW)
    assert usage_verdict(recorded.five_hour, 30) == UsageVerdict(False, "5-hour window: 30% used, the limit is 30%")


@pytest.mark.parametrize("minutes_ago, problem", [
    (15, None), (15.5, "the last line of the record is 16 minutes old"),
])
def test_a_line_too_old_is_not_the_usage_now(minutes_ago, problem):
    recorded = usage_from_record([record_line(minutes_ago)], NOW)
    assert ((recorded.five_hour is None), recorded.problem) == (problem is not None, problem)


@pytest.mark.parametrize("minutes_ago, problem", [
    (-1, None), (-1.5, "the last line of the record is dated after now"),
])
def test_a_line_dated_after_now_is_not_the_usage_now(minutes_ago, problem):
    recorded = usage_from_record([record_line(minutes_ago)], NOW)
    assert ((recorded.five_hour is None), recorded.problem) == (problem is not None, problem)


def test_a_record_without_a_line_gives_no_reading():
    assert usage_from_record([], NOW) == Recorded(None, "the record is empty", stalled=True)


ERROR_LINE = '{"time": "2026-09-28T17:59:00+00:00", "error": "the input is not a JSON object"}'


def test_an_error_line_at_the_end_is_told_as_one_without_what_it_holds():
    recorded = usage_from_record([ERROR_LINE], NOW)
    assert recorded == Recorded(None, "the last line of the record is an error line: the recorder could not "
                                      "read what the status line gave it", stalled=True)
    assert "not a JSON object" not in recorded.problem


@pytest.mark.parametrize("line", [
    "{not json",
    "[1, 2]",
    record_line(time="2026-09-28T17:59:00"),
    record_line(time="soon"),
    record_line(five="23"),
    record_line(five=True),
    # Below the range a value would read as room under any limit.
    record_line(five=-5),
    record_line(five=float("-inf")),
    record_line(five=150),
    record_line(five=float("nan")),
    record_line(resets="2026-09-28"),
    record_line(resets=1790600400.5),
    # Milliseconds or microseconds for seconds: out of the clock's range. Which error
    # the clock gives for it differs by platform, and both are taken as a line not read.
    record_line(resets=1790600400000),
    record_line(resets=1790600400000000),
    json.dumps({"time": "2026-09-28T17:59:00+00:00", "seven_day": None}),
    json.dumps({"time": "2026-09-28T17:59:00+00:00", "five_hour": [23.5, 1790600400]}),
], ids=["not json", "a list", "a time without a zone", "a time that is none", "a percent as text",
        "a percent that is true", "a percent below 0", "a percent of -inf", "a percent over 100",
        "a percent of nan", "a reset as a date", "a reset with a fraction", "a reset in milliseconds",
        "a reset in microseconds", "no five_hour", "five_hour as a list"])
def test_a_last_line_that_does_not_read_gives_no_reading(line):
    assert usage_from_record([line], NOW) == Recorded(None, "the last line of the record does not read",
                                                      stalled=True)


@pytest.mark.parametrize("resets, readable", [
    (NOW + datetime.timedelta(seconds=1), True), (NOW, False), (NOW - datetime.timedelta(minutes=5), False),
])
def test_a_window_past_its_reset_time_is_dropped(resets, readable):
    recorded = usage_from_record([record_line(resets=int(resets.timestamp()))], NOW)
    assert ((recorded.five_hour is not None), recorded.problem) == (
        readable, None if readable else "the record has no current 5-hour window")


def test_a_window_the_status_line_dropped_gives_no_reading():
    assert usage_from_record([record_line(five=None)], NOW) == Recorded(
        None, "the record has no current 5-hour window")


# ── The latest lines of the record ─────────────────────────────────────────────

def test_a_lower_value_on_the_last_line_is_an_older_one():
    # An idle session wrote what it last knew, under a new time, after a session that knew more.
    lines = [record_line(3, five=29), record_line(2, five=30), record_line(1, five=29)]
    assert usage_from_record(lines, NOW) == Recorded(UsageWindow(30, RESETS_AT))


def test_a_lower_value_on_an_earlier_line_changes_nothing():
    assert usage_from_record([record_line(2, five=10), record_line(1, five=29)], NOW) == Recorded(
        UsageWindow(29, RESETS_AT))


def test_the_reset_time_told_is_the_last_line_s():
    # A reset time that moved by less than a new window would is the same window.
    earlier = record_line(2, five=30, resets=int(RESETS_AT.timestamp()) + 1)
    assert usage_from_record([earlier, record_line(1, five=29)], NOW) == Recorded(UsageWindow(30, RESETS_AT))


@pytest.mark.parametrize("earlier, taken", [
    (record_line(15, five=40), True),
    (record_line(15.5, five=40), False),
    (record_line(-1, five=40), True),
    (record_line(-1.5, five=40), False),
    # The window before this one, whose usage was higher when it ended.
    (record_line(2, five=40, resets=int((RESETS_AT - datetime.timedelta(hours=5)).timestamp())), False),
    (record_line(2, five=40, resets=int((RESETS_AT - datetime.timedelta(minutes=59)).timestamp())), True),
    (record_line(2, five=40, resets=int((RESETS_AT - datetime.timedelta(hours=1)).timestamp())), False),
    (record_line(2, five=None), False),
    (record_line(2, five="40"), False),
    # No percent: taken, it would stand as the highest for as long as the line is recent.
    (record_line(2, five=150), False),
    (record_line(2, five=float("inf")), False),
    ("{not json", False),
    ('{"time": "2026-09-28T17:58:00+00:00", "error": "the input is not a JSON object"}', False),
], ids=["at the age a line may have", "older than that", "dated a little after now", "dated well after now",
        "the window before", "a reset moved by under an hour", "a reset moved by an hour", "no window",
        "a percent as text", "a percent over 100", "a percent of inf", "not json", "an error line"])
def test_an_earlier_line_counts_only_if_it_is_a_recent_reading_of_the_same_window(earlier, taken):
    recorded = usage_from_record([earlier, record_line(1, five=29)], NOW)
    assert recorded == Recorded(UsageWindow(40 if taken else 29, RESETS_AT))


@pytest.mark.parametrize("last, problem, stalled", [
    ("{not json", "the last line of the record does not read", True),
    (record_line(-1.5, five=29), "the last line of the record is dated after now", True),
    (record_line(16, five=29), "the last line of the record is 16 minutes old", True),
    # The status line is keeping the record: the plan has not reported the new window yet.
    (record_line(1, five=None), "the record has no current 5-hour window", False),
    (record_line(1, five=29, resets=int(NOW.timestamp())), "the record has no current 5-hour window", False),
], ids=["not json", "dated after now", "old", "no window", "a window at its reset"])
def test_the_last_line_alone_says_whether_the_record_is_alive(last, problem, stalled):
    # A good line before it does not stand in: the newest input is what was not read.
    assert usage_from_record([record_line(2, five=30), last], NOW) == Recorded(None, problem, stalled)
