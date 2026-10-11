"""Measure what a run of the colony costs of the plan limits, as three indices.

- tokens per percent: how many tokens, weighted by kind, move the 5-hour window by one
  percent, for each model. The parent's usage log (get_usage in the desktop app) gives the
  intervals in which the window moved; the transcripts give the tokens spent in each. The
  kinds are weighted by the ratio of their API prices, and one coefficient per model is
  fitted by least squares. A rate outside RATE_MIN to RATE_MAX is told apart as implausible.
  A fit over fewer intervals than MIN_INTERVALS_PER_MODEL times the models it fits says so
  ("too_few_intervals"): its rates are not to be trusted. The intervals are counted as a
  whole, not for each model apart.
- percent per cycle: the difference the parent logged before and after each cycle, by the
  reason of the signal and the model the cycle ran on.
- percent per hour: how far the 5-hour window moved over the run, per hour of wall clock.

Only lines read from get_usage are used, and the others are counted by source: the
indices are defined on get_usage's values, so a line read from the record of the status
line is not mixed in. The log runs on across runs, so the range starts by default at its last
start line, the start of the last run. A start refused at the limit began no run: its
lines are left out, and those in the range are counted ("starts_refused").

The plan limits are shared by every session of the account. The tokens of the sessions
that are not the run's (--session names the run's) are counted apart, so the write-up of
a run can say how much else ran; what other machines and claude.ai spent is not in these
files at all.

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/usage_index.py --usage-log .claude/play/<colony>/usage.log --transcripts ~/.claude/projects --session <parent session id>

It prints one JSON object, over several lines. Exit status: 0 when the indices were
computed; 2 when an input cannot be read or the script failed, with the JSON object
{"error": ...}.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import datetime
import json
import pathlib
import sys
import traceback
from dataclasses import dataclass, field

from play_files import user_path
from usage_rules import READ, UsageWindow, same_window

KINDS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
# Price of each kind over the base input price (the Claude API's "Pricing", 2026-09-28).
# Output, 5-minute and 1-hour cache writes stand in the same ratio for every model; cache
# reads do not.
KIND_RATIOS = {"input": 1.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "output": 5.0}
CACHE_READ_RATIOS = {"claude-opus-5-5": 0.05, "claude-fable-5-1": 0.025, "claude-mythos-5-1": 0.025}
STANDARD_CACHE_READ_RATIO = 0.1
# The model Claude Code writes for a message no API call produced.
NOT_A_MODEL = "<synthetic>"
# With as many intervals as models the fit is exact whatever the costs are, and its zero
# residual says nothing of how well it fits, so the rates are marked as not to be trusted
# unless the intervals, counted as a whole, number this many times the models of the fit.
MIN_INTERVALS_PER_MODEL = 2
# The weighted tokens per percent a fit may give. The one rate measured on a live run was
# about 2,600,000; two orders of magnitude on either side of a million leave room for other
# models and plans, and tell apart a fit gone wrong by far more.
RATE_MIN, RATE_MAX = 1e4, 1e8
# The phase usage_gate.py logs for a start that did not begin, the window being at the
# limit already. No run is in such a line, so it is no reading of one.
REFUSED = "refused"


class Unreadable(Exception):
    """An input the indices cannot be computed from."""


def cache_read_ratio(model: str) -> float:
    for name, ratio in CACHE_READ_RATIOS.items():
        if model == name or model.startswith(name + "-"):
            return ratio
    return STANDARD_CACHE_READ_RATIO


def weighted(model: str, tokens: dict[str, int]) -> float:
    """The tokens as base input tokens of the same price. Fast mode is a model of its own."""
    base = model.removesuffix(" fast")
    return sum(tokens[kind] * (cache_read_ratio(base) if kind == "cache_read" else KIND_RATIOS[kind])
               for kind in KINDS)


@dataclass
class Message:
    """One API response, whatever number of transcript lines it is written on."""

    time: datetime.datetime
    session: str | None
    model: str
    tokens: dict[str, int]


def kinds_of(usage: dict) -> dict[str, int]:
    split = usage.get("cache_creation")
    if isinstance(split, dict):
        write_5m = split.get("ephemeral_5m_input_tokens") or 0
        write_1h = split.get("ephemeral_1h_input_tokens") or 0
    else:
        write_5m, write_1h = usage.get("cache_creation_input_tokens") or 0, 0
    return {"input": usage.get("input_tokens") or 0, "cache_write_5m": write_5m,
            "cache_write_1h": write_1h, "cache_read": usage.get("cache_read_input_tokens") or 0,
            "output": usage.get("output_tokens") or 0}


@dataclass
class Transcripts:
    messages: list[Message]
    files: int
    unreadable_lines: int
    # Files removed between finding and reading them, as Claude Code's clean-up does.
    files_gone: int = 0


def read_transcripts(roots: list[pathlib.Path], since: datetime.datetime) -> Transcripts:
    """Every API response in the transcripts under the roots, subagents' included.

    A response is written on several lines with the same message id: one per block of
    content, the output tokens counted so far on each. A resumed session copies earlier
    lines into its own file with the usage set to nothing. So each kind is the largest
    any line of the message gives.
    """
    found: dict[str, Message] = {}
    files = unreadable = gone = 0
    for root in roots:
        if not root.is_dir():
            raise Unreadable(f"not a directory of transcripts: {root}")
        for path in sorted(root.rglob("*.jsonl")):
            try:
                # A file last written before the range holds nothing in it.
                if datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.UTC) < since:
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except FileNotFoundError:
                gone += 1
                continue
            except OSError as e:
                # Passing over a file would count its tokens as unspent, which reads as room. Only the
                # file's name goes out: its directory names another project.
                raise Unreadable(f"cannot read the transcript {path.name}: {e.strerror or type(e).__name__}") from e
            files += 1
            for line in lines:
                try:
                    entry = json.loads(line)
                    message = entry.get("message")
                    if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                        continue
                    time = datetime.datetime.fromisoformat(entry["timestamp"])
                    if time.tzinfo is None:
                        raise ValueError("a time without a time zone")
                    model, key = message["model"], message["id"]
                except (ValueError, KeyError, TypeError, AttributeError):
                    unreadable += 1
                    continue
                if model == NOT_A_MODEL:
                    continue
                usage = message["usage"]
                if usage.get("speed") == "fast":
                    model += " fast"
                tokens = kinds_of(usage)
                session = entry.get("sessionId")
                kept = found.get(key)
                if kept is None:
                    found[key] = Message(time, session, model, tokens)
                    continue
                # The session is the one whose line carries the usage, not a copy's.
                if sum(tokens.values()) > sum(kept.tokens.values()):
                    kept.session = session
                kept.time = min(kept.time, time)
                kept.tokens = {kind: max(kept.tokens[kind], tokens[kind]) for kind in KINDS}
    return Transcripts(sorted(found.values(), key=lambda m: m.time), files, unreadable, gone)


def solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when the system has no single answer."""
    n = len(vector)
    rows = [matrix[i][:] + [vector[i]] for i in range(n)]
    scale = max((abs(x) for row in matrix for x in row), default=0.0)
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) <= scale * 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col])]
    return [rows[i][n] / rows[i][i] for i in range(n)]


@dataclass
class Interval:
    start: datetime.datetime
    end: datetime.datetime
    percent: float
    weighted: dict[str, float] = field(default_factory=dict)


@dataclass
class LogIntervals:
    """The intervals to fit, and what of the log was not used, so a thin fit shows."""

    intervals: list[Interval]
    dropped: dict[str, int]


def log_intervals(entries: list[dict], since: datetime.datetime,
                  until: datetime.datetime) -> LogIntervals:
    """The intervals between one change of the 5-hour window and the next, where it rose.

    A value is first logged right after the tokens that brought it were spent, so the
    tokens that moved the window from one value to the next are those after the first line
    of the one and up to the first line of the other. An interval across a new window, or
    across a line where the usage was not read, is not used. Nor is one that starts where
    the value was not seen to change - the first line, the first after a line not read, the
    first of a new window: the usage reads as a whole percent, so such a start may lie
    anywhere in its percent, and the rise to the next may be far less than it reads.
    """
    # Each change keeps whether the value was seen to change there.
    changes: list[tuple[datetime.datetime, UsageWindow, bool] | None] = []
    for entry in entries:
        window = entry["window"]
        last = changes[-1] if changes else None
        if window is None:
            if last is not None:
                changes.append(None)
            continue
        same = last is not None and same_window(window, last[1])
        if last is None or not same or last[1].percent_used != window.percent_used:
            changes.append((entry["time"], window, same))
    intervals = []
    dropped: collections.Counter[str] = collections.Counter()
    for before, after in zip(changes, changes[1:]):
        if before is None or after is None:
            if before is not None or after is not None:
                dropped["the usage was not read"] += 1
            continue
        (start, old, seen_to_change), (end, new, _) = before, after
        if start < since or end > until:
            dropped["outside the range"] += 1
        elif not same_window(new, old):
            dropped["a new 5-hour window opened"] += 1
        elif new.percent_used < old.percent_used:
            dropped["the window fell"] += 1
        elif not seen_to_change:
            dropped["the value was not seen to change at its start"] += 1
        else:
            intervals.append(Interval(start, end, new.percent_used - old.percent_used))
    return LogIntervals(intervals, dict(sorted(dropped.items())))


def tokens_per_percent(intervals: list[Interval], messages: list[Message]) -> dict:
    """Fit one cost per model to the intervals; messages are sorted by time."""
    times = [message.time for message in messages]
    for interval in intervals:
        sums: dict[str, float] = collections.defaultdict(float)
        inside = messages[bisect.bisect_right(times, interval.start):bisect.bisect_right(times, interval.end)]
        for message in inside:
            sums[message.model] += weighted(message.model, message.tokens)
        interval.weighted = dict(sums)
    models = sorted({model for interval in intervals for model in interval.weighted})
    result: dict = {"intervals": len(intervals), "models": {}, "undetermined": [], "implausible": {}}
    if not models:
        return result
    # Fit percent = sum over models of c[model] * weighted tokens, in millions of tokens.
    rows = [[interval.weighted.get(model, 0.0) / 1e6 for model in models] for interval in intervals]
    ys = [interval.percent for interval in intervals]
    normal = [[sum(row[i] * row[j] for row in rows) for j in range(len(models))] for i in range(len(models))]
    target = [sum(row[i] * y for row, y in zip(rows, ys)) for i in range(len(models))]
    # Fewer intervals than models leave the normal matrix singular, which solve reports.
    coefficients = solve(normal, target)
    if coefficients is None:
        result["undetermined"] = models
        return result
    residuals = [y - sum(c * x for c, x in zip(coefficients, row)) for row, y in zip(rows, ys)]
    result["residual_rms"] = (sum(r * r for r in residuals) / len(residuals)) ** 0.5
    for model, c in zip(models, coefficients):
        if c > 0 and RATE_MIN <= 1e6 / c <= RATE_MAX:
            result["models"][model] = {"weighted_tokens_per_percent": 1e6 / c}
        else:
            if c > 0:
                result["implausible"][model] = 1e6 / c
            result["undetermined"].append(model)
    # A model the fit did not determine still took a coefficient of it, so it counts.
    needed = MIN_INTERVALS_PER_MODEL * len(models)
    if result["models"] and len(intervals) < needed:
        result["too_few_intervals"] = (f"{len(intervals)} intervals for {len(models)} models; "
                                       f"at least {needed} are needed to trust the rates")
    return result


def log_window(entry: dict) -> UsageWindow | None:
    body = entry.get("five_hour")
    if not isinstance(body, dict):
        return None
    return UsageWindow(body["percent_used"], datetime.datetime.fromisoformat(body["resets_at"]))


def read_log(path: pathlib.Path) -> list[dict]:
    """The lines of the usage log, each with its time and its window as values.

    What a line holds is not told on when it does not read, only which line it is: the log
    lies where a cycle can write, and the parent reads the line of a start that refuses it
    as the check's own word.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as e:
        why = e.strerror if isinstance(e, OSError) and e.strerror else type(e).__name__
        raise Unreadable(f"cannot read the usage log {path}: {why}") from e
    entries = []
    for number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry["time"] = datetime.datetime.fromisoformat(entry["time"])
            entry["window"] = log_window(entry)
        except (ValueError, KeyError, TypeError) as e:
            raise Unreadable(f"cannot read the usage log {path}: line {number} is not one the check "
                             f"wrote ({type(e).__name__})") from e
        entries.append(entry)
    return entries


def percent_per_cycle(entries: list[dict]) -> dict:
    """The usage a cycle took, from the check before it woke to the log after it returned."""
    groups: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    skipped = []
    woken = None
    for entry in entries:
        if entry["phase"] == "before":
            woken = entry if entry.get("verdict", {}).get("wake") else None
            continue
        if entry["phase"] != "after" or woken is None:
            continue
        before, woken = woken, None
        cycle = (entry["reason"], entry["model"])
        if cycle != (before["reason"], before["model"]):
            skipped.append({"time": entry["time"].isoformat(), "why": "the check before names another cycle"})
        elif before["window"] is None or entry["window"] is None:
            skipped.append({"time": entry["time"].isoformat(), "why": "the usage was not read"})
        elif not same_window(entry["window"], before["window"]):
            skipped.append({"time": entry["time"].isoformat(), "why": "a new 5-hour window opened"})
        else:
            groups[cycle].append(entry["window"].percent_used - before["window"].percent_used)
    cycles = [{"reason": reason, "model": model, "cycles": len(values), "percent_total": sum(values),
               "percent_mean": sum(values) / len(values)} for (reason, model), values in sorted(groups.items())]
    return {"cycles": cycles, "skipped": skipped}


def percent_per_hour(entries: list[dict]) -> dict:
    """How far the 5-hour window moved over the logged run, per hour of wall clock.

    When a new window opens, only its own usage is counted: what the old one took after
    the last reading is not known, so the sum is a lower bound then.
    """
    read = [entry for entry in entries if entry["window"] is not None]
    if len(read) < 2:
        return {"hours": 0.0, "percent": 0.0, "percent_per_hour": None, "new_windows": 0}
    percent, new_windows = 0.0, 0
    for before, after in zip(read, read[1:]):
        if not same_window(after["window"], before["window"]):
            percent += after["window"].percent_used
            new_windows += 1
        else:
            percent += after["window"].percent_used - before["window"].percent_used
    hours = (read[-1]["time"] - read[0]["time"]).total_seconds() / 3600
    return {"hours": hours, "percent": percent, "percent_per_hour": percent / hours if hours else None,
            "new_windows": new_windows}


def mixing(messages: list[Message], sessions: set[str], since: datetime.datetime,
           until: datetime.datetime) -> dict:
    own: dict[str, float] = collections.defaultdict(float)
    other: dict[str, float] = collections.defaultdict(float)
    others: dict[str, float] = collections.defaultdict(float)
    for message in messages:
        if not since <= message.time <= until:
            continue
        amount = weighted(message.model, message.tokens)
        if message.session in sessions:
            own[message.model] += amount
        else:
            other[message.model] += amount
            others[str(message.session)] += amount
    return {"own_weighted_tokens": dict(own), "other_weighted_tokens": dict(other),
            "other_sessions": dict(sorted(others.items()))}


def indices(log: list[dict], transcripts: Transcripts, sessions: set[str], since: datetime.datetime,
            until: datetime.datetime) -> dict:
    # The indices are defined on get_usage's readings, so the lines read from the record
    # of the status line, like those of a source this does not know, are counted apart
    # and not mixed in.
    measured = [entry for entry in log if entry.get("source") == READ]
    in_range = [entry for entry in measured if since <= entry["time"] <= until]
    left_out = collections.Counter(str(entry.get("source")) for entry in log
                                   if since <= entry["time"] <= until and entry.get("source") != READ)
    # The intervals are found over the whole log: cut at the range, an interval that began
    # before it would start at its first line and miss the tokens spent before.
    found = log_intervals(measured, since, until)
    return {
        "range": {"since": since.isoformat(), "until": until.isoformat()},
        "transcripts": {"files": transcripts.files, "files_gone": transcripts.files_gone,
                        "messages": len(transcripts.messages),
                        "unreadable_lines": transcripts.unreadable_lines},
        "lines_left_out": dict(sorted(left_out.items())),
        "tokens_per_percent": tokens_per_percent(found.intervals, transcripts.messages)
                              | {"intervals_dropped": found.dropped},
        "percent_per_cycle": percent_per_cycle(in_range),
        "percent_per_hour": percent_per_hour(in_range),
        # Without the run's sessions, every token would read as another session's.
        "mixing": mixing(transcripts.messages, sessions, since, until) if sessions else None,
    }


def time_arg(text: str) -> datetime.datetime:
    moment = datetime.datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(f"the time {text!r} has no time zone")
    return moment


def run(args: argparse.Namespace) -> dict:
    whole = read_log(args.usage_log)
    # A start that was refused is no line of a run: it would read as usage of the run
    # before it, and as the end of that run's range.
    log = [entry for entry in whole if entry.get("phase") != REFUSED]
    if not log and (args.since is None or args.until is None):
        raise Unreadable("the usage log has no line of a run; give --since and --until")
    # The log runs on across runs; by default the range is the last run, from its start.
    starts = [entry["time"] for entry in log if entry.get("phase") == "start"]
    since = args.since if args.since is not None else (starts[-1] if starts else log[0]["time"])
    until = args.until if args.until is not None else log[-1]["time"]
    transcripts = read_transcripts(args.transcripts, since)
    refused = sum(1 for entry in whole if entry.get("phase") == REFUSED and since <= entry["time"] <= until)
    return indices(log, transcripts, set(args.session), since, until) | {"starts_refused": refused}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--usage-log", required=True, type=user_path,
                        help="the usage.log usage_gate.py keeps for the colony")
    parser.add_argument("--transcripts", required=True, type=user_path, action="append",
                        help="a directory the transcripts are found under (~/.claude/projects)")
    parser.add_argument("--session", action="append", default=[],
                        help="the id of a session of the run (the parent's; its subagents share it); "
                             "without it, the tokens are not told apart by session")
    parser.add_argument("--since", type=time_arg, help="the start of the range; by default the log's last start line, else its first line")
    parser.add_argument("--until", type=time_arg, help="the end of the range; the log's last line by default")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
    except (Unreadable, OSError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    except Exception as e:
        # A crash says nothing about the usage, so it must not read as a result. The
        # trace goes to standard error, and the one line says the indices failed.
        traceback.print_exc()
        print(json.dumps({"error": f"the indices failed: {type(e).__name__}: {e}"}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
