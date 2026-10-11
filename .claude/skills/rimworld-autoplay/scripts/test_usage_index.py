"""Tests of the usage indices, on a usage log and transcripts whose answers are set first.

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts

The answers: one percent of the 5-hour window is 1,000,000 weighted tokens of Opus 5.5 and
4,000,000 of Sonnet 5. The parent session runs Opus; its cycles run as subagents on
Sonnet; another session on the machine spends Opus in the same hours.
"""

from __future__ import annotations

import datetime
import json

import pytest

import play_files
import usage_index

T0 = datetime.datetime(2026, 1, 5, 9, 0, tzinfo=datetime.UTC)
RESETS = T0 + datetime.timedelta(hours=4)
PARENT, OTHER = "parent-session", "other-session"
OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5"


def at(minutes: float) -> datetime.datetime:
    return T0 + datetime.timedelta(minutes=minutes)


def assistant(message_id: str, minutes: float, model: str, session: str, sidechain: bool = False,
              input_: int = 0, write_5m: int = 0, write_1h: int = 0, read: int = 0, output: int = 0,
              speed: str = "standard") -> dict:
    usage = {"input_tokens": input_, "cache_creation_input_tokens": write_5m + write_1h,
             "cache_read_input_tokens": read, "output_tokens": output, "speed": speed,
             "cache_creation": {"ephemeral_5m_input_tokens": write_5m, "ephemeral_1h_input_tokens": write_1h}}
    return {"type": "assistant", "timestamp": at(minutes).isoformat().replace("+00:00", "Z"),
            "sessionId": session, "isSidechain": sidechain,
            "message": {"id": message_id, "model": model, "role": "assistant", "usage": usage}}


def write_jsonl(path, entries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8", newline="")


def log_entry(minutes: float, phase: str, five: float | None, reason: str | None = None,
              model: str | None = None, wake: bool | None = None, resets: datetime.datetime = RESETS,
              source: str = "get_usage") -> dict:
    entry = {"time": at(minutes).isoformat(), "phase": phase, "reason": reason, "model": model, "source": source,
             "five_hour": None if five is None else {"percent_used": five, "resets_at": resets.isoformat()},
             "context_tokens": 1000}
    if wake is not None:
        entry["verdict"] = {"wake": wake, "reason": "…"}
    return entry


@pytest.fixture
def world(tmp_path):
    """The transcripts and the usage log of a two-hour run."""
    projects = tmp_path / "projects"
    project = projects / "C--repo"
    # Interval 1 (0, 20]: the parent spends 2,000,000 weighted Opus tokens -> 2%, in two
    #   responses on either side of the log line at 10 minutes that repeats the value. The second is
    #   100,000 input + 50,000 1-hour writes x2 + 8,000,000 cache reads x0.05 + 80,000 output x5
    #   = 100,000 + 100,000 + 400,000 + 400,000. It is written on three lines: two with the
    #   output counted so far, and a copy set to nothing by a resumed session. The last line
    #   falls past the interval's end; the response counts from its first.
    parent_lines = [
        assistant("m0", 5, OPUS, PARENT, input_=1_000_000),
        assistant("m1", 19.99, OPUS, PARENT, input_=100_000, write_1h=50_000, read=8_000_000, output=3),
        assistant("m1", 20.01, OPUS, PARENT, input_=100_000, write_1h=50_000, read=8_000_000, output=80_000),
        {"type": "assistant", "timestamp": at(6).isoformat(), "sessionId": PARENT,
         "message": {"id": "s0", "model": "<synthetic>", "usage": {"input_tokens": 9_000_000}}},
        {"type": "user", "timestamp": at(6).isoformat(), "message": {"role": "user", "content": "x"}},
    ]
    write_jsonl(project / f"{PARENT}.jsonl", parent_lines)
    # Found before the parent's file, so the copy must not make the response another session's.
    write_jsonl(project / "a-resumed.jsonl", [assistant("m1", 19.99, OPUS, "resumed")])
    # Interval 2 (20, 40]: a cycle spends 4,000,000 weighted Sonnet tokens -> 1%.
    #   1,000,000 input + 800,000 5-minute writes x1.25 + 10,000,000 reads x0.1 + 200,000 output x5
    # Interval 3 (40, 60]: a cycle spends 8,000,000 weighted Sonnet (2%) while the other
    #   session spends 1,000,000 weighted Opus (1%): 1,000,000 input.
    write_jsonl(project / PARENT / "subagents" / "agent-a1.jsonl", [
        assistant("c1", 30, SONNET, PARENT, True, input_=1_000_000, write_5m=800_000, read=10_000_000,
                  output=200_000),
        assistant("c2", 50, SONNET, PARENT, True, input_=2_000_000, write_5m=1_600_000, read=20_000_000,
                  output=400_000),
    ])
    write_jsonl(projects / "C--elsewhere" / f"{OTHER}.jsonl", [
        assistant("o1", 45, OPUS, OTHER, input_=1_000_000),
    ])
    log = tmp_path / "usage.log"
    write_jsonl(log, [
        # An earlier run, which the range leaves out by default. The value is seen to change
        # from it at 0, so the first interval of this run starts at a change.
        log_entry(-2, "start", 9.0),
        log_entry(0, "start", 10.0),
        # The value stays, so the interval does not start here.
        log_entry(10, "before", 10.0, "patrol", "sonnet", wake=True),
        log_entry(20, "after", 12.0, "patrol", "sonnet"),
        log_entry(25, "before", 12.0, "urgent", "opus", wake=True),
        log_entry(40, "after", 13.0, "urgent", "opus"),
        log_entry(45, "before", 13.0, "patrol", "sonnet", wake=True),
        log_entry(60, "after", 16.0, "patrol", "sonnet"),
        # A fall is not an interval to fit, and is counted as dropped.
        log_entry(70, "before", 15.0, "patrol", "sonnet", wake=False),
        # A line read from the status line's record must not feed the fit or the other indices.
        log_entry(90, "before", 99.0, "patrol", "sonnet", wake=True, source="statusline"),
        log_entry(100, "after", 0.5, "patrol", "sonnet", source="statusline"),
        log_entry(120, "before", 15.0, "patrol", "sonnet", wake=True),
    ])
    return projects, log


@pytest.fixture
def world_after_a_fall(world):
    """The run of world with a fourth interval, which starts where the value fell.

    Interval 4 (70, 130]: a cycle spends 4,000,000 weighted Sonnet tokens -> 1%. The value 15
    was first logged at 70, so the interval starts there.
    """
    projects, log = world
    agent = projects / "C--repo" / PARENT / "subagents" / "agent-a1.jsonl"
    with agent.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(assistant("c3", 125, SONNET, PARENT, True, input_=4_000_000)) + "\n")
    with log.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(log_entry(130, "after", 16.0, "patrol", "sonnet")) + "\n")
    return projects, log


def compute(capsys, world, *extra: str) -> tuple[int, dict]:
    projects, log = world
    code = usage_index.main(["--usage-log", str(log), "--transcripts", str(projects), "--session", PARENT,
                             *extra])
    return code, json.loads(capsys.readouterr().out)


def test_tokens_per_percent_come_out_as_set(capsys, world):
    code, result = compute(capsys, world)
    assert code == 0
    fitted = result["tokens_per_percent"]
    assert fitted["intervals"] == 3
    assert fitted["undetermined"] == []
    assert fitted["models"][OPUS]["weighted_tokens_per_percent"] == pytest.approx(1_000_000)
    assert fitted["models"][SONNET]["weighted_tokens_per_percent"] == pytest.approx(4_000_000)
    assert fitted["residual_rms"] == pytest.approx(0, abs=1e-9)
    # Three intervals for two models: the fit comes out, marked as not to be trusted.
    assert fitted["too_few_intervals"] == "3 intervals for 2 models; at least 4 are needed to trust the rates"


def test_percent_per_cycle_is_grouped_by_reason_and_model(capsys, world):
    _, result = compute(capsys, world)
    assert result["percent_per_cycle"] == {"cycles": [
        {"reason": "patrol", "model": "sonnet", "cycles": 2, "percent_total": 5.0, "percent_mean": 2.5},
        {"reason": "urgent", "model": "opus", "cycles": 1, "percent_total": 1.0, "percent_mean": 1.0},
    ], "skipped": []}


def test_percent_per_hour_divides_the_rise_by_the_wall_clock(capsys, world):
    _, result = compute(capsys, world)
    assert result["percent_per_hour"] == {"hours": 2.0, "percent": 5.0, "percent_per_hour": 2.5,
                                          "new_windows": 0}


def test_only_lines_read_from_get_usage_are_used_and_the_others_are_counted(capsys, world):
    projects, log = world
    with log.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(log_entry(110, "before", 50.0, "patrol", "sonnet", wake=True, source="guess")) + "\n")
        f.write(json.dumps({k: v for k, v in log_entry(115, "after", 60.0, "patrol", "sonnet").items()
                            if k != "source"}) + "\n")
    _, result = compute(capsys, world)
    assert result["lines_left_out"] == {"None": 1, "guess": 1, "statusline": 2}
    assert result["percent_per_hour"]["percent"] == 5.0


def refused_start(minutes: float, five: float) -> dict:
    """The line usage_gate.py logs for a start that did not begin."""
    return log_entry(minutes, usage_index.REFUSED, five) | {"limit": 30, "verdict": {"wake": False, "reason": "…"}}


def test_a_start_that_was_refused_does_not_end_the_range_of_the_run_before_it(capsys, world):
    _, log = world
    with log.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(refused_start(125, 99.0)) + "\n")
    _, result = compute(capsys, world)
    assert result["range"]["until"] == at(120).isoformat()
    assert result["starts_refused"] == 0


def test_a_start_that_was_refused_is_counted_and_is_no_reading_of_the_run(capsys, world):
    _, log = world
    with log.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(refused_start(125, 99.0)) + "\n")
    _, result = compute(capsys, world, "--until", at(130).isoformat())
    assert result["starts_refused"] == 1
    # Read as a line of the run, it would add the rise from 15 to 99.
    assert result["percent_per_hour"]["percent"] == 5.0


def test_a_log_of_refused_starts_alone_has_no_run_to_measure(capsys, world, tmp_path):
    projects, _ = world
    log = tmp_path / "refused.log"
    write_jsonl(log, [refused_start(0, 99.0)])
    code = usage_index.main(["--usage-log", str(log), "--transcripts", str(projects)])
    assert code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error": "the usage log has no line of a run; give --since and --until"}


def test_the_range_starts_at_the_last_start_by_default(capsys, world):
    _, result = compute(capsys, world)
    assert result["range"]["since"] == at(0).isoformat()
    assert result["tokens_per_percent"]["intervals_dropped"]["outside the range"] == 1


def test_the_range_starts_at_the_first_line_of_a_log_without_a_start(capsys, world):
    _, log = world
    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text("".join(line + "\n" for line in lines if '"phase": "start"' not in line),
                   encoding="utf-8", newline="")
    _, result = compute(capsys, world)
    assert result["range"]["since"] == at(10).isoformat()


def test_an_interval_that_starts_where_the_value_fell_is_fitted(capsys, world_after_a_fall):
    code, result = compute(capsys, world_after_a_fall)
    assert code == 0
    fitted = result["tokens_per_percent"]
    assert (fitted["intervals"], result["range"]["until"]) == (4, at(130).isoformat())
    # Two intervals for each of the two models: enough to trust the rates.
    assert "too_few_intervals" not in fitted
    assert fitted["models"][OPUS]["weighted_tokens_per_percent"] == pytest.approx(1_000_000)
    assert fitted["models"][SONNET]["weighted_tokens_per_percent"] == pytest.approx(4_000_000)


def test_without_the_run_s_sessions_the_mixing_is_not_told(capsys, world):
    projects, log = world
    code = usage_index.main(["--usage-log", str(log), "--transcripts", str(projects)])
    result = json.loads(capsys.readouterr().out)
    assert (code, result["mixing"]) == (0, None)
    assert result["tokens_per_percent"]["intervals"] == 3


def test_a_home_directory_in_a_path_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert play_files.user_path("~/projects") == tmp_path / "projects"


def test_the_other_sessions_tokens_are_counted_apart(capsys, world):
    _, result = compute(capsys, world)
    mixing = result["mixing"]
    assert mixing["own_weighted_tokens"] == pytest.approx({OPUS: 2_000_000, SONNET: 12_000_000})
    assert mixing["other_weighted_tokens"] == pytest.approx({OPUS: 1_000_000})
    assert mixing["other_sessions"] == pytest.approx({OTHER: 1_000_000})


def test_the_transcripts_read_are_told(capsys, world):
    _, result = compute(capsys, world)
    assert result["transcripts"] == {"files": 4, "files_gone": 0, "messages": 5, "unreadable_lines": 0}
    # The earlier run's interval is outside the range, which starts at the last start.
    assert result["tokens_per_percent"]["intervals_dropped"] == {"outside the range": 1, "the window fell": 1}


def test_a_transcript_removed_while_reading_is_counted(tmp_path, monkeypatch):
    real = tmp_path / "p" / "s.jsonl"
    write_jsonl(real, [assistant("a1", 5, OPUS, PARENT, input_=10)])
    gone = tmp_path / "p" / "swept.jsonl"
    monkeypatch.setattr(type(real), "rglob", lambda self, pattern: iter([gone, real]))
    found = usage_index.read_transcripts([tmp_path / "p"], T0 - datetime.timedelta(days=1))
    assert (found.files, found.files_gone, len(found.messages)) == (1, 1, 1)


def test_the_range_leaves_out_what_is_outside_it(capsys, world):
    _, result = compute(capsys, world, "--since", at(15).isoformat(), "--until", at(48).isoformat())
    assert result["tokens_per_percent"]["intervals"] == 1
    assert result["percent_per_cycle"]["cycles"] == [
        {"reason": "urgent", "model": "opus", "cycles": 1, "percent_total": 1.0, "percent_mean": 1.0}]
    assert result["mixing"]["own_weighted_tokens"] == pytest.approx({OPUS: 1_000_000, SONNET: 4_000_000})


def test_an_interval_begun_before_the_range_is_not_cut_at_its_edge(capsys, world):
    # The window rose from 12 to 13 over (20, 40]; from 25 on only part of it is seen.
    _, result = compute(capsys, world, "--since", at(25).isoformat(), "--until", at(48).isoformat())
    assert result["tokens_per_percent"]["intervals"] == 0
    assert result["tokens_per_percent"]["intervals_dropped"] == {"outside the range": 5}


def test_a_fit_with_fewer_intervals_than_models_is_undetermined():
    intervals = [usage_index.Interval(at(0), at(10), 1.0)]
    messages = [usage_index.Message(at(5), PARENT, OPUS, {"input": 10, "cache_write_5m": 0,
                                                            "cache_write_1h": 0, "cache_read": 0, "output": 0}),
                usage_index.Message(at(6), PARENT, SONNET, {"input": 10, "cache_write_5m": 0,
                                                              "cache_write_1h": 0, "cache_read": 0, "output": 0})]
    result = usage_index.tokens_per_percent(intervals, messages)
    assert result["undetermined"] == [OPUS, SONNET]
    assert result["models"] == {}


def reading(minutes: float, five: float | None, resets: datetime.datetime = RESETS) -> dict:
    return log_entry(minutes, "before", five, "patrol", "sonnet", wake=True, resets=resets)


def test_intervals_across_a_new_window_or_an_unread_usage_are_not_used():
    later = RESETS + datetime.timedelta(hours=5)
    entries = as_read([reading(0, 10.0), reading(5, 11.0), reading(10, 20.0, later), reading(15, 21.0, later),
                       reading(20, 22.0, later), reading(30, None), reading(40, 25.0, later),
                       reading(45, 26.0, later), reading(50, 27.0, later), reading(55, 26.5, later)])
    found = usage_index.log_intervals(entries, at(0), at(60))
    assert [(i.start, i.end, i.percent) for i in found.intervals] == [(at(15), at(20), 1.0), (at(45), at(50), 1.0)]
    # Starting at the first line, at the first of a new window and after a line not read,
    # the value was not seen to change.
    assert found.dropped == {"a new 5-hour window opened": 1, "the usage was not read": 2,
                             "the value was not seen to change at its start": 3, "the window fell": 1}


def test_an_interval_that_starts_where_the_value_was_not_seen_to_change_is_not_fitted():
    # 1% is 1,000,000 weighted Opus tokens. The run starts at 7.9%, which reads as 7: 100,000
    # tokens bring it to 8. Fitted as a whole percent, that first interval would pull the
    # rate far below a million.
    def tokens(amount):
        return {"input": amount, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0, "output": 0}
    entries = as_read([reading(0, 7.0), reading(10, 8.0), reading(20, 9.0), reading(30, 10.0)])
    messages = [usage_index.Message(at(5), PARENT, OPUS, tokens(100_000)),
                usage_index.Message(at(15), PARENT, OPUS, tokens(1_000_000)),
                usage_index.Message(at(25), PARENT, OPUS, tokens(1_000_000))]
    found = usage_index.log_intervals(entries, at(0), at(30))
    fitted = usage_index.tokens_per_percent(found.intervals, messages)
    assert fitted["models"][OPUS]["weighted_tokens_per_percent"] == pytest.approx(1_000_000)


@pytest.mark.parametrize("percent", [1e-4, 1e3], ids=["far too many tokens", "far too few"])
def test_a_rate_outside_the_plausible_range_is_told_apart(percent):
    intervals = [usage_index.Interval(at(0), at(10), percent)]
    messages = [usage_index.Message(at(5), PARENT, OPUS, {"input": 1_000_000, "cache_write_5m": 0,
                                                            "cache_write_1h": 0, "cache_read": 0, "output": 0})]
    result = usage_index.tokens_per_percent(intervals, messages)
    assert result["models"] == {}
    assert result["undetermined"] == [OPUS]
    assert result["implausible"] == {OPUS: pytest.approx(1_000_000 / percent)}


def million_each(model: str, percents: list[float]) -> tuple[list, list]:
    """Intervals of these rises, ten minutes each, and a million input tokens of the model in each."""
    tokens = {"input": 1_000_000, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0, "output": 0}
    return ([usage_index.Interval(at(10 * n), at(10 * n + 10), percent) for n, percent in enumerate(percents)],
            [usage_index.Message(at(10 * n + 5), PARENT, model, dict(tokens)) for n in range(len(percents))])


@pytest.mark.parametrize("intervals, marked", [(1, True), (2, False), (3, False)])
def test_a_fit_over_too_few_intervals_for_its_models_says_so(intervals, marked):
    fitted = usage_index.tokens_per_percent(*million_each(OPUS, [1.0] * intervals))
    # The rate is given either way; the mark is what says it is not to be trusted.
    assert fitted["models"][OPUS]["weighted_tokens_per_percent"] == pytest.approx(1_000_000)
    assert ("too_few_intervals" in fitted) is marked
    if marked:
        assert fitted["too_few_intervals"] == "1 intervals for 1 models; at least 2 are needed to trust the rates"


def test_the_intervals_of_a_fit_are_counted_as_a_whole_not_for_each_model():
    # Four intervals for two models are enough by the rule, though Sonnet's tokens lie in one alone.
    intervals, messages = million_each(OPUS, [1.0, 1.0, 1.0, 1.5])
    messages.append(usage_index.Message(at(36), PARENT, SONNET, dict(messages[0].tokens)))
    fitted = usage_index.tokens_per_percent(intervals, messages)
    assert set(fitted["models"]) == {OPUS, SONNET}
    assert "too_few_intervals" not in fitted


def test_intervals_outside_the_range_are_counted_as_dropped():
    entries = as_read([reading(0, 10.0), reading(10, 11.0), reading(20, 12.0), reading(30, 13.0)])
    found = usage_index.log_intervals(entries, at(5), at(25))
    assert [(i.start, i.end) for i in found.intervals] == [(at(10), at(20))]
    assert found.dropped == {"outside the range": 2}


def test_a_model_the_fit_gives_no_positive_cost_is_undetermined():
    def tokens(amount):
        return {"input": amount, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0, "output": 0}
    intervals = [usage_index.Interval(at(0), at(10), 1.0), usage_index.Interval(at(10), at(20), 0.5)]
    messages = [usage_index.Message(at(5), PARENT, OPUS, tokens(1_000_000)),
                usage_index.Message(at(15), PARENT, OPUS, tokens(1_000_000)),
                usage_index.Message(at(16), PARENT, SONNET, tokens(1_000_000))]
    result = usage_index.tokens_per_percent(intervals, messages)
    assert result["models"][OPUS]["weighted_tokens_per_percent"] == pytest.approx(1_000_000)
    assert result["undetermined"] == [SONNET]
    # The undetermined model took a coefficient too, so it counts toward the intervals needed.
    assert result["too_few_intervals"] == "2 intervals for 2 models; at least 4 are needed to trust the rates"


def test_cache_writes_without_the_split_count_as_5_minute_writes():
    assert usage_index.kinds_of({"input_tokens": 1, "cache_creation_input_tokens": 800, "output_tokens": 2}) == {
        "input": 1, "cache_write_5m": 800, "cache_write_1h": 0, "cache_read": 0, "output": 2}


def test_a_line_that_does_not_read_is_counted(tmp_path):
    path = tmp_path / "p" / "s.jsonl"
    write_jsonl(path, [assistant("a1", 5, OPUS, PARENT, input_=10)])
    naive = assistant("a2", 6, OPUS, PARENT, input_=10) | {"timestamp": "2026-01-05T09:06:00"}
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write('{"message": {"usage": {}, "id": "x"}}\n{not json\n' + json.dumps(naive) + "\n")
    found = usage_index.read_transcripts([tmp_path / "p"], T0 - datetime.timedelta(days=1))
    assert (len(found.messages), found.unreadable_lines) == (1, 3)


def test_a_transcript_that_cannot_be_read_is_named(tmp_path, monkeypatch):
    path = tmp_path / "p" / "s.jsonl"
    write_jsonl(path, [assistant("a1", 5, OPUS, PARENT, input_=10)])

    def refuse(self, *args, **kwargs):
        raise PermissionError("locked")
    monkeypatch.setattr(type(path), "read_text", refuse)
    with pytest.raises(usage_index.Unreadable, match="cannot read the transcript s.jsonl: ") as raised:
        usage_index.read_transcripts([tmp_path / "p"], T0 - datetime.timedelta(days=1))
    # The directory names another project, so only the file's name goes out.
    assert tmp_path.name not in str(raised.value)


def as_read(entries: list[dict]) -> list[dict]:
    for entry in entries:
        entry["time"] = datetime.datetime.fromisoformat(entry["time"])
        entry["window"] = usage_index.log_window(entry)
    return entries


def test_percent_per_hour_counts_a_new_window_from_nothing():
    later = RESETS + datetime.timedelta(hours=5)
    entries = as_read([log_entry(0, "start", 40.0), log_entry(30, "before", 42.0, "patrol", "sonnet", True),
                       log_entry(60, "before", 3.0, "patrol", "sonnet", True, resets=later)])
    assert usage_index.percent_per_hour(entries) == {"hours": 1.0, "percent": 5.0, "percent_per_hour": 5.0,
                                                     "new_windows": 1}


@pytest.mark.parametrize("model, ratio", [("claude-opus-5-5", 0.05), ("claude-opus-5-5-20260101", 0.05),
                                          ("claude-fable-5-1", 0.025), ("claude-opus-5", 0.1),
                                          ("claude-haiku-4-5-20251001", 0.1), ("claude-opus-5-5 fast", 0.05)])
def test_a_cache_read_is_weighted_by_its_model(model, ratio):
    tokens = {"input": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 1000, "output": 0}
    assert usage_index.weighted(model, tokens) == pytest.approx(1000 * ratio)


def test_fast_mode_is_a_model_of_its_own(tmp_path):
    write_jsonl(tmp_path / "p" / "s.jsonl", [assistant("f1", 5, OPUS, PARENT, input_=10, speed="fast")])
    [message] = usage_index.read_transcripts([tmp_path / "p"], T0 - datetime.timedelta(days=1)).messages
    assert message.model == "claude-opus-5-5 fast"


def test_a_cycle_that_cannot_be_measured_is_skipped_with_the_reason():
    entries = as_read([log_entry(0, "before", 40.0, "patrol", "sonnet", wake=True),
                       log_entry(10, "after", 1.0, "patrol", "sonnet", resets=RESETS + datetime.timedelta(hours=5)),
                       log_entry(20, "before", None, "urgent", "opus", wake=True),
                       log_entry(30, "after", 3.0, "urgent", "opus"),
                       log_entry(40, "before", 3.0, "urgent", "opus", wake=True),
                       log_entry(50, "after", 4.0, "patrol", "sonnet")])
    result = usage_index.percent_per_cycle(entries)
    assert result["cycles"] == []
    assert [s["why"] for s in result["skipped"]] == [
        "a new 5-hour window opened", "the usage was not read", "the check before names another cycle"]


def test_an_after_without_a_woken_cycle_is_no_cycle():
    entries = as_read([log_entry(0, "before", 10.0, "patrol", "sonnet", wake=False),
                       log_entry(10, "after", 12.0, "patrol", "sonnet")])
    assert usage_index.percent_per_cycle(entries) == {"cycles": [], "skipped": []}


def test_an_unreadable_input_says_so(capsys, world, tmp_path):
    projects, _ = world
    code = usage_index.main(["--usage-log", str(tmp_path / "none.log"), "--transcripts", str(projects),
                             "--session", PARENT])
    assert code == 2
    assert "cannot read the usage log" in json.loads(capsys.readouterr().out)["error"]


def test_a_log_line_it_did_not_foresee_ends_in_one_error_line_and_exit_2(capsys, world, tmp_path):
    projects, _ = world
    log = tmp_path / "usage.log"
    entry = log_entry(0, "before", 10.0, "patrol", "sonnet", wake=True)
    del entry["phase"]
    write_jsonl(log, [entry])
    code = usage_index.main(["--usage-log", str(log), "--transcripts", str(projects)])
    out = capsys.readouterr().out
    assert code == 2
    assert out.count("\n") == 1
    assert json.loads(out)["error"].startswith("the indices failed: KeyError")
